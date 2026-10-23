"""Reopen delivered .blend files and check editable art survives serialization."""
from pathlib import Path
import bpy,json
ROOT=Path(__file__).resolve().parents[1];A=ROOT/'assets/wasteland-materials-v1';R=ROOT/'reports/remaining-textures-20261021'
paths=[A/'source/wasteland-material-library.blend',A/'source/terrain-library.blend',A/'source/target-and-masks-library.blend',A/'source/painted-UV-masters.blend',*sorted((A/'devices').glob('*.blend'))]
records=[]
for path in paths:
    bpy.ops.wm.open_mainfile(filepath=str(path))
    images=[i for i in bpy.data.images if i.source=='FILE']
    assert images and all(i.packed_file for i in images),path
    assert any(o.type=='MESH' for o in bpy.context.scene.objects),path
    if path.name=='wasteland-material-library.blend':assert sum(m.use_fake_user for m in bpy.data.materials)>=10
    if path.name=='painted-UV-masters.blend':assert sum(m.use_fake_user for m in bpy.data.materials)>=2
    if path.parent.name=='devices':assert sum(o.type in ('MESH','CURVE') for o in bpy.context.scene.objects)>=10
    records.append(dict(path=path.relative_to(ROOT).as_posix(),materials=len(bpy.data.materials),packed_images=len(images),scene_objects=len(bpy.context.scene.objects)))
result=dict(passed=True,blender=bpy.app.version_string,projects=len(records),editable_sources_reopened=True,all_file_images_packed=True,records=records)
(R/'blender-source-validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(dict(passed=True,projects=len(records))))
