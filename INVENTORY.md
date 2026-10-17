## Correction: equipable defaults true (2026-09-12)

Original loader a7341f supplies CL=1 for XML key equipable at a756f4. Helper680860 preserves the default when dictionary lookup681f48 reports absence. Original a7343c stores the result at metadata+68d. verify_equipable_default_native.py executes this loader segment, the helper missing-key branch and destination write: value1 confirmed. String lifetime and dictionary lookup are isolated.

Therefore the absence of equipable in items.cfg/diagnostic XML does not establish a failure or require an added field. Previous notes identifying missing compatibility flags as the necessary next blocker were too broad. Actual type/slot rules and server mutation still remain to implement. Evidence equipable_default_native.json.

## Full policy target propagation (2026-09-12)

verify_item_policy_native.py executes a6516c through return with synthetic ordinary-item metadata and isolated predicate/UI/lifetime calls. Five cases prove propagation of no target (FF), masks1/10/80 (options0/4/7) and rejection of target40000 along this ordinary branch. Sender9903a4 is captured, not executed here; its independent verifier covers serialization.

This is not a real Beretta compatibility test: metadata lookup and predicates are stubs. Both policy and sender require metadata+68d nonzero. Local items.cfg sections301/326 contain weapon characteristics but do not directly establish this metadata flag. Recover loader/default initialization before claiming real equip readiness.

## Explicit target option mapping (2026-09-12)

Original a7a050 was executed for25 inputs. Options0..18 map to masks1,2,4,8,10,20,40,80,100,200,400,4000,8000,10000,20000,40000,80000,100000,200000 (hex masks). Zero and unsupported masks returnFF. In particular raw800/1000/2000 returnFF here, although inventory reception normalizes them to4: these are distinct conversions.

ItemAction.target_mask returns None forFF and rejects unrecognized explicit indices; item_target_option reproduces original conversion. Evidence item_target_native.json and verify_item_target_native.py;142 tests pass. This maps a supplied target control and does not establish item compatibility or automatic slot choice. Server equip mutation remains pending.

## Wear button and shared item action (2026-09-12)

Localization m492 (Надеть) is assigned at8d56b2. Event interface+0xc uses table8d5320, adapter8d52d1, wrapper8d5458 and callback8d4ab8. The ordinary callback passes pet ID, selected item record and null target to a6516c. Original callback replay verifies these arguments and the no-selection/no-owner early returns.

The common policy at a6516c contains equipment and consumable branches; its final call a65b53 reaches9903a4. Original writer replay confirms C2S33 = opcode:u8, pet_id:u32, instance_id:u32, option:u8. The no-target policy initializes option to FF at a65267. Explicit target uses a7a050; its mapping remains to recover. The intermediate policy has NOT been executed by this verifier. Do not interpret every33 as equip or option as inventory slot.

Evidence: evidence/equip_request_native.json; tools/verify_equip_request_native.py. Codec tio/protocol/item_action.py has no server mutation route.141 unit tests pass.

> Route correction: original997260 invokes920068 and skips99729a..997451 legacy6B. RTTI91e8d2 TGUI_SupplementWindow; not equip evidence. Native item_action_route_native.json verified return and selecteditem1001. Need actual equip binding.
> 6B writer992294 confirmed original3cases: modeu8,identityu32,two u16count lists of(instanceu32,countu32). Meaning of mode/groups UNKNOWN; codec only, no DB mutations.139tests. Next caller993da0/drag-drop mapping.
> RTTI confirmed equipped=unknown_u8_01; slot=location_raw; count=unknown_u32_01. getEquipped63c770/getSlot63c7d0. Native99082a..9908b4 maps0x800/1000/2000->4;8casesPASS. InitialBeretta equipped0/slot0. Actor projection now uses equipped items only, rejects duplicate/foreign/unsupported cases.138tests. Equip request/server mutation still pending.
> Обновление: обычные непустые записи ItemList30 реализованы. Original
> reader63bd38 прошёл3cases (optional-u32 absent/zero/max); live consumer
> создал instance1001/template301. См.owned_pet_nonempty_inventory_live.log.
> OwnedPetStore сохраняет бойца и inventory вместе, не заменяет сохранённое
> состояние новым seed. Пока включается через --probe-owned-pet.
> 82unit tests PASS. Строка имени и вложенный item record ещё не поддержаны.

## Формат обычной записи
u32 instanceID,u32 templateID,2u8,u32,u8,u32 location_raw,
3u16,4u8,flag_name (поддержан0),flag_u32,[u32],3u8,
flag_nested (поддержан0). Размер35bytes без optional-u32,39bytes с ним.
Семантика unknown полей ещё не восстановлена. Native flags наличия в
объекте не являются дополнительными wire bytes.

## Сохранение
Таблица owned_pets(account,pet_id,human,pet_packet,inventory_packet).
Проверяются совпадение ownerID, полевая схема и уникальность instanceID
внутри inventory. Один BEGIN IMMEDIATE для первоначального сохранения
обоих пакетов; существующая запись не перезаписывается seed.
Это переходное хранение подтверждённых wire-полей до domain-модели.
Покупка/продажа/изменение кошелька пока отсутствуют.

# Инвентарь бойца — начало восстановления

CONFIRMED: bare C2S2F writer99002f: u16count, затем u32ID бойца.
Наблюдался2f010001000000 сразу после PetInfo66.
Не путать с C8/2F writer64be7c — другой packet с другими полями.

S2C30: serializer63ce70, reader63ce00: u32ownerID,u8unknown,u32count,
затем item records через63bd38. Пока реализован только count0.
Consumer990638 ищет владельца черезa93f70 и обновляет inventory pet+6c;
выставляет pet+300/+301. Native empty decoder:9bytes тела, без stubs,
провереныowner1/12345 и unknown0/255.

Live эксперимент: при отсутствии30 клиент запросил2F пять раз за8s;
после корректного30 — один запрос, один ответ, повторов в оставшийся
интервал нет. Это подтверждает завершение запроса пустого инвентаря,
не подтверждает обработку покупок, продаж и непустого инвентаря.

Пустой ответ включён только в --probe-owned-pet для его локальногоID1.
Не возвращать пустой список для аккаунта с вещами и не выдавать trial
за persistent roster. Trial packet хранится в evidence/owned_pet_trial.json.

Следующий шаг: разобрать original item-record63bd38/63befc и связать
предметы с серверным состоянием. После этого вывести собственных бойцов
и их инвентарь из SQLite и подключить операции города.
