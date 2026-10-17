"""Record observed GUI checks without upgrading partial acceptance to complete."""
import json
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
folder = root / 'reports/gameplay-followup/stage1-interfaces/graphical-adapter-revision3'
target = folder / 'graphical-acceptance.json'
if target.exists():
    raise ValueError('Preserve existing GUI evidence')
result = dict(
    utc=datetime.now(timezone.utc).isoformat(),
    run='runs/20261008T184331.362408Z',
    client_version='2026.10.08.6',
    actual_native_clients=2,
    actual_hosted_accounts=2,
    owned_fixture_only=True,
    authentication='Original callbacks returned success for both owned accounts; authentication dialog automation was not used',
    passed=[
        'Both clients entered hosted Reservation with their existing accounts',
        'SC catalogue opened through native city interface',
        'Closed SC window stayed closed through passive server updates',
        'Both human accounts joined the same hosted survival battle and received turns',
        'Ordinary movement spent one AP on the selected actor',
        'Native inventory staged the existing pistol without charging AP',
        'Native inventory OK committed equipment: AP changed from 14 to 12',
    ],
    cleanup='Both dedicated clients received native Alt+F4; adapter released its bound process handles. No checkpoint or player save was rewritten.',
    limitations=[
        'Full graphical acceptance remains incomplete',
        'Both accounts have zero Gold: paid NVG positive use and SC purchase were not exercised',
        'Only weapon equipment was changed visually; multi-item atomicity is covered by automated/native checks',
        'Battle ended by closing dedicated clients; a native results-window return was not verified',
        'Portal city page was observed only as an anonymous redirect to login; no authenticated browser acceptance',
    ],
    graphical_acceptance_complete=False,
)
target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
p = root / 'reports/gameplay-followup/progress.json'
progress = json.loads(p.read_text(encoding='utf-8'))
progress['phases'][0]['graphical_startup'] = 'Revision3: two owned native clients authenticated, entered city and shared hosted fight'
progress['phases'][0]['graphical_evidence'] = str(target.relative_to(root)).replace('\\', '/')
progress['phases'][2]['server_package'] = 'reports/gameplay-completion/stage11-warehouse-services-r5'
p.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(dict(recorded=True, graphical_acceptance_complete=False)))
