"""Controlled native shop-wait regression probe; no inventory/wallet mutation.

Requires an open shop. Sets only the transient waiting/loading UI flags to
reproduce a pending operation, then releases it through original 9dc760.
The installed retry hook must send 73 and real server74 must finish loading.
"""
import argparse
import json
import time
from pathlib import Path
import frida


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pid', type=int)
    args = parser.parse_args()
    session = frida.attach(args.pid)
    messages = []
    def receive(message, data):
        messages.append(message)
        print(json.dumps(message), flush=True)
    try:
        source = "const silver = Process.getModuleByName('silver.dll').base;\n"
        source += Path(__file__).with_name('shop_request_retry.js').read_text()
        source += r"""
const at = va => silver.add(va-0x400000);
const shop = at(0xac5b98).readPointer().readPointer();
if (shop.isNull() || at(0xac4c58).readU8() || shop.add(0x2b8).readU8())
  throw Error('Open a healthy shop before this controlled probe');
function callEax(va, value) {
  const code = Memory.alloc(Process.pageSize);
  code.writeByteArray([0x53,0xb8,...new Uint8Array(new Uint32Array([value]).buffer),
    0xbb,...new Uint8Array(new Uint32Array([at(va).toUInt32()]).buffer),
    0xff,0xd3,0x5b,0xc3]);
  Memory.protect(code,Process.pageSize,'r-x');
  new NativeFunction(code,'void',[])();
}
let replies = 0;
Interceptor.attach(at(0x991b34),{onLeave(){replies++;}});
callEax(0x9dc760,1);
callEax(0x991940,0); // Original builder drops this while waiting.
shop.add(0x2b8).writeU8(1); // Same loading state set by normal shop opening.
callEax(0x9dc760,0); // Simulate completion of the preceding operation.
setTimeout(()=>send({event:'shop_retry_result', replies,
  waiting:at(0xac4c58).readU8(), loading:shop.add(0x2b8).readU8()}),2000);
"""
        script = session.create_script(source)
        script.on('message', receive)
        script.load()
        time.sleep(3)
        payloads = [m['payload'] for m in messages if m['type'] == 'send']
        assert any(p.get('event') == 'shop_request_deferred' for p in payloads)
        assert sum(p.get('event') == 'shop_request_resumed' for p in payloads) == 1
        result = next(p for p in payloads if p.get('event') == 'shop_retry_result')
        assert result == dict(event='shop_retry_result', replies=1, waiting=0, loading=0), result
        (Path(__file__).resolve().parents[1]/'evidence/shop_retry_live.json').write_text(
            json.dumps(dict(status='PASS',method=__doc__,pid=args.pid,events=payloads),indent=2))
    finally:
        session.detach()


if __name__ == '__main__':
    main()
