"""Tradeable encounter materials, awarded atomically with victory settlement."""
from dataclasses import replace
from .protocol.item_list import ItemRecord,decode_item_list,encode_item_list
from .world_encounters import POLICY
MATERIALS={int(k):v for k,v in POLICY.get('loot',{}).items()}

def material_sale(item,count):
    rule=MATERIALS.get(item.template_id)
    if rule is None:return None
    pristine=ItemRecord(item.instance_id,item.template_id,b'\0\0',item.count,0,0,(0,0,0),b'\0'*4,None,b'\0'*3)
    if item!=pristine:raise ValueError('Modified encounter material cannot be sold')
    return count*rule['sell_credits']

def award(db,account,match_id,result,report,*,escaped=False):
    if report.get('loot_version')!=1 or result!=1 or escaped:return ()
    # Reward validation runs before this function. An immutable settlement key
    # prevents a retry/reconnect from awarding the same carcasses twice.
    db.execute('''CREATE TABLE IF NOT EXISTS encounter_loot_awards (
       match_id TEXT NOT NULL,account TEXT NOT NULL,template_id INTEGER NOT NULL,
       amount INTEGER NOT NULL,destination TEXT NOT NULL,PRIMARY KEY(match_id,account,template_id))''')
    if db.execute('SELECT 1 FROM encounter_loot_awards WHERE match_id=? AND account=?',(match_id,account)).fetchone():
        raise ValueError('Loot receipt exists without battle reward')
    db.execute('CREATE TABLE IF NOT EXISTS item_sequences (account TEXT PRIMARY KEY,next_id INTEGER NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS warehouse_items (account TEXT NOT NULL,instance_id INTEGER NOT NULL,item_packet BLOB NOT NULL,PRIMARY KEY(account,instance_id))')
    rows=db.execute('SELECT pet_id,human,inventory_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(account,)).fetchall()
    if not rows:raise ValueError('Encounter recipient missing')
    ids=[i.instance_id for _,_,p in rows for i in decode_item_list(p)[1]]
    ids.extend(k for k, in db.execute('SELECT instance_id FROM warehouse_items WHERE account=?',(account,)))
    sequence=db.execute('SELECT next_id FROM item_sequences WHERE account=?',(account,)).fetchone()
    next_id=max(max(ids,default=0)+1,sequence[0] if sequence else 1)
    if next_id+len(MATERIALS)>0xffffffff:raise ValueError('Encounter loot ID space exhausted')
    materials=tuple(ItemRecord(next_id+index,identity,b'\0\0',report['dogs']*rule['per_dog'],0,0,(0,0,0),b'\0'*4,None,b'\0'*3)
                    for index,(identity,rule) in enumerate(MATERIALS.items()))
    from .item_stacking import merge_stacks
    from .inventory_capacity import validate_capacity
    recipient=next((r for r in rows if r[1]),rows[0]);owner,items,flag=decode_item_list(recipient[2])
    updated=merge_stacks((*items,*materials));destination=f'inventory:{owner}'
    try:validate_capacity(items,updated)
    except ValueError:
        # A full bag cannot destroy a victory's materials. The private warehouse
        # receives the two stacks even if its normal transfer limit is reached;
        # existing capacity checks still allow withdrawals/reduction.
        destination='warehouse'
        from .warehouse import WarehouseStore
        warehouse=WarehouseStore._read(db,account)
        merged=merge_stacks((*warehouse.values(),*materials))
        remaining={i.instance_id for i in merged}
        for identity in warehouse.keys()-remaining:
            db.execute('DELETE FROM warehouse_items WHERE account=? AND instance_id=?',(account,identity))
        for item in merged:
            db.execute('INSERT INTO warehouse_items VALUES (?,?,?) ON CONFLICT(account,instance_id) DO UPDATE SET item_packet=excluded.item_packet',
                       (account,item.instance_id,encode_item_list(0,(item,))))
    else:
        db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',(encode_item_list(owner,updated,flag),account,recipient[0]))
    db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=MAX(next_id,excluded.next_id)',(account,next_id+len(materials)))
    for item in materials:db.execute('INSERT INTO encounter_loot_awards VALUES (?,?,?,?,?)',(match_id,account,item.template_id,item.count,destination))
    return materials
