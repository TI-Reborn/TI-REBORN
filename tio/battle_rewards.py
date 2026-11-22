"""Authoritative PvP rewards, persisted once per match/account."""

from .db_transaction import connect, transaction
from contextlib import closing
from fractions import Fraction
import json
import sqlite3
from .protocol.asset_count import AssetCount


def settle(path,account,match_id,result,*,health=None,rental_tax=0,rank_report=None,
           escaped=False,rental_units=None,mined_crystals=None,achievement_report=None,experience_report=None,
           reward_context=None,statistics_report=None,ranked_report=None,encounter_report=None,now=None,mine_extraction=None,team_ranked_report=None,
           wager=False,wager_report=None,contract_report=None,reservation_survival: bool = False,
           tournament_proficiency: dict[int, tuple[tuple[int, ...], tuple[int, ...]]] | None = None):
    if result not in (0,1,2):raise ValueError('Invalid battle result')
    if type(rental_tax) is not int or rental_tax<0:
        raise ValueError('Invalid rental tax')
    with transaction(path) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS battle_rewards (
            match_id TEXT NOT NULL, account TEXT NOT NULL, result INTEGER NOT NULL,
            credits INTEGER NOT NULL, PRIMARY KEY(match_id,account))''')
        columns={r[1] for r in db.execute('PRAGMA table_info(battle_rewards)')}
        for column in ('gross','rental_tax'):
            if column not in columns:db.execute(f'ALTER TABLE battle_rewards ADD COLUMN {column} INTEGER')
        if 'calculation' not in columns:db.execute('ALTER TABLE battle_rewards ADD COLUMN calculation TEXT')
        prior=db.execute('SELECT result,credits FROM battle_rewards WHERE match_id=? AND account=?',(match_id,account)).fetchone()
        wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(account,)).fetchone()
        if wallet is None:raise ValueError('Battle wallet missing')
        if prior is not None:
            if prior[0]!=result:raise ValueError('Conflicting battle result')
            from .clans import project_assets
            return project_assets(db,account,AssetCount(*wallet))
        if wager:
            # The reserved pot is the sole reward. Persist wounds and ordinary
            # equipment consumption, but never pass through progression hooks.
            if any(v is not None for v in (rank_report,experience_report,reward_context,
                    statistics_report,ranked_report,team_ranked_report,achievement_report,
                    encounter_report,mine_extraction,mined_crystals,tournament_proficiency)):
                raise ValueError('Wager report contains ordinary progression')
            from . import wagers
            wagers.schema(db)
            if not db.execute('SELECT 1 FROM wager_members WHERE match_id=? AND account=?',(match_id,account)).fetchone():
                raise ValueError('Account did not participate in this wager')
            if health:
                from .battle_recovery import save_wounds
                save_wounds(db,account,health)
            amount=0
            if wager_report is not None:
                receipts=wagers.settle(db,match_id,wager_report,now=now)
                amount=receipts[account][1]
            db.execute('INSERT INTO battle_rewards(match_id,account,result,credits,gross,rental_tax,calculation) VALUES (?,?,?,?,?,?,?)',
                       (match_id,account,result,amount,amount,0,json.dumps(dict(wager=True,report=wager_report),sort_keys=True)))
            current=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(account,)).fetchone()
            from .clans import project_assets
            return project_assets(db,account,AssetCount(*current))
        if wager_report is not None:raise ValueError('Wager outcome requires a wager battle')
        percent=0
        if reward_context is not None:
            from .ranks import sync,credit_percent
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='owned_pets'").fetchone():
                sync(db,account,active=True)
                percent=credit_percent(db,account)
        from .reward_policy import calculate
        gross,calculation=calculate(db,account,match_id,result,
            reward_context if mined_crystals is None or mine_extraction is not None else None,percent,escaped=escaped,now=now)
        tournament = tournament_proficiency is not None
        if tournament:
            gross = 0
            audit = json.loads(calculation)
            audit['tournament'] = True
            calculation = json.dumps(audit, sort_keys=True)
        if mine_extraction is not None:
            audit=json.loads(calculation);audit['mining_credit_reward']=0
            calculation=json.dumps(audit,sort_keys=True);gross=0
        repeat=Fraction(json.loads(calculation)['progression_repeat'])
        if encounter_report is not None:
            from .world_encounters import reward
            gross,calculation=reward(encounter_report,result,escaped=escaped)
        if contract_report is not None:
            if result != 1 or escaped or any(v is not None for v in
                    (reward_context, ranked_report, team_ranked_report, encounter_report,
                     mine_extraction, mined_crystals, statistics_report, rank_report)):
                raise ValueError('Invalid contract settlement context')
            expected_keys = {'version','instance_id','match_id','owner','login','credits','experience','bonus_experience'}
            if (set(contract_report) != expected_keys or contract_report['version'] != 1
                    or contract_report['owner'] != account or contract_report['match_id'] != match_id):
                raise ValueError('Invalid contract settlement report')
            from .pve_contracts import ContractStore
            award = ContractStore(path).claim_award(contract_report['instance_id'], account)
            if award is None or any(award[k] != contract_report[k] for k in
                    ('instance_id','match_id','owner','login','credits','experience')):
                raise ValueError('Missing or conflicting contract award')
            selected = award['selected']
            quotient, remainder = divmod(award['experience'], len(selected))
            expected_bonus = {int(identity): quotient + int(index < remainder)
                              for index, identity in enumerate(selected)}
            bonus = {int(identity): value for identity, value in contract_report['bonus_experience'].items()}
            if bonus != expected_bonus or any(type(value) is not int for value in bonus.values()):
                raise ValueError('Invalid frozen contract experience bonus')
            gross = award['credits']
            calculation = json.dumps(dict(contract=contract_report, progression_repeat='1'), sort_keys=True)
        from .premium import state,experience_multiplier
        premium_kind,_=state(db,account,now)
        numerator,denominator=experience_multiplier(db,account,now)
        contract_match = contract_report is not None
        if not contract_match and db.execute("SELECT 1 FROM sqlite_master WHERE name='pve_contract_instances'").fetchone():
            contract_match = db.execute('SELECT 1 FROM pve_contract_instances WHERE match_id=?', (match_id,)).fetchone() is not None
        if contract_match and numerator:
            numerator,denominator=1,1
        progression_factor=repeat
        experience_factor=progression_factor*Fraction(numerator,denominator)
        frozen=None
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='world_city_matches'").fetchone():
            if db.execute('SELECT 1 FROM world_city_matches WHERE match_id=?',(match_id,)).fetchone():
                from .world_completion import frozen_city
                frozen=frozen_city(db,match_id)
                progression_factor*=Fraction(frozen['experience'])
                experience_factor*=Fraction(frozen['experience'])
                if frozen['town_id']==4:rank_report={}
        if premium_kind and not contract_match:
            audit=json.loads(calculation);audit['premium_kind']=premium_kind
            audit['before_premium']=gross;gross=gross*3//2
            calculation=json.dumps(audit,sort_keys=True)
        if rental_units is not None:
            rental_units=tuple(rental_units)
            if any(type(n) is not int or not 0<=n<=4 for n in rental_units):raise ValueError('Invalid rental units')
            from .rental import training_rental_tax
            rental_tax=training_rental_tax(gross,rental_units)
        if rental_tax>gross:raise ValueError('Invalid rental tax')
        reward=gross-rental_tax
        if wallet[0]+reward>0xffffffff:raise ValueError('Credit balance overflow')
        if health:
            from .battle_recovery import save_wounds
            save_wounds(db,account,health)
        if tournament_proficiency:
            from .weapon_proficiency import settle_proficiencies
            settle_proficiencies(db, account, tournament_proficiency)
        if experience_report:
            from .level_progression import settle_experience,MAX_XP
            if any(type(n) is not int or not 0<=n<=MAX_XP for n in experience_report.values()):
                raise ValueError('Invalid battle experience')
            bonus = {int(identity): value for identity, value in contract_report['bonus_experience'].items()} if contract_report else {}
            if any(experience_report.get(identity, 0) < value for identity, value in bonus.items()):
                raise ValueError('Contract experience bonus missing from report')
            # Anti-experience suppresses level XP, not the combat contribution
            # used for clan influence. Keep repeat/city limits on both paths.
            influence_factor=experience_factor if numerator else progression_factor
            influence_report={i:min(MAX_XP,(n-bonus.get(i,0))*influence_factor.numerator//influence_factor.denominator+bonus.get(i,0)) for i,n in experience_report.items()}
            experience_report={i:min(MAX_XP,(n-bonus.get(i,0))*experience_factor.numerator//experience_factor.denominator+(bonus.get(i,0) if numerator else 0)) for i,n in experience_report.items()}
            settle_experience(db,account,match_id,experience_report,keep_full_health=tournament)
            if not tournament:
                from .clans import settle_influence
                from .cities import CITIES
                city=CITIES.get(reward_context.town_id) if reward_context is not None else None
                settle_influence(db,account,influence_report,identity=match_id,
                    city_coefficient=Fraction(frozen['influence']) if frozen is not None else 1 if city is None else city.influence,now=now)
        if rank_report:
            from .ranks import settle_ranks
            settle_ranks(db,account,match_id,result,rank_report,escaped=escaped,now=now,
                         repeat_factor=repeat)
        if mined_crystals is not None:
            from .crystal_market import CrystalMarket
            if mine_extraction is None:CrystalMarket.extract(db,account,match_id,mined_crystals)
            else:
                if mine_extraction.get('extractor')!=account:raise ValueError('Mine extraction belongs to another account')
                CrystalMarket.settle_mine(db,match_id,**mine_extraction)
        if statistics_report is not None:
            from .player_statistics import settle_statistics
            settle_statistics(db,account,match_id,result,statistics_report,now=now)
        if ranked_report is not None:
            from .ranked import settle as settle_ranked
            teams=ranked_report['teams'];winner=ranked_report['winner']
            side=next((i for i,team in enumerate(teams) if any(p[0]==account for p in team)),None)
            if side is None or result!=(2 if winner is None else int(side==winner)):
                raise ValueError('Ranked reward result mismatch')
            settle_ranked(db,match_id,ranked_report,now=now)
        if team_ranked_report is not None:
            from . import team_ratings,rating_completion
            frozen=team_ranked_report.get('frozen',{})
            if frozen.get('version')==1:implementation=team_ratings
            elif frozen.get('version')==2 and frozen.get('format')=='wall':implementation=rating_completion
            else:raise ValueError('Unknown team rating report version')
            implementation.validate_reward(account,result,team_ranked_report,escaped=escaped)
            implementation.settle(db,match_id,team_ranked_report,now=now)
        if encounter_report is not None:
            from .encounter_loot import award
            award(db,account,match_id,result,encounter_report,escaped=escaped)
            if result!=1:
                from .world_encounters import return_defeated
                return_defeated(db,account,match_id,health)
        # Preserve the effective positive progression factors alongside the
        # frozen pair calculation. Penalties and wounds are never discounted.
        audit=json.loads(calculation)
        audit['progression_repeat']=str(repeat)
        audit['experience_factor']=str(experience_factor)
        audit['rank_positive_factor']=str(repeat*(2 if result==1 else 1)*
            (Fraction(3,2) if premium_kind==1 else 1))
        calculation=json.dumps(audit,sort_keys=True)
        db.execute('INSERT INTO battle_rewards(match_id,account,result,credits,gross,rental_tax,calculation) VALUES (?,?,?,?,?,?,?)',
                   (match_id,account,result,reward,gross,rental_tax,calculation))
        db.execute('UPDATE wallets SET credits=credits+? WHERE account=?',(reward,account))
        if reservation_survival and not escaped:
            from .reservation_quests import survival_result
            survival_result(db,account,result)
        if achievement_report is not None:
            from .achievements import settle_battle,update
            settle_battle(db,account,achievement_report,result,escaped=escaped)
            update(db,account,maximum={'credits_peak':wallet[0]+reward})
        from .clans import project_assets
        return project_assets(db,account,AssetCount(wallet[0]+reward,wallet[1]))


def receipt(path,account,match_id):
    with closing(connect(path)) as db:
        return db.execute('SELECT gross,rental_tax FROM battle_rewards WHERE match_id=? AND account=?',(match_id,account)).fetchone()
