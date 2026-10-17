"""Additional provenance for the imported read-only protected-runtime list."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
F=ROOT/'reports/gameplay-completion/legacy-status-20261011/server-lobby-original-names-deployment'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    review=json.loads((F/'preparation-review.json').read_text(encoding='utf8'))
    assert review['passed'] and review['applied'] is False
    for name,value in review['implementation_sources_sha256'].items():assert sha(ROOT/name)==value
    dependency='tools/deploy_legacy_lobby_projection.py';raw=(ROOT/dependency).read_bytes()
    target=F/'source'/dependency;assert not target.exists();target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    value=dict(passed=True,preparation_review_sha256=sha(F/'preparation-review.json'),
               deployment_manifest_sha256=sha(F/'deployment-manifest.json'),
               qualified_proof_sha256=review['qualified_proof_sha256'],
               additional_direct_dependency_sha256={dependency:sha(ROOT/dependency)},
               dependency_role='Read-only PROTECTED_RUNTIME constant only; never executes its deployment logic',
               additional_provenance_tool_sha256=sha(Path(__file__)),remote_mutations=0,applied=False)
    target=F/'preparation-dependencies.json';assert not target.exists()
    target.write_text(json.dumps(value,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,dependencies_sha256=sha(target),remote_mutations=0)))
if __name__=='__main__':main()
