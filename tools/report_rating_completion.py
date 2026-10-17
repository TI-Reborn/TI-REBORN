"""Record reviewable rating evidence and a strict read-only UI contract."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/gameplay-followup/stage4-ratings'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name,value):
    target=FOLDER/name
    if target.exists():raise ValueError('Preserve existing rating report: '+name)
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
    integer=dict(type='integer');stamp={**integer,'minimum':0}
    def obj(fields,**extra):return dict(type='object',additionalProperties=False,required=list(fields),properties=fields,**extra)
    season=obj(dict(id=dict(type='string',pattern=r'^\d{4}-(?:0[1-9]|1[0-2])$'),
                    startsAt=stamp,endsAt=stamp,state=dict(enum=['open','closing','archived']),
                    archivedAt=dict(anyOf=[stamp,dict(type='null')])))
    row=obj(dict(teamId=dict(type='string',pattern=r'^[0-9a-f]{64}$'),
                 names=dict(type='array',minItems=2,maxItems=4,items=dict(type='string')),
                 place={**integer,'minimum':1},skill={**integer,'minimum':0,'maximum':400},
                 wins=stamp,losses=stamp,draws=stamp,unrated=stamp))
    fields=dict(version=dict(const=1),format=dict(enum=['pairs','wall']),
                playersPerSide=dict(enum=[2,4]),soldiersPerPlayer=dict(enum=[1,3]),
                scope=dict(type='string',pattern=r'^(?:all|\d{4}-(?:0[1-9]|1[0-2]))$'),
                calendar=dict(const='UTC calendar month'),currentSeason=obj({k:v for k,v in season['properties'].items() if k in ('id','startsAt','endsAt')}),
                seasonState=dict(enum=['all','not_created','open','closing','archived']),
                archived=dict(type='boolean'),offset={**integer,'minimum':0,'maximum':9990},
                limit={**integer,'minimum':1,'maximum':100},total=stamp,hasMore=dict(type='boolean'),
                rows=dict(type='array',maxItems=100,items=row),seasons=dict(type='array',maxItems=12,items=season),
                rewards=dict(type='array',maxItems=0),historicalSeasonScheduleConfirmed=dict(const=False),
                historicalSeasonRewardsConfirmed=dict(const=False),ratingModel=dict(const='Fixed squad Gaussian model; server policy'))
    schema={'$schema':'https://json-schema.org/draft/2020-12/schema',**obj(fields),
            'description':'Read-only public listing; no login, save-owner alias, wallet or mutation arguments.'}
    # Python's reserved keyword cannot be used in keyword args. JSON Schema's
    # actual conditional documents the relationship without adding DTO fields.
    schema['allOf']=[{'if':{'properties':{'format':{'const':'pairs'}}},
                     'then':{'properties':{'playersPerSide':{'const':2},'soldiersPerPlayer':{'const':3},
                         'rows':{'items':{'properties':{'names':{'minItems':2,'maxItems':2}}}}}},
                     'else':{'properties':{'playersPerSide':{'const':4},'soldiersPerPlayer':{'const':1},
                         'rows':{'items':{'properties':{'names':{'minItems':4,'maxItems':4}}}}}}}]
    write('rating-contract.schema.json',schema)
    manual=ROOT/'reports/chat-presence/TIO_manual.pdf'
    native=FOLDER/'native-abi.json';proof=json.loads(native.read_text(encoding='utf-8'))
    research=dict(version=1,utc=datetime.now(timezone.utc).isoformat(),
        confirmed=[dict(source='Original manual',path=str(manual.relative_to(ROOT)),printedPages=[14,15,16],
                        sha256=sha(manual),facts=['Team: two players per side and up to three soldiers each',
                        'Wall: four players per side and one soldier each','Survival: two to four independent players, not a fixed team format']),
                   dict(source='Original administration announcement, 2012-05-03',
                        url='https://ggeek.ru/forum/vyberite-razdel/81118-trueskill/',
                        facts=['TrueSkill permits one to four mercenaries per player, levels4..20',
                               'Multiple mercenaries do not prove three/four authenticated human owners per TrueSkill team']),
                   dict(source='Pinned original Silver x86 numeric code',sha256=proof['silver_sha256'],
                        proof='native-abi.json',assembler='original-c6-writer-readers.asm',
                        facts=['C6/21 request has two boolean flags, count and owned pet records; flags are not player count',
                               'C6/03 projects individual rating/league/place/streak, not seasons',
                               'C6/04 loops two sides and variable player and actor lists',
                               'C6/04 reader loops alone do not establish historical queue dimensions',
                               'BA/C8 Wall4v4 remains its existing native transport'])],
        unconfirmed=['Permanent human teams3v3 in TrueSkill',
                     'Historical permanent Wall squad TrueSkill formula',
                     'Historical UTC month seasons or season prize schedule',
                     'Historical fourth-mercenary turn duration',
                     'Clan/alliance TrueSkill formula behind native selector1',
                     'Unified original seasonal/team table screen and season selector packet',
                     'Exact cross-band TrueSkill combat normalization and token kit economy'],
        explicit_server_policy=['Independent fixed-four-account Gaussian entity with existing ranked.infer',
            'Wall season: calendar UTC month; archive waits for all admitted pending matches',
            'Keep draw Gaussian values; count draw; both sides must cause opposing damage',
            'Up to three rated opposing account pairings per86400sec, aliases canonicalized',
            'C6 squad count1..4; equal opposing count, current classic bands, saved equipment',
            'Fourth mercenary turn120sec; previous classic1/2/3 timers unchanged',
            'No seasonal item/Credits/Gold rewards assigned'],
        ui=dict(privateChat=['!teamrating wall [YYYY-MM|all] [page]','!seasons wall'],
                readOnlyHelper="tio.rating_completion.public_listing(db,format='pairs'|'wall',scope=None|'all'|'YYYY-MM',offset=0,limit=10,now=None)",
                schema='rating-contract.schema.json',
                scope='No new HTTP endpoint or portal page in this bounded delivery; parent owns integration',
                graphical_client_acceptance=False),
        historical_rewards=dict(teamSeasonRewards=[],knownWeeklyAssaultBadges='Separate already implemented subsystem, not team season rewards'),
        source_baseline='Immutable hosted public .5 snapshot plus frozen published stage9 revision2 overrides',
        hosted_changes=False,hosted_player_data_opened=False,hosted_player_data_copied=False)
    write('research.json',research)
    result_path=FOLDER/'final/public-regression-candidate/local-isolated.json'
    if not result_path.exists():raise ValueError('Final proof not finished')
    result=json.loads(result_path.read_text(encoding='utf-8'))
    corrected_path=FOLDER/'shared-abi-correction.json'
    corrected=json.loads(corrected_path.read_text(encoding='utf-8'))
    events=[json.loads(line) for line in (FOLDER/'final/public-regression-candidate/local-test-events.jsonl').read_text(encoding='utf-8').splitlines()]
    failures=[e['test'] for e in events if e['outcome'] in ('failure','error')]
    if (failures!=[corrected['test']] or result['result']['tests_run']!=124 or
        result['result']['failures']!=1 or result['result']['errors'] or result['result']['skips'] or
        not corrected['passed'] or not corrected['sourceUnchanged'] or not result['source_unchanged']):
        raise ValueError('Combined regression evidence changed or incomplete')
    selected=result['selected_modules'];native_checks=len(proof['checks'])
    summary=dict(version=1,utc=datetime.now(timezone.utc).isoformat(),passed=corrected['passed'] and proof['passed'],
        automated_server=dict(tests=result['result']['tests_run'],seconds=result['seconds'],
                              failures=result['result']['failures'],errors=result['result']['errors'],skips=result['result']['skips'],
                              sourceUnchanged=result['source_unchanged'],modules=selected,proof=str(result_path.relative_to(FOLDER)),
                              proofSha256=sha(result_path),wholePublicSuite=False,
                              combinedPassed=124,combinedFailed=0,initialRunPreserved=True,
                              correctionProof='shared-abi-correction.json',correctionProofSha256=sha(corrected_path),
                              correctedTest=corrected['test'],repeatedPassedCases=0),
        nativeABI=dict(checks=native_checks,passed=proof['passed'],proof='native-abi.json',proofSha256=sha(native)),
        delivery=dict(files=8,manifest='final/delivery-manifest.json',manifestSha256=sha(FOLDER/'final/delivery-manifest.json')),
        retainedFailedIterations=['validation1','validation2','validation3'],
        failureClassification=dict(validation1='Classic C6 timing cap; new Wall readiness fixture confirmed too early; unordered archive query and wrong reply opcode in new tests',
            validation2='Native errors confirm C6 classic cap and new fixture readiness. Initial outer-runner log decode failed under Windows cp1252; UTF8 read corrected, captured rerun retained',
            validation3='Second C6 timing cap at tick; Wall month-boundary fixture used real settlement wallclock instead of simulated clock'),
        hostedChanges=False,hostedPlayerDataCopied=False,graphicalClientAcceptance=False,
        limitations=research['unconfirmed'])
    write('validation.json',summary)
    pins={name:sha(FOLDER/'final/runtime'/name) for name in json.loads((FOLDER/'final/delivery-manifest.json').read_text())['files']}
    pins.update({str((ROOT/'tests'/name).relative_to(ROOT)):sha(ROOT/'tests'/name) for name in
                 ('test_rating_completion.py','test_ranked_squads.py','test_wall_ranked.py')})
    pins['rating-contract.schema.json']=sha(FOLDER/'rating-contract.schema.json')
    pins['manual.pdf']=sha(manual);pins['native-abi.json']=sha(native)
    write('source-pins.json',dict(version=1,sha256=pins))
    print(json.dumps(dict(passed=summary['passed'],server_tests=summary['automated_server']['tests'],native_checks=native_checks,net_files=8)))


if __name__=='__main__':main()
