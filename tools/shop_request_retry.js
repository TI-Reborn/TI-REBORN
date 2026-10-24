// This build's 991940 silently drops a shop request while global waiting=1.
// Queue only that dropped request; replay through the original writer on the
// client thread after 9dc760 clears waiting. No timeout or forced flag reset.
{
  let pendingShopCategory = null;
  const requestCode = Memory.alloc(Process.pageSize);
  requestCode.writeByteArray([0x53, 0x8b, 0x44, 0x24, 0x08, 0xbb,
    ...new Uint8Array(new Uint32Array([silver.add(0x991940-0x400000).toUInt32()]).buffer),
    0xff, 0xd3, 0x5b, 0xc3]);
  Memory.protect(requestCode, Process.pageSize, 'r-x');
  const requestShop = new NativeFunction(requestCode, 'void', ['uint']);
  Interceptor.attach(silver.add(0x991940-0x400000), {
    onEnter() {
      if (silver.add(0xac5940-0x400000).readPointer().readU8()) {
        pendingShopCategory = this.context.eax.toUInt32() & 255;
        send({event: 'shop_request_deferred', category: pendingShopCategory});
      } else pendingShopCategory = null;
    }
  });
  Interceptor.attach(silver.add(0x9dc760-0x400000), {
    onLeave() {
      if (pendingShopCategory === null || silver.add(0xac4c58-0x400000).readU8()) return;
      const category = pendingShopCategory;
      pendingShopCategory = null;
      const shop = silver.add(0xac5b98-0x400000).readPointer().readPointer();
      if (!shop.isNull() && shop.add(0x2b8).readU8()) {
        send({event: 'shop_request_resumed', category});
        requestShop(category);
      }
    }
  });
}
