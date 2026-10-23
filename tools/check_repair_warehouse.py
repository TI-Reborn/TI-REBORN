"""Check repair-kit protocol/persistence on an isolated hosted source snapshot."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'work/repair-warehouse-20261017'
REPORT=ROOT/'reports/repair-warehouse-20261017'
MODULES=('test_repair_warehouse_regression','test_warehouse','test_warehouse_transfer',
         'test_warehouse_queries.WarehouseQueryTests.test_private_warehouse_still_uses_owned_items',
         'test_warehouse_queries.WarehouseQueryTests.test_bad_queries_and_unrelated_commands','test_warehouse_errors',
         'test_warehouse_completion.WarehouseCompletionTests.test_initialization_preserves_legacy_packets_ids_and_overflow_in_every_city',
         'test_warehouse_completion.WarehouseCompletionTests.test_city_and_account_isolation_reserves_hidden_ids_and_whole_metadata',
         'test_warehouse_completion.WarehouseCompletionTests.test_capacity32_and_paid_service8_16_legacy_does_not_consume_city_slots',
         'test_warehouse_completion.WarehouseCompletionTests.test_merge_compaction_never_combines_remote_city_or_legacy_stacks',
         'test_warehouse_completion.WarehouseCompletionTests.test_outer_transaction_rejection_rolls_back_inventory_placements_and_services',
         'test_warehouse_completion.WarehouseCompletionTests.test_database_write_failure_rolls_back_no_partial_placement_or_charge',
         'test_warehouse_completion.WarehouseCompletionTests.test_native_warehouse_projection_includes_legacy_and_current_not_remote',
         'test_warehouse_completion.WarehouseCompletionTests.test_delivery_rejects_inventory_alias_before_any_item_is_written',
         'test_shop_completion.ShopCompletionTests.test_used_repairkit_and_ammo_unit_prices',
         'test_shop_completion.ShopCompletionTests.test_weapon_free_box_pack_and_id_sequence_survive_restart_replay')


def main():
    candidate=WORK/'candidate'
    shutil.copytree(ROOT/'tests',candidate/'tests',ignore=shutil.ignore_patterns('__pycache__'),dirs_exist_ok=True)
    shutil.copy2(ROOT/'tools/audit_unanswered_requests.py',candidate/'tools/audit_unanswered_requests.py')
    result=subprocess.run([sys.executable,'-X','utf8','-m','unittest',*MODULES],cwd=candidate,
        env=dict(os.environ,PYTHONPATH=str(candidate)+os.pathsep+str(candidate/'tests')),
        capture_output=True,text=True,encoding='utf-8',timeout=180)
    (REPORT/'server-contract-tests.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    count=re.search(r'Ran (\d+) tests in ([\d.]+)s',result.stderr)
    report=dict(passed=result.returncode==0,tests=int(count[1]) if count else None,
                seconds=float(count[2]) if count else None,modules=MODULES,
                actual_hosted_sources=True,hosted_database_used=False,hosted_changes=False,
                graphical_clients=False)
    (REPORT/'server-contract-tests.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
    if result.returncode:print(result.stderr[-14000:].encode('ascii','backslashreplace').decode())
    return result.returncode


if __name__=='__main__':sys.exit(main())
