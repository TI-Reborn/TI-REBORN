> Live подтверждение: --probe-owned-pet создал настоящий слот0/id1/resource1;
> pointer ресурса ненулевой, поля+5ffc=1,+6006/+6008=100. Reader66 вернулся.
> Получен C2S2F010001000000; после S2C30 пустого инвентаря повторов за8s нет.
> См.evidence/owned_pet_live_summary.json. Полная видимость/играбельность бойца
> этим не доказана. Настройки trial локальные, без сохранения; default запуск
> пока не включает этот probe. 80unit PASS,2original inventory cases PASS.

> Обновление: добавлен tio/protocol/pet_info.py. Eight profile native verification:
> tools/verify_pet_info_native.py; evidence/pet_info_codec_native.json.
> Поддержаны обе ветки equipment, optional appearance, owner block и CString.
> Кодек требует явного профиля ресурсов и полного набора полей по callsite.
> Timed states и trailing-string branch пока отклоняются. Live actor и найм
> ещё не реализованы. 78 unit tests PASS; 8 original-reader profiles PASS.

# Собственные наёмники: PetInfo66

CONFIRMED по TI silver.dll:
- C2S63/u32 — builder8c3c34; C2S64/u32 — builder8c3c64.
  Назначение операций окончательно привязать к UI callbacks.
- S2C65/u32 — PetDelete: dispatcher8c7edc →8c40d4; поискID черезa93f70,
  уничтожение объекта и очистка слота. Это не generic success найма.
- S2C66 — PetInfo: dispatcher8c7edc →8c4380.
  Первоеu32 — ID: поиск по pet+28 в31 слотах, создание при отсутствии.
  Второеu32 передаётся a853cc, затем CString имени и4u8 состояния.
- Вложенный6d01f8: flag + при flag!=0 шестьbytes внешности.
- a93f9c определяет ветку снаряжения: результат0 →13u16,
  иначе3u16. Это зависимость от клиентских ресурсов, не отдельный wire flag.
- Далее16float32, триu32, прочие поля состояния и условные блоки.
- Flag, записанный вpet+43, включает дополнительные5полей в8c4de6..
  8c4e90; значения копируются в глобальное состояние. Их игровые имена UNKNOWN.
- Некоторые состояния включают парыu32 и время. Последнийu32(+60e0)
  включает дополнительную строку605df4; не считать её CString без проверки.

## Воспроизводимый результат
python tools/trace_pet_info_native.py
Оригинальный reader исполнил базовую ветку:71поле,206байт тела.
Трасса: evidence/pet_info_native_read_trace.json с offset,size,callsite.
Полный disassembly: evidence/pet_info_reader.asm.

Ограничения: существующий slot0 сID1; branchhuman принудительно выбран
явным stub для lookup ресурсов; пустое имя; нулевые optional состояния;
UI, runtime и model calls заглушены. Все числовые чтения и optional appearance
выполнены оригинальными инструкциями. Это структурный probe, НЕ валидный
игровой боец и НЕ доказательство найма/сохранения/отображения.

## Следующий шаг
Расширить trace на создание отсутствующегоID, внешность, дополнительные
состояния и ветки3/13 equipment. Из этого вывести проверенный codec66,
сопоставить model/resource и значения локального бойца; после этого live
и SQLite. Не подключать206нулевыхbytes как готового персонажа.
