'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="editor-token"]').content;
const kinds = {all:'Все', weapon:'Оружие', armor:'Броня', ammo:'Патроны', medical:'Лечение', other:'Прочее'};
const symbols = {weapon:'↗', armor:'◇', ammo:'▥', medical:'＋', other:'□'};
const weaponTypes = {Automatic:'Автоматическое', Heavy:'Тяжёлое', Light:'Лёгкое', Distance:'Снайперское', Melee:'Ближний бой', Throwing:'Метательное'};
let state, draft = {}, selected = 304, filter = 'all', previewData, previewTimer, previewSequence = 0, toastTimer, saving = false, previewInvalid = false;
const clone = value => JSON.parse(JSON.stringify(value));
const ordered = value => value && typeof value==='object' && !Array.isArray(value) ? Object.fromEntries(Object.keys(value).sort().map(k=>[k,ordered(value[k])])) : value;
const equal = (a,b) => JSON.stringify(ordered(a)) === JSON.stringify(ordered(b));
const dirty = () => state && !equal(draft, state.profile?.changes || {});
const changesCount = () => Object.values(draft).reduce((total,row) => total + Object.keys(row).length,0);
const activeItem = () => state.items.find(item => item.id === selected);
const valueFor = (item,key) => Object.hasOwn(draft[String(item.id)] || {},key) ? draft[String(item.id)][key] : item.base[key];
const displayValue = v => v === null ? 'Без боеприпаса' : v === '' ? '—' : typeof v === 'number' ? v.toLocaleString('ru-RU') : String(v);
function node(tag, className, text) {const el=document.createElement(tag); if(className)el.className=className;if(text!==undefined)el.textContent=text;return el;}
function toast(message,error=false){clearTimeout(toastTimer);$('toast').textContent=message;$('toast').className='toast'+(error?' error':'');$('toast').hidden=false;toastTimer=setTimeout(()=>$('toast').hidden=true,6000);}
async function api(path,body){
  const headers={'X-Editor-Token':token};if(body!==undefined)headers['Content-Type']='application/json';
  const response=await fetch(path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body)});
  if(!response.ok){let message='Не удалось выполнить запрос';try{message=(await response.json()).error || message;}catch{}throw new Error(message);}
  return response;
}
async function jsonApi(path,body){return (await api(path,body)).json();}
async function ask(title,description,initial=null,action='Продолжить'){
  const dialog=$('text-dialog');$('dialog-title').textContent=title;$('dialog-description').textContent=description;
  $('dialog-input').value=initial || '';$('dialog-label').hidden=initial===null;$('dialog-input').disabled=initial===null;
  $('dialog-ok').textContent=action;dialog.returnValue='cancel';dialog.showModal();
  if(initial!==null){$('dialog-input').focus();$('dialog-input').select();}
  return new Promise(resolve=>dialog.addEventListener('close',()=>resolve(dialog.returnValue==='ok'?(initial===null?true:$('dialog-input').value):null),{once:true}));
}
async function allowDiscard(){return !dirty() || await ask('Есть несохранённые изменения','При смене профиля несохранённые правки будут потеряны.',null,'Сменить профиль');}
function applyState(next){
  state=next;draft=clone(state.profile?.changes || {});previewInvalid=false;
  if(!state.items.some(i=>i.id===selected))selected=state.items[0]?.id;
  if(state.profile)localStorage.setItem('tio-balance-profile',state.profile.id);else localStorage.removeItem('tio-balance-profile');
  const picker=$('profiles');picker.replaceChildren(new Option('Исходный баланс',''));
  for(const p of state.profiles)picker.add(new Option(p.name,p.id));picker.value=state.profile?.id || '';
  $('revision').textContent=state.profile?'r'+state.profile.revision:'';
  $('total-count').textContent=state.items.length;
  $('banner').hidden=!state.stale_sources.length;
  $('banner').textContent='Исходные каталоги изменились после создания профиля. Сохранение и экспорт кандидата остановлены. Создайте новый профиль на актуальной основе.';
  renderFilters();renderList();renderForm();updateStatus();queuePreview();
}
function renderFilters(){
  $('filters').replaceChildren();
  for(const [key,label] of Object.entries(kinds)){
    const button=node('button','filter'+(filter===key?' active':''),label);button.type='button';button.setAttribute('aria-pressed',String(filter===key));
    button.addEventListener('click',()=>{filter=key;renderFilters();renderList();});$('filters').append(button);
  }
}
function renderList(){
  if(!state)return;
  const list=$('item-list'), scroll=list.scrollTop, query=$('search').value.trim().toLocaleLowerCase('ru');list.replaceChildren();
  const items=state.items.filter(i=>(filter==='all'||i.kind===filter)&&(!query||String(i.id).includes(query)||i.name.toLocaleLowerCase('ru').includes(query))&&(!$('changed-only').checked||draft[String(i.id)]));
  for(const item of items){
    const button=node('button','item-row'+(item.id===selected?' active':''));button.type='button';button.setAttribute('aria-pressed',String(item.id===selected));
    button.setAttribute('aria-label',item.name+', ID '+item.id);
    button.append(node('span','item-symbol',symbols[item.kind]));
    const label=node('span');label.append(node('span','row-title',item.name),node('span','row-subtitle',weaponTypes[item.weapon_type] || kinds[item.kind]));button.append(label);
    const meta=node('span','row-meta',String(item.id));if(draft[String(item.id)])meta.append(node('i','change-dot'));button.append(meta);
    button.addEventListener('click',()=>{selected=item.id;renderList();renderForm();queuePreview();});const wrapper=node('div');wrapper.setAttribute('role','listitem');wrapper.append(button);list.append(wrapper);
  }
  if(!items.length)list.append(node('div','empty','Предметы не найдены. Измените поиск или фильтр.'));
  list.scrollTop=scroll;$('visible-count').textContent=items.length+' из '+state.items.length;
}
const groups = [
  ['Атака',['damage_base','damage_random','attack_ap','critical']],
  ['Дальность и точность',['min_range','max_range','accuracy','accuracy_gain_amount','damage_fade']],
  ['Боеприпасы',['ammo_id','bullets_count']],
  ['Защита',['defense']],
  ['Вес и экономика',['weight','credits']]
];
function renderForm(){
  const item=activeItem();if(!item)return;
  $('item-name').textContent=item.name;$('item-category').textContent=(kinds[item.kind]||'Предмет').toUpperCase();
  $('item-id').textContent='ID '+item.id;$('item-subtype').textContent=weaponTypes[item.weapon_type] || kinds[item.kind];
  $('item-changed').hidden=!draft[String(item.id)];$('reset-item').disabled=!state.profile||!draft[String(item.id)];
  $('readonly-hint').hidden=Boolean(state.profile)&&Boolean(Object.keys(item.fields).length);
  $('readonly-hint').textContent=!state.profile?'Создайте профиль, чтобы изменить параметры и сравнить результат.':'Для этого служебного предмета доступен только просмотр.';
  const container=$('field-groups');container.replaceChildren();
  for(const [title,keys] of groups){
    const present=keys.filter(k=>Object.hasOwn(item.base,k));if(!present.length)continue;
    const section=node('section','field-group');section.append(node('h3','',title));const grid=node('div','field-grid');
    for(const key of present){
      const changed=Object.hasOwn(draft[String(item.id)]||{},key);
      const label=node('label','field-label'+(changed?' changed':''));label.dataset.field=key;
      const caption=node('span','field-caption',state.labels[key]);
      if(!item.fields[key])caption.append(node('span','lock','только просмотр'));
      label.append(caption);let input;
      if(key==='ammo_id'){
        input=node('select');input.add(new Option('Без боеприпаса','none'));
        for(const ammo of state.ammunition)input.add(new Option(ammo.name+' · '+ammo.id,String(ammo.id)));
        input.value=valueFor(item,key)===null?'none':String(valueFor(item,key));
      }else{
        input=node('input');input.type='number';input.step='1';input.required=true;input.value=valueFor(item,key);
        if(item.fields[key]){input.min=item.fields[key].min;input.max=item.fields[key].max;}
      }
      input.id='field-'+key;input.name=key;input.disabled=saving||!state.profile||!item.fields[key]||state.stale_sources.length>0;
      input.setAttribute('aria-label',state.labels[key]);input.addEventListener('input',()=>editValue(item,key,input));label.append(input);
      let hint=changed?'Было: '+displayValue(item.base[key]):key==='credits'?'За '+item.pack_count+' шт. в упаковке':key==='damage_random'?'Максимум = базовый + добавочный':key==='damage_fade'?'100% — без снижения урона':' ';
      label.append(node('span','was',hint));grid.append(label);
    }
    section.append(grid);container.append(section);
  }
  $('item-notes').replaceChildren(...item.notes.map(text=>node('p','',text)));
}
function editValue(item,key,input){
  const value=key==='ammo_id'?(input.value==='none'?null:Number(input.value)):(input.value===''?'':Number(input.value));
  const patch={...(draft[String(item.id)]||{})};if(value===item.base[key])delete patch[key];else patch[key]=value;
  if(Object.keys(patch).length)draft[String(item.id)]=patch;else delete draft[String(item.id)];
  const label=input.closest('label');label.classList.toggle('changed',Object.hasOwn(patch,key));
  label.querySelector('.was').textContent=Object.hasOwn(patch,key)?'Было: '+displayValue(item.base[key]):key==='credits'?'За '+item.pack_count+' шт. в упаковке':' ';
  $('item-changed').hidden=!draft[String(item.id)];$('reset-item').disabled=!draft[String(item.id)];
  previewInvalid=false;renderList();updateStatus();queuePreview();
}
function updateStatus(){
  if(!state)return;
  const count=changesCount(),hasProfile=Boolean(state.profile),unsaved=dirty(),stale=state.stale_sources.length>0;
  $('change-count').textContent=count+' '+(count===1?'изменение':count>1&&count<5?'изменения':'изменений');$('diff-count').textContent=count;
  const itemCount=Object.keys(draft).length;const itemWord=itemCount%10===1&&itemCount%100!==11?'предмет':itemCount%10>=2&&itemCount%10<=4&&!(itemCount%100>=12&&itemCount%100<=14)?'предмета':'предметов';
  $('change-summary').textContent=hasProfile?itemCount+' '+itemWord+' · '+(unsaved?'есть несохранённые правки':'профиль сохранён'):'Создайте профиль для первого эксперимента';
  $('save-status').textContent=saving?'Сохранение…':stale?'Основа изменилась':unsaved?'● Не сохранено':hasProfile?'Сохранено на компьютере':'Исходный баланс';
  $('save-status').classList.toggle('dirty',unsaved);
  $('save').disabled=!hasProfile||!unsaved||saving||stale||previewInvalid;
  $('profiles').disabled=saving;$('new-profile').disabled=saving;$('import-profile').disabled=saving;
  $('reset-item').disabled=saving||!hasProfile||!draft[String(selected)];
  for(const input of document.querySelectorAll('#item-form input, #item-form select'))input.disabled=saving||!hasProfile||!activeItem().fields[input.name]||stale;
  $('export-profile').disabled=!hasProfile||unsaved||saving;
  $('export-candidate').disabled=!hasProfile||unsaved||saving||stale||!count;
  $('export-profile').title=unsaved?'Сначала сохраните изменения':'Снимок и изменения для повторного открытия';
  $('export-candidate').title=unsaved?'Сначала сохраните изменения':!count?'Сначала измените параметры':'Архив для проверки перед применением';
}
function queuePreview(){clearTimeout(previewTimer);const seq=++previewSequence;previewTimer=setTimeout(()=>requestPreview(seq),200);}
async function requestPreview(seq){
  try{
    if(!$('item-form').checkValidity())throw new Error('Проверьте значения: нужны целые числа в допустимом диапазоне.');
    if(!$('target-defense').checkValidity()||!$('ap-budget').checkValidity())throw new Error('Проверьте броню цели и запас ОД.');
    const result=await jsonApi('/api/preview',{profile_id:state.profile?.id||null,changes:draft,item_id:selected,defense:Number($('target-defense').value),budget:Number($('ap-budget').value)});
    if(seq!==previewSequence)return;
    previewData=result;previewInvalid=false;$('preview-error').hidden=true;
    $('distance').max=result.series.length || 1;if(Number($('distance').value)>result.series.length)$('distance').value=1;
    renderPreview();updateStatus();
  }catch(error){
    if(seq!==previewSequence)return;
    previewInvalid=true;$('preview-error').textContent=error.message;$('preview-error').hidden=false;
    $('chart').replaceChildren(node('div','empty','Исправьте значения для предпросмотра.'));$('metrics').replaceChildren();updateStatus();
  }
}
const SVG='http://www.w3.org/2000/svg';
function svgNode(tag,attrs={},text){const el=document.createElementNS(SVG,tag);for(const [k,v]of Object.entries(attrs))el.setAttribute(k,String(v));if(text!==undefined)el.textContent=text;return el;}
function renderPreview(){
  if(!previewData)return;const data=previewData,chart=$('chart');chart.replaceChildren();
  const weapon=data.kind==='weapon';$('distance-control').hidden=!weapon;document.querySelector('.simulation-inputs').hidden=!weapon;document.querySelector('.legend').hidden=!weapon;
  document.querySelector('.preview-heading h2').textContent=weapon?'Как меняется урон':data.kind==='armor'?'Как работает защита':'Параметры предмета';
  if(!weapon){
    $('metrics').replaceChildren();
    if(data.kind==='armor'){
      chart.append(node('div','empty','Остаточный урон после попадания по этой броне'));
      for(const row of data.armor)addMetric('При уроне '+row.raw,row.base,row.profile);
      $('preview-note').textContent='Расчёт защиты без улучшений и других частей экипировки. Положительное попадание наносит минимум 1 урона.';
    }else{chart.append(node('div','empty',data.note||'Для этого типа предмета нет боевого графика. Вес и цена сохраняются в профиле.'));$('preview-note').textContent='Итоговые изменения доступны в сравнении перед экспортом.';}
    return;
  }
  const series=data.series,distance=Number($('distance').value),point=series[distance-1];
  const width=320,height=200,left=34,right=9,top=16,bottom=30;
  const maximum=Math.max(10,...series.flatMap(p=>[p.base,p.profile].filter(v=>v.in_range).map(v=>v.high)))*1.12;
  const x=n=>left+(n-1)/Math.max(1,series.length-1)*(width-left-right),y=n=>height-bottom-n/maximum*(height-top-bottom);
  const svg=svgNode('svg',{viewBox:`0 0 ${width} ${height}`,role:'img','aria-label':'Диапазон урона по дистанции; серый — исходный, янтарный — профиль'});
  for(let i=0;i<=4;i++){const value=maximum*i/4;svg.append(svgNode('line',{x1:left,x2:width-right,y1:y(value),y2:y(value),stroke:'#2a323d','stroke-width':1}),svgNode('text',{x:left-7,y:y(value)+3,fill:'#768496','font-size':9,'text-anchor':'end'},String(Math.round(value))));}
  for(const tick of [...new Set([1,Math.round(series.length/2),series.length])])svg.append(svgNode('text',{x:x(tick),y:height-10,fill:'#768496','font-size':9,'text-anchor':'middle'},String(tick)));
  for(const [key,color] of [['base','#96a6b9'],['profile','#e5a34d']]){
    const points=series.filter(p=>p[key].in_range);if(!points.length)continue;
    const upper=points.map(p=>`${x(p.distance)},${y(p[key].high)}`).join(' '),lower=[...points].reverse().map(p=>`${x(p.distance)},${y(p[key].low)}`).join(' ');
    svg.append(svgNode('polygon',{points:upper+' '+lower,fill:color,'fill-opacity':key==='base'?.07:.14}));
    for(const limit of ['low','high'])svg.append(svgNode('polyline',{points:points.map(p=>`${x(p.distance)},${y(p[key][limit])}`).join(' '),fill:'none',stroke:color,'stroke-width':key==='base'?1.3:2,'stroke-dasharray':key==='base'?'4 3':'none','stroke-linejoin':'round'}));
    if(points.length===1)svg.append(svgNode('circle',{cx:x(points[0].distance),cy:y(points[0][key].high),r:3,fill:color}));
  }
  svg.append(svgNode('line',{x1:x(distance),x2:x(distance),y1:top,y2:height-bottom,stroke:'#5c6877','stroke-dasharray':'3 4'}));chart.append(svg);
  $('distance-value').textContent=distance+' кл.';$('metrics').replaceChildren();
  const format=(v,k)=>!v.in_range?'Вне дальности':k==='damage'?`${v.low}–${v.high}`:k==='accuracy'?v.accuracy+'%':v[k];
  addMetric('Урон после брони',format(point.base,'damage'),format(point.profile,'damage'));
  addMetric('Точность',format(point.base,'accuracy'),format(point.profile,'accuracy'));
  addMetric('Средний урон / ОД',format(point.base,'damage_per_ap'),format(point.profile,'damage_per_ap'));
  addMetric('Атак при '+data.budget+' ОД',point.base.attacks,point.profile.attacks);
  $('preview-note').textContent=data.note;
}
function addMetric(label,before,after){const row=node('div','metric');row.append(node('span','',label),node('span','before',String(before)),node('span','arrow','→'),node('span','after',String(after)));$('metrics').append(row);}
async function saveProfile(){
  if($('save').disabled)return;saving=true;updateStatus();
  try{const next=await jsonApi('/api/profiles/'+state.profile.id,{revision:state.profile.revision,name:state.profile.name,changes:draft});applyState(next);toast('Профиль сохранён. Исходные каталоги не изменены.');}
  catch(error){toast(error.message,true);}finally{saving=false;updateStatus();}
}
async function download(action){
  try{const response=await api('/api/profiles/'+state.profile.id+'/'+action);const blob=await response.blob();const url=URL.createObjectURL(blob);const a=node('a');a.href=url;a.download=action==='candidate'?'tio-balance-candidate.zip':'tio-balance-profile.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);toast(action==='candidate'?'Кандидат экспортирован для проверки.':'Профиль экспортирован.');}catch(error){toast(error.message,true);}
}
function renderDiff(){
  $('diff-body').replaceChildren();
  for(const [id,patch]of Object.entries(draft)){
    const item=state.items.find(i=>i.id===Number(id));
    for(const [field,value]of Object.entries(patch)){
      const row=node('tr');row.append(node('td','',item.name+' · '+id),node('td','',state.labels[field]),node('td','',displayValue(item.base[field])),node('td','',displayValue(value)));$('diff-body').append(row);
    }
  }
  $('diff-empty').hidden=changesCount()>0;$('reset-all').disabled=saving||!state.profile||!changesCount();
}
$('search').addEventListener('input',renderList);$('changed-only').addEventListener('change',renderList);
$('save').addEventListener('click',saveProfile);$('item-form').addEventListener('submit',e=>e.preventDefault());
$('target-defense').addEventListener('input',queuePreview);$('ap-budget').addEventListener('input',queuePreview);$('distance').addEventListener('input',renderPreview);
$('profiles').addEventListener('change',async()=>{const id=$('profiles').value;$('profiles').value=state.profile?.id||'';if(!await allowDiscard())return;try{applyState(await jsonApi(id?'/api/profiles/'+id:'/api/state'));}catch(error){toast(error.message,true);}});
$('new-profile').addEventListener('click',async()=>{
  if(!await allowDiscard())return;
  const name=await ask('Новый профиль','Исходные значения останутся в каталоге. Ваши изменения будут храниться отдельно.','Эксперимент 01','Создать профиль');if(name===null)return;
  try{applyState(await jsonApi('/api/profiles',{name}));toast('Профиль создан. Можно редактировать предметы.');}catch(error){toast(error.message,true);}
});
$('reset-item').addEventListener('click',()=>{delete draft[String(selected)];previewInvalid=false;renderForm();renderList();updateStatus();queuePreview();});
$('export-profile').addEventListener('click',()=>download('profile'));$('export-candidate').addEventListener('click',()=>download('candidate'));
$('review').addEventListener('click',()=>{renderDiff();$('review-dialog').showModal();});$('close-review').addEventListener('click',()=>$('review-dialog').close());$('done-review').addEventListener('click',()=>$('review-dialog').close());
$('reset-all').addEventListener('click',async()=>{if(await ask('Сбросить все изменения?','Параметры вернутся к исходному снимку. Чтобы сохранить сброс в профиле, нажмите «Сохранить профиль».',null,'Сбросить')){draft={};previewInvalid=false;renderForm();renderList();renderDiff();updateStatus();queuePreview();}});
$('help-button').addEventListener('click',()=>$('help-dialog').showModal());$('close-help').addEventListener('click',()=>$('help-dialog').close());
$('import-profile').addEventListener('click',async()=>{if(await allowDiscard())$('import-file').click();});
$('import-file').addEventListener('change',async()=>{
  const file=$('import-file').files[0];$('import-file').value='';if(!file)return;
  try{if(file.size>1900000)throw new Error('Профиль слишком большой. Максимум 1,9 МБ.');const profile=JSON.parse(await file.text());const name=await ask('Импорт профиля','Профиль будет сохранён отдельной копией. Совпадение исходных каталогов проверяется автоматически.',String(profile.name||'Импорт').slice(0,65)+' (импорт)','Импортировать');if(name===null)return;applyState(await jsonApi('/api/import',{name,profile}));toast('Профиль импортирован отдельной копией.');}catch(error){toast(error.message,true);}
});
window.addEventListener('beforeunload',e=>{if(dirty()){e.preventDefault();e.returnValue='';}});
window.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();saveProfile();}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();$('search').focus();}});
(async()=>{try{const initial=await jsonApi('/api/state');const remembered=localStorage.getItem('tio-balance-profile');applyState(remembered&&initial.profiles.some(p=>p.id===remembered)?await jsonApi('/api/profiles/'+remembered):initial);}catch(error){$('item-name').textContent='Не удалось открыть каталоги';$('item-list').replaceChildren(node('div','empty error-text',error.message));toast(error.message,true);}})();
