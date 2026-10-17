"""Observe native shop/warehouse transitions without changing client data."""
import argparse
import json
import time

import frida


SCRIPT = r"""
const b = Process.getModuleByName('silver.dll').base;
const at = va => b.add(va - 0x400000);
function state() {
  const shop = at(0xac5b98).readPointer().readPointer();
  return {request_gate: at(0xac5940).readPointer().readU8(),
    waiting: at(0xac4c58).readU8(),
    shop_loading: shop.isNull() ? null : shop.add(0x2b8).readU8()};
}
send({event: 'initial', ...state()});
for (const [va, name] of [[0x991940, 'shop_request'], [0x991b34, 'shop_reply'],
    [0x9921a8, 'warehouse_request'], [0x992646, 'warehouse_reply'],
    [0x990638, 'inventory_reply'], [0x990050, 'inventory_wait'],
    [0x975450, 'city_menu'],
    [0x9dc760, 'waiting_changed']]) {
  Interceptor.attach(at(va), {
    onEnter() {send({event: name + '_enter', eax: this.context.eax.toUInt32(),
      caller: this.returnAddress.sub(b).add(0x400000).toString(), ...state()});},
    onLeave() {send({event: name + '_return', ...state()});}
  });
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pid', type=int)
    parser.add_argument('--seconds', type=int, default=60)
    args = parser.parse_args()
    session = frida.attach(args.pid)
    try:
        script = session.create_script(SCRIPT)
        script.on('message', lambda message, data: print(json.dumps(message), flush=True))
        script.load()
        time.sleep(args.seconds)
    finally:
        session.detach()


if __name__ == '__main__':
    main()
