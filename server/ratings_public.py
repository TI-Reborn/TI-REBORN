"""Read-only squad standings inside the authoritative gameplay process.

The private portal supplies its verified account login. No save-owner keys,
wallet creation, season rollover or arbitrary SQL are accepted here.
"""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
import time

from .accounts import identity
from .city_operations import CityError
from tio import rating_completion, rating_seasons

FIELDS = frozenset(('username', 'format', 'scope', 'offset', 'limit'))
PAGE_SIZE = 10
MAX_OFFSET = 9990
MAX_INTEGER = 2**53 - 1
MAX_EPOCH = 253370764800  # The last supported season ends before year 9999.


def _month(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-(?:0[1-9]|1[0-2])', value):
        raise ValueError('Invalid public season identity')
    return rating_seasons.validate(value)


def validate_payload(data):
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise CityError('invalid_request')
    try:
        identity(data['username'])
        if data['scope'] not in (None, 'all'): _month(data['scope'])
    except (TypeError, ValueError): raise CityError('invalid_request') from None
    if (data['format'] not in ('pairs', 'wall') or type(data['offset']) is not int
        or not 0 <= data['offset'] <= MAX_OFFSET or data['offset'] % PAGE_SIZE
        or type(data['limit']) is not int or data['limit'] != PAGE_SIZE):
        raise CityError('invalid_request')
    return data


def _integer(value, low=0, high=MAX_INTEGER):
    if type(value) is not int or not low <= value <= high: raise ValueError('Invalid public rating scalar')


def _season(value, *, current=False):
    fields = {'id', 'startsAt', 'endsAt'} if current else {'id', 'startsAt', 'endsAt', 'state', 'archivedAt'}
    if not isinstance(value, dict) or set(value) != fields: raise ValueError('Invalid public season')
    _month(value['id'])
    for field in ('startsAt', 'endsAt'): _integer(value[field], 0, MAX_EPOCH)
    season, start, end = rating_seasons.boundary(value['startsAt'])
    if season != value['id'] or value['startsAt'] != start or value['endsAt'] != end:
        raise ValueError('Invalid public season boundaries')
    if not current:
        if value['state'] not in ('open', 'closing', 'archived'): raise ValueError('Invalid public season state')
        stamp = value['archivedAt']
        if stamp is not None: _integer(stamp, value['endsAt'], MAX_EPOCH)
        if (value['state'] == 'archived') != (stamp is not None): raise ValueError('Invalid public archive')


def validate_response(value, request):
    """Both private HTTP hops reject malformed, extra or cross-query fields."""
    validate_payload(request)
    if not isinstance(value, dict) or set(value) != {'username', 'ratings'} or value['username'] != request['username']:
        raise ValueError('Invalid public rating identity')
    dto = value['ratings']
    fields = {'version', 'format', 'playersPerSide', 'soldiersPerPlayer', 'scope', 'calendar', 'currentSeason',
              'seasonState', 'archived', 'offset', 'limit', 'total', 'hasMore', 'rows', 'seasons', 'rewards',
              'historicalSeasonScheduleConfirmed', 'historicalSeasonRewardsConfirmed', 'ratingModel'}
    if not isinstance(dto, dict) or set(dto) != fields: raise ValueError('Invalid public rating fields')
    if (type(dto['version']) is not int or dto['version'] != 1 or dto['format'] != request['format']
        or type(dto['playersPerSide']) is not int or dto['playersPerSide'] != (2 if request['format'] == 'pairs' else 4)
        or type(dto['soldiersPerPlayer']) is not int or dto['soldiersPerPlayer'] != (3 if request['format'] == 'pairs' else 1)
        or dto['calendar'] != 'UTC calendar month' or dto['rewards'] != []
        or dto['historicalSeasonScheduleConfirmed'] is not False or dto['historicalSeasonRewardsConfirmed'] is not False
        or dto['ratingModel'] != 'Fixed squad Gaussian model; server policy'):
        raise ValueError('Invalid public rating policy')
    _season(dto['currentSeason'], current=True)
    expected_scope = dto['currentSeason']['id'] if request['scope'] is None else request['scope']
    if dto['scope'] != expected_scope: raise ValueError('Invalid public rating scope')
    if dto['seasonState'] not in ('all', 'not_created', 'open', 'closing', 'archived'):
        raise ValueError('Invalid public rating season state')
    if (dto['seasonState'] == 'all') != (dto['scope'] == 'all') or type(dto['archived']) is not bool or dto['archived'] != (dto['seasonState'] == 'archived'):
        raise ValueError('Invalid public rating archive state')
    for field in ('offset', 'limit', 'total'): _integer(dto[field])
    if dto['offset'] != request['offset'] or dto['limit'] != request['limit'] or type(dto['hasMore']) is not bool:
        raise ValueError('Invalid public rating pagination')
    rows = dto['rows']
    if (not isinstance(rows, list) or len(rows) != max(0, min(dto['limit'], dto['total'] - dto['offset']))
        or dto['hasMore'] != (dto['offset'] + len(rows) < dto['total'])):
        raise ValueError('Invalid public rating rows')
    seen = set(); prior = 401
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'teamId', 'names', 'place', 'skill', 'wins', 'losses', 'draws', 'unrated'}:
            raise ValueError('Invalid public rating row')
        team = row['teamId']
        if not isinstance(team, str) or not re.fullmatch('[a-f0-9]{64}', team) or team in seen:
            raise ValueError('Invalid public squad identity')
        seen.add(team)
        names = row['names']
        if (not isinstance(names, list) or len(names) != dto['playersPerSide'] or any(
            not isinstance(name, str) or not 1 <= len(name) <= 64 or any(ord(c) < 32 or ord(c) == 127 for c in name) for name in names)):
            raise ValueError('Invalid public squad names')
        _integer(row['place'], 1, dto['total']); _integer(row['skill'], 0, 400)
        for field in ('wins', 'losses', 'draws', 'unrated'): _integer(row[field])
        if row['wins'] + row['losses'] + row['draws'] < 1 or row['skill'] > prior:
            raise ValueError('Invalid public squad order')
        prior = row['skill']
    seasons = dto['seasons']
    if not isinstance(seasons, list) or len(seasons) > 12: raise ValueError('Invalid public seasons')
    seen = set(); prior = MAX_EPOCH + 1
    for season in seasons:
        _season(season)
        if season['id'] in seen or season['startsAt'] >= prior: raise ValueError('Invalid public season order')
        seen.add(season['id']); prior = season['startsAt']
    return value


class RatingsPublic:
    def __init__(self, router, *, clock=time.time):
        self.router, self.path, self.clock = router, Path(router.config.database).resolve(), clock

    def status(self, data):
        data = validate_payload(data)
        with self.router.team_arena.lock:
            if self.router.server.stopping.is_set(): raise CityError('service_unavailable', 503)
            with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as db:
                db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
                if not db.execute('SELECT 1 FROM accounts WHERE login=?', (data['username'],)).fetchone():
                    raise CityError('account_not_found', 404)
                result = dict(username=data['username'], ratings=rating_completion.public_listing(db,
                    format=data['format'], scope=data['scope'], offset=data['offset'], limit=data['limit'], now=self.clock()))
                return validate_response(result, data)
