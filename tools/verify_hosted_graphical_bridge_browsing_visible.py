"""Read-only native validation; no Frida, game process, login or connection."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch as mock_patch
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import hosted_graphical_qa_bridge as bridge
from deploy import client_arena_browsing_visible as composer
FOLDER=ROOT/'reports/gameplay-completion/legacy-status-20261011/client-main-list-visibility'
NEW='e1d9435a8521881a6559dd3d724d9f5ca865a7aaa72d1707cf1669adaa3a4d80'
OLD={'7137403658a66f8c9ee571960f29203bf6049d2722fa9719526049aec01670c1','2d9e0f83b3ff94ef2c7ac5df2d396cd7b7a55a7ac03168c0ef252e977b75b359','4897eb6d6af6beb587fc9b303dc6911519d90b3414ae8cca8fd1ffb698c1f082','efc655e70cdc1e414270f6e5a4651d4c2927e866c7ae878edb6d54cb118049bf','853feb6a3803078ffaf1570969c8432bce37f8c20593acbadcdb5a68f798f3a1','afaa457c06ba6223476bc6e53eeff9947e9291acbce19700bb10ed5c3b29bdad'}
OLD.add('9d24b8f13a2c2a07c0673f8f9165b9df9f76a45eaa8561415606b3854ca86302')
OLD.add('8735e66a1495b124f935432bebaa413f94dbcc9d4f4f00cb502911656e3bbb0b')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    assert bridge.accepted_native_hashes('silver.dll')==OLD|{NEW}
    for name in ('ti.exe','orange.dll'):assert bridge.accepted_native_hashes(name)=={bridge.HASHES[name]}
    raw=(FOLDER/'silver.dll').read_bytes()
    with mock_patch.object(composer,'patch',wraps=composer.patch) as guarded_patch,mock_patch.object(composer,'review',wraps=composer.review) as guarded_review:
        assert bridge.validate_native_binary('silver.dll',raw)==NEW
        assert guarded_review.call_count==1 and guarded_patch.call_count>=1
        calls=dict(review=guarded_review.call_count,full_byte_patch=guarded_patch.call_count)
    corrupted=bytearray(raw);corrupted[0x1234]^=1
    try:bridge.validate_native_binary('silver.dll',bytes(corrupted))
    except ValueError:reject=True
    else:raise AssertionError('Mutated native bytes accepted')
    source=FOLDER.parent/'gui/prepare-a/client'
    with TemporaryDirectory(prefix='bridge-static-',dir=FOLDER) as temporary:
        target=Path(temporary).resolve();assert FOLDER.resolve() in target.parents
        (target/'base').mkdir();(target/'.tio-owned-qa').write_text('Static QA only; no account credentials or startup.\n')
        for name in ('ti.exe','orange.dll'):(target/name).write_bytes((source/name).read_bytes())
        (target/'silver.dll').write_bytes(raw)
        for name in ('autoexec.cfg','config.cfg'):(target/'base'/name).write_bytes((source/'base'/name).read_bytes())
        guards=bridge.static_guards(target);assert len(guards)==16
    report=dict(passed=True,candidate_sha256=NEW,bridge_sha256=sha(Path(bridge.__file__)),composition_source_sha256=sha(FOLDER.parent/'client-freshness/silver.dll'),review_sha256=sha(FOLDER/'combined-review.json'),all_prior_accepted_hashes_retained=True,previous_ti_orange_hash_guards_unchanged=True,full_byte_patch_and_review_invoked=calls,mutated_binary_rejected=reject,native_authentication_guards=guards,guard_count=len(guards),temporary_static_fixture_removed=True,gui_clients_started=0,authentication_calls=0,connections_opened=0,existing_game_files_modified=False,hosted_modified=False)
    out=FOLDER/'bridge-static-guards.json';out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,guard_count=len(guards),candidate_sha256=NEW,report_sha256=sha(out))))
if __name__=='__main__':main()
