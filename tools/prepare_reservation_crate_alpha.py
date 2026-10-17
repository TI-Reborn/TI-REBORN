"""Restore native BMP serialization without changing generated texture pixels."""
from reservation_texture_assets import *
from reservation_texture_export import encode
from build_visual_asset_catalog import decode
import tarfile
from PIL import Image

FIX=ROOT/'reports/reservation-crate-alpha'
NAMES=('steel_box_01b.png','ground_ny_detail_32.png')

def main():
    previous=(FIX/'previous-manifest.json').read_bytes();manifest=json.loads(previous)
    assert manifest['version']=='2026.10.06.3'
    inventory=json.loads((OUT/'inventory.json').read_text());names=json.loads((OUT/'names.json').read_text())
    records={r['path']:r for r in manifest['files']};proof=[]
    release=FIX/'client-release';(release/'blobs').mkdir(parents=True,exist_ok=True)
    for name in NAMES:
        original=fetch(inventory['textures'][name]).read_bytes();reference,_=decode(original)
        assert original[:2]==b'BM' and struct.unpack_from('<H',original,28)[0]==32
        target='base/setting/reservation_v2/'+names[name];record=records[target]
        published=urllib.request.urlopen('https://185.184.42.88/updates/blobs/'+record['sha256'],timeout=30).read()
        assert len(published)==record['size'] and sha(published)==record['sha256']
        before,_=decode(published);assert before.size==reference.size
        fixed=bytes(encode(original,before,reference));after,_=decode(fixed)
        assert fixed[:2]==b'BM' and struct.unpack_from('<H',fixed,28)[0]==32
        assert after.size==before.size and after.convert('RGB').tobytes()==before.convert('RGB').tobytes()
        assert after.getchannel('A').tobytes()==reference.getchannel('A').tobytes()
        pixels=list(before.convert('RGB').get_flattened_data())
        # Keep original padding colors as well as the native transparency plane.
        if name=='steel_box_01b.png':
            assert all(pixels[i]==(0,0,0) for i,p in enumerate(reference.convert('RGB').get_flattened_data()) if p==(0,0,0))
            assert pixels.count((0,0,0))>len(pixels)//2
        dest=FIX/'client'/target;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(fixed)
        (release/'blobs'/sha(fixed)).write_bytes(fixed)
        proof.append(dict(source=name,target=target,before_sha=record['sha256'],after_sha=sha(fixed),
                          format='32-bit BMP with original native alpha',size=list(after.size),rgb_pixels_unchanged=True,
                          native_alpha_exact=True,alpha_range=list(after.getchannel('A').getextrema()),black_padding_pixels=pixels.count((0,0,0))))
        record.update(size=len(fixed),sha256=sha(fixed))
    manifest['version']='2026.10.06.4'
    manifest['news']='Исправлен чёрный фон у ящиков Резервации: восстановлен оригинальный формат прозрачности. Закройте игру и обновите клиент через лаунчер.\n\n'+manifest['news']
    (release/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (release/'previous-manifest.json').write_bytes(previous)
    (FIX/'asset-verification.json').write_text(json.dumps(dict(passed=True,files=proof,changed_files=2,graphical_game_client=False),indent=2)+'\n')
    with tarfile.open(FIX/'patch.tar.gz','w:gz') as tar:
        for path in release.rglob('*'):
            if path.is_file():tar.add(path,arcname=path.relative_to(release).as_posix())
    print(json.dumps(dict(version=manifest['version'],files=proof)))

if __name__=='__main__':
    import sys
    sys.path.insert(0,str(ROOT));main()
