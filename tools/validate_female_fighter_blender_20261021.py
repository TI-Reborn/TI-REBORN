"""Open female .blend and validate real skinning, UV, textures and poses."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'tools/validate_fighter_model_blender_20261021.py').read_text()
source=source.replace("'assets/fighter-model-v1'","'assets/female-fighter-v1'")
source=source.replace('veteran.blend','scout.blend').replace('Veteran_','Scout_')
source=source.replace("('head','torso','legs','hands')","('head','torso','legs','hands','hair')")
source=source.replace('==52','==51').replace('rig_bones=52,parts=4','rig_bones=51,parts=5')
source=source.replace("'Preview_Idle','Preview_Walk'","'Scout_Preview_Idle','Scout_Preview_Walk'")
exec(compile(source,__file__,'exec'))
