"""Check kit transfer/list codecs against the original native client writers.

Native UI array selection and serialization execute with synthetic memory;
network/UI endpoints are isolated. No hosting or installed files are changed.
"""
import json
from pathlib import Path
import sys
import hashlib
import pefile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT)]
from verify_warehouse_transfer_native import run as transfer
from verify_warehouse_native import run as snapshot
from verify_warehouse_ui_arrays_native import run as selection
from tio.protocol.warehouse import WarehouseItem,decode_warehouse_list
from tio.protocol.warehouse_transfer import decode_warehouse_transfer
from verify_auth_native import BINARY,EXPECTED_SHA


def main():
    published=(ROOT/'reports/repair-warehouse-20261017/client/baseline/silver.dll').read_bytes()
    original=BINARY.read_bytes();assert hashlib.sha256(original).hexdigest()==EXPECTED_SHA
    old=pefile.PE(data=original);current=pefile.PE(data=published)
    compared=[]
    try:
        for start,size in ((0x992294,0x200),(0x63f60c,0x100),(0x63ead4,0x180),
                           (0xa66645,0x60),(0xa667b2,0x60)):
            assert old.get_data(start-0x400000,size)==current.get_data(start-0x400000,size),hex(start)
            compared.append(dict(address=hex(start),bytes=size))
    finally:old.close();current.close()
    cases=[]
    for index,(template,durability) in enumerate(((17,600),(18,1200),(19,3600))):
        identity=1001+index
        for deposits,withdrawals in ((((identity,1),),()),((),((identity,1),))):
            case=transfer(deposits,withdrawals)
            decoded=decode_warehouse_transfer(bytes.fromhex(case['packet_hex']))
            assert decoded.first_items==deposits and decoded.second_items==withdrawals
            cases.append(dict(template=template,**case))
    items=(WarehouseItem(1001,17,1,328,600,600),WarehouseItem(1002,18,1,1200,1200,1200),WarehouseItem(1003,19,1,3600,3600,3600))
    case=snapshot(0,1,0,items)
    assert decode_warehouse_list(bytes.fromhex(case['packet_hex']))==(0,1,0,items)
    cases.append(case)
    cases.extend(selection(entry) for entry in (0xa66645,0xa667b2))
    report=dict(passed=True,cases=cases,published_native_functions_match_original=compared,
                graphical_clients=False,hosted_changes=False,limitations=__doc__)
    (ROOT/'reports/repair-warehouse-20261017/native-wire-verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(passed=True,cases=len(cases),native_transfer_directions=True,native_6a_fields=True,graphical_clients=False)))


if __name__=='__main__':main()
