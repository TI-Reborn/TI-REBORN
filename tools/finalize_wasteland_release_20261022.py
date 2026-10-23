"""Assemble the final local release, inventory and factual Russian handoff."""
from pathlib import Path
import collections,hashlib,json,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/remaining-textures-20261021';A=ROOT/'assets/wasteland-materials-v1';FINAL=OUT/'phase3-final'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda b:hashlib.sha256(b).hexdigest()
proof=read(FINAL/'texture-proof.json');public=read(FINAL/'https-verification.json');health=read(OUT/'final-hosted-health.json');sources=read(OUT/'blender-source-validation.json')
assert len(proof)==727 and public['passed'] and public['verified_resources']==727 and health['passed'] and sources['passed']
assert public['version']==health['version']=='2026.10.22.3'
stages=[read(OUT/d/'publication.json') for d in ('phase1-active','phase2-complete','phase3-final')]
assert all(r['passed'] and r['protected_unchanged'] and not r['server_restarted'] and not r['database_written'] and not r['local_player_data_uploaded'] for r in stages)
cleanup=read(OUT/'fixture-cleanup.json');assert cleanup['unrelated_rows_preserved'] and cleanup['integrity']=='ok'
assert not (ROOT/'.secrets/remaining-textures-20261021.json').exists()
before=read(OUT/'phase1-active/manifest-before.json');after=read(FINAL/'manifest.json');ar={r['path']:r for r in before['files']};br={r['path']:r for r in after['files']}
assert set(ar)==set(br) and len(ar)==6658
changed={n for n in ar if ar[n]!=br[n]};assert changed=={r['path'] for r in proof} and len(changed)==727
release=A/'release';release.mkdir(exist_ok=True)
for t in proof:
    raw=(A/'native'/t['path']).read_bytes();assert sha(raw)==t['sha256']==br[t['path']]['sha256'] and len(raw)==br[t['path']]['size']
    target=release/'client'/t['path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
shutil.copy2(FINAL/'manifest.json',release/'manifest.json');shutil.copy2(FINAL/'texture-proof.json',release/'changes.json')
excluded=read(OUT/'separate-artwork.json');assert len(excluded)==325
why={r['path']:r['reason'] for r in excluded};inventory=read(OUT/'inventory.json')
for t in inventory:
    t['final_status']='replaced_in_this_release' if t['path'] in changed else 'already_different_from_installer' if t['status']=='replaced' else 'preserved_specialized_art_or_functional_texture'
    if t['path'] in why:t['preservation_reason']=why[t['path']]
(OUT/'final-inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
logs=[]
for command in ([sys.executable,'-m','unittest','tests.test_reservation_texture_codec','-q'],[sys.executable,'tools/verify_equipment_texture_loader_native.py']):
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True);assert result.returncode==0
    logs.append(' '.join(command)+'\n'+result.stdout+result.stderr)
(OUT/'final-automated-checks.log').write_text('\n\n'.join(logs),encoding='utf-8')
summary=dict(passed=True,version=public['version'],texture_count=727,groups=dict(collections.Counter(t['path'].split('/')[1] for t in proof)),
    source_inventory_images=len(inventory),already_different_from_original=294,preserved_specialized_resources=325,
    exact_sprite_alpha=646,opaque_model_maps=73,new_blender_prop_icons=8,new_ground_textures=7,
    completely_repainted_uv_atlases=['armor_raider.jpg','mob_sickminer.jpg'],
    blender_projects_reopened=sources['projects'],native_manifest_geometry_and_code_files_changed=0,
    https_verified_resources=727,https_verified_bytes=public['verified_bytes'],manifest_sha256=public['manifest_sha256'],
    server_service=health['service'],server_database_integrity='ok',publication_restarted_service=False,
    protected_data_unchanged_during_each_publication=True,qa_accounts_remaining=0,qa_checkpoints_remaining=0,qa_cleanup_preserved_unrelated_rows=True,
    full_task_interval_player_fingerprints_unchanged=cleanup['preexisting_players_preserved'],
    graphical_coverage=dict(native_accounts_observed_sequentially=2,simultaneous_native_clients=1,inventory=True,hosted_forest_field=True,all_cities_and_each_asset=False),
    backups=health['backups_preserved'],limits=['Specialized UI/portrait/tutorial artwork and functional masks are listed separately and retained.','Most sprite silhouettes and baked structural shading are retained; surfaces are refinished.','Graphical inspection covers inventory and one hosted forest field; variant resources have codec/alpha/size verification.'])
(OUT/'final-acceptance.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
link=lambda label,p:f'[{label}]({p.resolve().as_posix()})'
report=f'''# Материальные текстуры клиента — 22 октября 2026

Опубликована версия **2026.10.22.3**, всего **727 текстур**. Обновление доступно через обычный лаунчер.

| Ресурсы | Количество |
| --- | ---: |
| Окружение, здания, растительность, грунт | 432 |
| Иконки предметов | 217 |
| Диффузные карты моделей | 73 |
| Материальные GFX-спрайты | 5 |

В Blender 4.5 созданы восемь новых устройств для инвентаря и семь новых поверхностей грунта. Для остальных спрайтов сохранены силуэты, положение деталей и основная геометрическая светотень, переработаны материалы поверхностей. Карты Raider и Sick Miner отдельно перерисованы и экспортированы через Blender. У 73 UV-карт увеличено разрешение с сохранением пропорций; у спрайтов сохранены размеры нативных кадров. У 646 спрайтов альфа-канал совпадает с исходным. Восемь новых иконок получили собственную сглаженную прозрачность в прежних размерах 64×32.

Ориентир для оформления — предыстория руководства, страницы 3–6: поселения экспедиции Теслы, заброшенная военная и исследовательская инфраструктура, умеренная растительность, наёмники и добыча Spectra Crystals. Использованы выцветшая краска, сухая древесина, старый бетон, матовый металл, ткань и ограниченные следы износа.

## Просмотр и исходники

- {link('Исходные рендеры устройств Blender',A/'preview/blender-devices.jpg')}.
- {link('Инвентарь после обновления через лаунчер',OUT/'gui-inventory-published.jpg')}.
- {link('Проверка нового окружения в настоящем клиенте',OUT/'gui-forest-candidate.jpg')}.
- {link('31 страница сравнений',A/'preview/index.html')}.
- {link('Проекты Blender и пересборка',A/'README.ru.md')}.
- {link('Запросы и происхождение карт imagegen',A/'source/generation-provenance.json')}.
- {link('Точный опубликованный набор',release/'changes.json')}.

Встроенный imagegen использован для атласа вспомогательных материалов и двух UV-карт. Процедурные материалы, устройства, рендер и экспорт подготовлены в Blender. Файлы генерации сохранены в проекте.

## Проверки

Все 727 опубликованных файлов повторно загружены по HTTPS и сверены с локальными SHA-256. Проверены форматы, размеры, альфа, неизменность списка файлов манифеста и сохранение всех прежних замен. Нативные модели, TILE/SET-геометрия, XML-каталоги и DLL не менялись. Три теста кодека и проверка настоящего x86-загрузчика текстур прошли.

В графическом клиенте проверены инвентарь и лесное поле боя. Две автоматизированные TLS-учётные записи получили одинаковое поле 38×38; графические входы двух аккаунтов выполнены последовательно. После первой публикации второй аккаунт получил ресурсы обычным лаунчером. В следующих публикациях эти 328 проверенных ресурсов сохранены побайтно. Полный графический обход всех вариантов и городов не выполнялся.

{sources['projects']} основных проектов Blender повторно открыты; изображения упакованы в .blend, редактируемые материалы сохранены. {link('Проверка исходников',OUT/'blender-source-validation.json')}.

## Хостинг и данные

Служба `tio-server` активна; публикации выполнены без её перезапуска. Перед каждой заменой манифеста сделаны резервные копии удалённой SQLite, прежних клиентских ресурсов, кода и конфигурации:

{chr(10).join('- `'+r+'`' for r in health['backups_preserved'])}

Во время каждой публикации fingerprints защищённых таблиц совпали до и после. Локальные сохранения и базы игроков не загружались. Два disposable QA-аккаунта из исключённого рейтингового пространства удалены; собственных незавершённых QA-боёв нет. Удаление проверило сохранность всех посторонних строк и схемы внутри своей транзакции; пользовательские кланы не удалялись. Общий fingerprint между созданием и удалением fixtures различается, поэтому он не заявляется доказательством неизменности игроков за весь длительный интервал работы. {link('Результат очистки',OUT/'fixture-cleanup.json')}.

Финальная проверка: SQLite `ok`, аккаунтов 26, кланов 4. Приватные загрузочные ZIP удалены, резервные копии сохранены. {link('Финальное состояние хостинга',OUT/'final-hosted-health.json')}.

## Границы набора

В исходном установщике проверены 1346 изображений: 294 уже отличались, 727 заменены этим набором, 325 сохранены отдельно. Среди сохранённых — интерфейсные атласы, учебные схемы и портреты, шрифты, маски управления камуфляжем, тактические маркеры, эффекты и теневые/служебные плоскости. Это отдельные типы ресурсов, требующие своей обработки. {link('Полный итоговый инвентарь',OUT/'final-inventory.json')}, {link('Список сохранённых ресурсов и причин',OUT/'separate-artwork.json')}.
'''
(OUT/'README.ru.md').write_text(report,encoding='utf-8')
asset=f'''# Wasteland materials v1

Опубликованный клиентский набор: **2026.10.22.3**, **727 материальных текстур**.

Основные редактируемые проекты:

- {link('Библиотека материалов',A/'source/wasteland-material-library.blend')} — узлы и упакованные изображения для поверхности металла, дерева, бетона, ткани и растительности.
- {link('Грунт',A/'source/terrain-library.blend')} — новая поверхность с параметрами оттенка биома.
- {link('Мишень и маски для лица',A/'source/target-and-masks-library.blend')}.
- {link('Перерисованные UV-карты',A/'source/painted-UV-masters.blend')}.
- `devices/*.blend` — восемь самостоятельных 3D-проектов устройств; `devices/*.png` — рендеры 1024×512, `*-registered.png` — подготовка к нативным иконкам.

`guides/` содержит зарегистрированные исходные развёртки. `masters/` — рендеры для экспорта. `release/client/` — точные опубликованные файлы; `release/manifest.json` и `release/changes.json` связывают их с SHA-256. `preview/index.html` открывает все сравнения.

Графы для игровых атласов используют исходную геометрическую светотень и цветовое распределение, новые материалы накладываются внутри существующего расположения деталей. Устройства моделированы заново. Прозрачность кадров и положение UV сохраняются при нативном экспорте; у восьми новых устройств используется новая альфа.

Для генерации вспомогательного атласа материалов и карт Raider/Sick Miner использован **встроенный imagegen**. {link('Полный набор запросов и пути исходных изображений',A/'source/generation-provenance.json')}.

## Пересборка из C:\\TIO-emulator

```powershell
& 'work/fighter-model-v1/blender-4.5.0-windows-x64/blender.exe' --background --factory-startup --python tools/wasteland_materials_blender_20261021.py -- --force
& 'work/fighter-model-v1/blender-4.5.0-windows-x64/blender.exe' --background --factory-startup --python tools/wasteland_repaint_bake_20261021.py
& 'work/fighter-model-v1/blender-4.5.0-windows-x64/blender.exe' --background --factory-startup --python tools/wasteland_devices_blender_20261021.py
python tools/remaining_textures_20261021.py export
python tools/finalize_wasteland_devices_20261021.py
python tools/remaining_textures_20261021.py sheets
```

Экспорт требует оригинальные файлы из `work/remaining-textures-20261021/original`: они нужны для нативных заголовков и прозрачности. Пересборка сама не публикует изменения. Повторная публикация использует отдельные guarded-скрипты и откажет при несовпадении фактического манифеста хостинга.

{link('Проверки, резервные копии и границы визуального покрытия',OUT/'README.ru.md')}.
'''
(A/'README.ru.md').write_text(asset,encoding='utf-8')
(release/'README.ru.md').write_text('Точная поставка 2026.10.22.3: 727 изображений. Обновляйте игру через обычный лаунчер.\n\n'+link('Подробности',OUT/'README.ru.md')+'\n',encoding='utf-8')
pages=sorted((A/'preview').glob('comparison-*.jpg'))
html='<!doctype html><html lang="ru"><meta charset="utf-8"><title>Материалы 2026.10.22.3</title><style>body{background:#19201e;color:#ddd;font:16px system-ui;max-width:1500px;margin:auto;padding:24px}img{max-width:100%;height:auto}section{margin:32px 0}a{color:#b5cbb2}</style><h1>727 материальных текстур</h1><p>Слева исходник, справа экспорт Blender. В UV-картах моделей увеличено разрешение, поэтому при просмотре листа их физический размер может различаться.</p>'
for i,p in enumerate(pages,1):html+=f'<section><h2>Лист {i}</h2><a href="{p.name}"><img loading="lazy" src="{p.name}" alt="Сравнение {i}"></a></section>'
(A/'preview/index.html').write_text(html+'</html>',encoding='utf-8')
print(json.dumps(dict(passed=True,version=summary['version'],textures=len(proof),blender_projects=sources['projects'],report=str(OUT/'README.ru.md'))))
