"""Freeze a reviewed portal overlay after its isolated validation succeeds."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/gameplay-followup/stage34-portal-integration'
SCOPE = REPORT / 'runtime/web'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, value):
    destination = REPORT / name
    if destination.exists():
        raise ValueError('Preserve frozen delivery evidence: ' + name)
    destination.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def main():
    proof = read(REPORT / 'validation2/validation.json')
    pins = read(REPORT / 'validation2/source-pins.json')
    wire = read(REPORT / 'services-wire-r6-proof.json')
    inputs = read(REPORT / 'frozen-inputs.json')
    hunks = read(REPORT / 'reviewed-hunks.json')['hunks']
    files = {p.relative_to(SCOPE).as_posix(): sha(p) for p in sorted(SCOPE.rglob('*')) if p.is_file()}
    if not proof['passed'] or proof['testCounts'] != {'tests': 94, 'pass': 94, 'fail': 0, 'skipped': 0}:
        raise ValueError('Expected final 94-test web validation')
    if files != pins['scoped']:
        raise ValueError('Validated scoped web changed')
    if not wire['passed'] or not wire['source_unchanged']:
        raise ValueError('Frozen r6 wire verification failed')
    fixture = 'tests/fixtures/stage11-services-r6.json'
    if files[fixture] != wire['dataSha256']:
        raise ValueError('Services wire fixture changed')
    if any(sha(ROOT / 'web' / name) != expected for name, expected in pins['baseline'].items()):
        raise ValueError('Shared web baseline changed after validation')
    # Each existing target has a byte-exact before guard and deterministic edits.
    for name, hunk in hunks.items():
        target = ROOT / name
        if sha(target) != hunk['before_sha256']:
            raise ValueError('Reviewed target changed: ' + name)
        content = target.read_bytes().decode('utf-8')
        for edit in hunk.get('edits', [dict(before=hunk.get('before'), after=hunk.get('after'))]):
            if content.count(edit['before']) != 1:
                raise ValueError('Ambiguous reviewed hunk: ' + name)
            content = content.replace(edit['before'], edit['after'])
        if hashlib.sha256(content.encode('utf-8')).hexdigest() != hunk['after_sha256']:
            raise ValueError('Reviewed after hash differs: ' + name)
    origins = {}
    for name, original in inputs['frozen_files'].items():
        if sha(ROOT / original['source']) != original['sha256']:
            raise ValueError('Original frozen source changed: ' + name)
        if name != 'src/lib/services-contract.ts' and files[name] != original['sha256']:
            raise ValueError('Unexpected overlay change: ' + name)
        origins[name] = original
    # The only change to original feature sources is the reviewed nonce rule.
    name = 'src/lib/services-contract.ts'
    before = (ROOT / origins[name]['source']).read_bytes()
    after = before.replace(b'/^[A-Za-z0-9_-]{16,64}$/', b'/^[A-Za-z0-9][A-Za-z0-9_-]{15,63}$/')
    if after == before or (SCOPE / name).read_bytes() != after:
        raise ValueError('Unexpected services contract change')
    old_wire = read(REPORT / 'revisions/stage11-r5/stage11-services.json')
    new_wire = read(SCOPE / fixture)
    preserved_dto = all(old_wire[name] == new_wire[name] for name in ('states', 'replies', 'requests'))
    if not preserved_dto:
        raise ValueError('r5/r6 status, receipt or request fixture changed unexpectedly')
    utc = datetime.now(timezone.utc).isoformat()
    delivery = dict(version=1, utc=utc, scope='Portal services, ratings, account navigation and four accepted fund UI edits',
        overlayRoot='runtime/web', files={name: dict(sha256=value,
            existingBaselineSha256=pins['baseline'].get(name),
            origin=origins.get(name, {}).get('source', 'New integration fixture/test or accepted fund test')) for name, value in files.items()},
        reviewedHunksFile='reviewed-hunks.json', reviewedHunksSha256=sha(REPORT / 'reviewed-hunks.json'),
        reviewedPatchFile='navigation.patch', reviewedPatchSha256=sha(REPORT / 'navigation.patch'),
        existingTargets={name: dict(beforeSha256=hunk['before_sha256'], afterSha256=hunk['after_sha256']) for name, hunk in hunks.items()},
        intentionalFeatureSourceChange=dict(path='src/lib/services-contract.ts',
            beforeSha256=origins['src/lib/services-contract.ts']['sha256'], afterSha256=files['src/lib/services-contract.ts'],
            reason='Match frozen stage11-r6 alnum-first 16..64 receipt identifier; UUID retry remains stable'),
        validationFile='validation2/validation.json', validationSha256=sha(REPORT / 'validation2/validation.json'),
        wireProofFile='services-wire-r6-proof.json', wireProofSha256=sha(REPORT / 'services-wire-r6-proof.json'),
        stage11ManifestSha256=wire['stage11_manifest_sha256'], cityV1Changed=False,
        sharedWebModified=False, hostedChanges=False, graphicalAcceptance=False)
    write('delivery-manifest.json', delivery)
    contract = dict(version=1, utc=utc, activeLinkedAccountRequired=True,
        pages=['/{ru|en}/services', '/{ru|en}/ratings'],
        services=dict(statusPortal='GET /api/services/status?slot=1..5',
            actionPortal='POST /api/services/action', privateStatus='POST /v2/services/status',
            privateAction='POST /v2/services/action', dtoVersion=2,
            requestId='[A-Za-z0-9][A-Za-z0-9_-]{15,63}; same ID on retry; browser identity derived from linked session',
            safeReceipt=['requestId', 'action', 'creditsDelta', 'goldDelta'],
            replay='Original receipt delta plus replayed=true and freshly fetched full status; UI does not apply deltas',
            avatarCatalog='Disabled until a documented catalog is configured', r5R6StatusReceiptRequestDtosIdentical=preserved_dto),
        ratings=dict(portal='GET /api/ratings/status?format=pairs|wall&scope=current|all|YYYY-MM&page=1..1000',
            private='POST /v1/ratings/status', readOnly=True, rowsPerPage=10),
        reviewedEdits=dict(navigation=['Account ru/en links to services and ratings', 'Exact top-level portal allowlist; city and assault retained'],
            fund=['Shared heading and empty caption', 'Personal Credits payer caption', 'Maximum donation=min(personal credits, unsigned32 escrow headroom)']),
        mergeInstructions=['Check each overlay target against existingBaselineSha256; null means new file',
            'Copy only files listed in delivery-manifest.json from runtime/web',
            'Apply reviewed-hunks.json only if each full before SHA and unique before fragment match',
            'Check after SHAs; preserve current CityV1 and all unrelated existing sources',
            'Root integrates corresponding frozen services/ratings/defense-fund server routes and publishes'],
        build=dict(distDir='.next-interfaces-20261008', webpack=True,
            isolated=True, standaloneManifestVerified=True, binaryDelivery='Build tree removed after proof; root rebuilds for publication'))
    write('integration-contract.json', contract)
    report = dict(version=1, utc=utc, readyForRootIntegration=True,
        deliveryManifestSha256=sha(REPORT / 'delivery-manifest.json'), overlayFiles=len(files),
        sourceFiles=sum(name.startswith('src/') for name in files), reviewedExistingTargets=len(hunks),
        testCounts=proof['testCounts'], testCoverage='All 17 selected non-PostgreSQL portal unit modules',
        requestedSubsetCounts=dict(servicesAndCity=14, ratingsCityAndAssault=22, overlappingCityTests=6),
        typeScriptPassed=True, fullNextBuildPassed=True, buildSeconds=proof['checks'][2]['seconds'],
        compiledRoutes=list(name for name in proof['compiledRoutes'] if name != 'standalone'),
        servicesR6Wire=dict(statusFixtures=wire['statusFixtures'], actionFixtures=wire['actionFixtures'],
            nonceLengths=wire['receiptBoundaries'], realEphemeralCoreHTTPAndFlaskProxy=True, syntheticAccounts=wire['syntheticAccounts']),
        sourcePins=dict(sharedWebUnchanged=True, scopedSourceUnchanged=True, frozenRuntimeUnchanged=True),
        excludedTestModules=proof['excludedTestModules'], originalEvidenceRetained=['validation1', 'revisions/stage11-r5', 'services-wire.log'],
        noLivePlayerData=True, noSecretsUsed=True, noStripeChanges=True, noVpsChanges=True, noGraphicalAcceptance=True)
    write('completion.json', report)
    print(json.dumps(dict(ready=True, manifestSha256=report['deliveryManifestSha256'], overlayFiles=len(files),
        webTestsPassed=proof['testCounts']['pass'], fullNextBuild=True)))


if __name__ == '__main__':
    main()
