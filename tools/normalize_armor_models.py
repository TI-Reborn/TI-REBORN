"""Bridge legacy CFG armor names to installed client meshes.

Modern chest meshes replace the legacy torso/arms, but omit separate hands. XML loader
a70ceb/a70dbf accepts w_model_N/w_texture_N for female render bindings.
"""
import re
from pathlib import Path

MODELS=Path(r'C:/Program Files (x86)/TIOnline/base/models')


def normalize(fields,models=MODELS):
    if fields.get('itype')!='armor' or int(fields['item_id'])>=65000:return
    if fields.get('freaks_only')=='1':return
    identity=int(fields['item_id']);old=fields.get('model_1','')
    if fields.get('dogs_only')=='1':
        # These three original dog meshes still ship unchanged.
        for key,value in fields.items():
            if re.fullmatch(r'model_\d+',key):assert (models/(value+'.mdjx')).is_file(),value
        return
    part=fields['bodypart']
    suffix=old.replace('armor_','',1)
    suffix=re.sub(r'_(torso|arms|hand|hands|feet)$','_chest' if part=='chest' else '_legs',suffix)
    suffix=suffix.replace('battle_heavy_se_','battlese_').replace('combat_heavy_m1_','combat_heavy_')
    texture='armor_'+('combatse' if 'combat_heavy_m1' in old else 'battlese' if 'battle_heavy_se' in old else suffix.split('_')[0])+'.jpg'
    special={206:('pantsukudasai','chr_man_body.jpg'),208:('combat_light_head','armor_combat.jpg'),
             222:('military_light_chest','armor_military.jpg'),254:('tank','armor_tank.jpg'),
             256:('tankse','armor_tankse.jpg'),257:('santahat','armor_santahat.jpg'),
             263:('fea','armor_fea.jpg'),264:('fease','armor_fease.jpg'),
             334:('suicidjack','armor_suicidjack.jpg')}
    suffix,texture=special.get(identity,(suffix,texture))
    # Legacy Leather Longies mistakenly says chest although its model is legs.
    if identity==226:fields['bodypart']='legs';suffix='battle_heavy_legs'
    for key in list(fields):
        if re.fullmatch(r'(w_)?(model|texture|mask|camo_texture|texture_damaged)_\d+',key):del fields[key]
    sexes=('woman',) if identity in (263,264) else ('man','woman')
    for sex in sexes:
        prefix='w_' if sex=='woman' else ''
        mesh=f'{sex}_armor_{suffix}'
        assert (models/(mesh+'.mdjx')).is_file(),mesh
        assert (models/texture).is_file(),texture
        fields[prefix+'model_1']=mesh
        fields[prefix+'texture_1']=texture
        mask=texture.replace('.jpg','_mask.png')
        if (models/mask).is_file():fields[prefix+'mask_1']=mask
    if identity in (263,264):
        fields['model_1']=fields['w_model_1'];fields['texture_1']=texture
        fields['female']='1'
    if identity==208:fields['showface']='1'
    if fields.get('bodypart')=='chest' or identity in (263,264):
        fields['model_2']='chr_woman_hands' if identity in (263,264) else 'chr_man_hands'
        fields['texture_2']='chr_woman_body.jpg' if identity in (263,264) else 'chr_man_body.jpg'
        fields['w_model_2']='chr_woman_hands';fields['w_texture_2']='chr_woman_body.jpg'
    if identity==206:
        fields['model_2']='chr_man_legs';fields['texture_2']='chr_man_body.jpg'
        fields['w_model_2']='chr_woman_legs';fields['w_texture_2']='chr_woman_body.jpg'
