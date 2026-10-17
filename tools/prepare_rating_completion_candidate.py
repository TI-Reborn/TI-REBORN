"""Prepare only owned rating scopes from immutable published public sources."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'reports/gameplay-followup/stage1-interfaces/public-regression'
FOLDER = ROOT / 'reports/gameplay-followup/stage4-ratings'


def write(name, text):
    path = FOLDER / 'runtime' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')


def main():
    if (FOLDER / 'candidate-manifest.json').exists():
        raise ValueError('Preserve frozen rating candidate')
    source = (BASE / 'snapshot/tio/team_ratings.py').read_text(encoding='utf-8')
    source = source.replace('fixed two-account squads', 'fixed four-account Wall squads')
    source = source.replace('All four accounts', 'All eight accounts')
    source = source.replace('team_rating_', 'wall_rating_').replace('team_ranked_', 'wall_ranked_')
    source = source.replace('config/rating_seasons.json', 'config/rating_completion.json')
    source = source.replace("row.get('team_players')!=2", "row.get('team_players')!=4")
    source = source.replace("row.get('version')!=1", "row.get('version')!=1 or row.get('season_rewards')!=[]")
    source = source.replace("not 1<=row.get('maximum_soldiers',0)<=3", "row.get('maximum_soldiers')!=1")
    source = source.replace('len(values)!=2', 'len(values)!=4').replace('len(set(values))!=2', 'len(set(values))!=4')
    source = source.replace('два разных аккаунта', 'четыре разных аккаунта')
    source = source.replace('len(set(accounts))!=4', 'len(set(accounts))!=8')
    source = source.replace('len(set(auth))!=4', 'len(set(auth))!=8')
    source = source.replace('четыре разных игровых аккаунта', 'восемь разных игровых аккаунтов')
    source = source.replace("version=1,match_id=match_id", "version=2,format='wall',match_id=match_id")
    source = source.replace('auth[:2],auth[2:]', 'auth[:4],auth[4:]')
    source = source.replace("frozen.get('version')!=1", "frozen.get('version')!=2 or frozen.get('format')!='wall'")
    source = source.replace('len(set(a for team in auth for a in team))!=4', 'len(set(a for team in auth for a in team))!=8')
    source = source.replace('rating_seasons.schema(db)', 'season_schema(db)')
    source = source.replace('rating_seasons.current(db,now)', 'current(db,now)')
    source = source.replace('rating_seasons.close_finished(db,now)', 'close_finished(db,now)')
    source = source.replace('rating_seasons.listing(db)', 'seasons(db)')
    source = source.replace('snapshot(db,team,scope)', 'snapshot(db,team,scope)')
    source = source.replace('return frozen\n\n\n', 'return frozen\n\n\n')
    seasons = (BASE / 'snapshot/tio/rating_seasons.py').read_text(encoding='utf-8')
    seasons = seasons[seasons.index('def schema(db):'):]
    seasons = seasons.replace('def schema(db):', 'def season_schema(db):').replace('schema(db)', 'season_schema(db)')
    seasons = seasons.replace('def season_season_schema(db):', 'def season_schema(db):')
    seasons = seasons.replace('team_rating_', 'wall_rating_').replace('team_ranked_', 'wall_ranked_')
    seasons = seasons.replace('boundary(now)', 'rating_seasons.boundary(now)').replace('def listing(', 'def seasons(')
    source += '\n\n' + seasons
    source = source.replace('a fixed pair\'s rating', 'a fixed Wall squad\'s rating')
    source = source.replace('fixed pair', 'fixed Wall squad').replace('fixed squads', 'fixed Wall squads')
    write('tio/rating_completion.py', source)
    policy = dict(version=1,team_players=4,minimum_level=4,maximum_level=20,maximum_soldiers=1,
                  calendar='UTC calendar month',repeat_window_seconds=86400,maximum_rated_opposing_pairs=3,
                  rating_model='Gaussian two-team model; a fixed four-account squad is one rating entity',
                  draw_policy='Keep Gaussian rating; count the draw',season_rewards=[],
                  historical_season_schedule_confirmed=False,
                  historical_season_rewards_confirmed=False,
                  qualification='Eight distinct authenticated human accounts, no AI, both sides cause authoritative opposing damage',
                  wall_rating_is_server_policy=True,ranked_soldiers_minimum=1,ranked_soldiers_maximum=4,
                  ranked_matching='Equal soldier count and current classic level band; saved equipment only')
    write('config/rating_completion.json',json.dumps(policy,ensure_ascii=False,indent=2)+'\n')
    for name in ('server/team_ranked.py','server/ranked_arena.py','server/team_arena.py',
                 'tio/battle_rewards.py','tools/survival_scene.py'):
        write(name,(BASE/'snapshot'/name).read_text(encoding='utf-8'))
    # Stage9's published assault admission patch is the only difference in this
    # consumer; never use unrelated shared local runtime.
    frozen = ROOT/'reports/gameplay-completion/stage9-interfaces-revision2'
    manifest = json.loads((frozen/'candidate-manifest.json').read_text(encoding='utf-8'))
    entry = manifest['files']['tio/team_scene.py']
    raw = (frozen/entry['source']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise ValueError('Changed published scope')
    write('tio/team_scene.py',raw.decode('utf-8'))
    print('Prepared owned rating scopes; no manifest frozen and no hosted changes')


if __name__=='__main__':main()
