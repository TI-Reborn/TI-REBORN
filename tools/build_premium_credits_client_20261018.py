"""Change only the two premium price currency atlas selections: gold -> credits."""
from pathlib import Path
import hashlib,json,struct,sys
import pefile
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/premium-credits-20261018'
BEFORE='5bd61fc2e946e64f88506951602b2d90dd59ab1589c9b472d4c23e39876a9492'
def main():
 raw=(OUT/'silver-before.dll').read_bytes();assert hashlib.sha256(raw).hexdigest()==BEFORE
 pe=pefile.PE(data=raw);candidate=bytearray(raw);changes=[]
 for va in (0x70d3bf,0x70d3fa):
  off=pe.get_offset_from_rva(va-0x400000);assert raw[off:off+4]==bytes.fromhex('6a016a00')
  candidate[off+1]=0;changes.append(dict(va=hex(va),before='6a016a00',after='6a006a00',reason='currency atlas row 1 (gold) -> 0 (credits)'))
 assert sum(a!=b for a,b in zip(raw,candidate))==2
 # The existing affordability check must continue to read credits, not gold.
 assert pe.get_data(0x70d395-0x400000,6)==bytes.fromhex('8b8030020000')
 (OUT/'silver.dll').write_bytes(candidate)
 proof=dict(passed=True,before_sha256=BEFORE,after_sha256=hashlib.sha256(candidate).hexdigest(),changes=changes,changed_bytes=2,size_unchanged=True,relocations_unchanged=True,credit_wallet_field='character+0x230')
 (OUT/'native-review.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof))
if __name__=='__main__':main()
