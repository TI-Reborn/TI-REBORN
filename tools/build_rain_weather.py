"""Build finite rain audio and the scoped native client patch from originals."""
import argparse,json,sys,hashlib,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def build(original, dependencies=None):
    if dependencies:sys.path.insert(0,str(dependencies))
    import numpy as np
    import soundfile as sf
    from deploy.client_rain_weather import patch
    folder=ROOT/'reports/rain-weather'
    destination=folder/'client';destination.mkdir(parents=True,exist_ok=True)
    (destination/'silver.dll').write_bytes(patch((folder/'silver-source.dll').read_bytes()))
    source=original/'base/sound/Ambient';sound=destination/'base/sound';sound.mkdir(parents=True,exist_ok=True)
    rain,rate=sf.read(source/'amb_rain_loop.ogg',always_2d=True)
    surface,surface_rate=sf.read(source/'amb_rain_surface_loop.ogg',always_2d=True)
    assert rate==surface_rate and rain.shape[1]==surface.shape[1]
    count=int(rate*1.05);mixed=rain[:count]*.65+surface[:count]*.35
    fade=int(rate*.025)
    mixed[:fade]*=np.linspace(0,1,fade)[:,None]
    mixed[-fade:]*=np.linspace(1,0,fade)[:,None]
    sf.write(sound/'tio_weather_rain.ogg',mixed,rate,format='OGG',subtype='VORBIS')
    shutil.copyfile(source/'amb_rain_thunder.ogg',sound/'tio_weather_thunder.ogg')
    for name in ('tio_weather_rain','tio_weather_thunder'):
        (sound/(name+'.xml')).write_text(f'<Sound><InternalName value="{name}"/><FileName value="{name}.ogg"/><AutoLoad value="0"/><AutoUnloadDeadline value="300"/><Channels value="2"/><Effect value="0"/></Sound>')
    # XML Effect=0 prevents abandoned infinite native sound loops on scene exit.
    manifest=json.loads((folder/'previous-manifest.json').read_text(encoding='utf-8'))
    resources={}
    for name in ('base/gfx/rain.tga',*[f'base/sound/Ambient/{n}.ogg' for n in ('amb_rain_loop','amb_rain_surface_loop','amb_rain_thunder')]):
        digest=hashlib.sha256((original/name).read_bytes()).hexdigest()
        assert next(r for r in manifest['files'] if r['path']==name)['sha256']==digest
        resources[name]=digest
    sounds={p.name:dict(seconds=sf.info(p).duration,sample_rate=sf.info(p).samplerate,finite=True) for p in sound.glob('*.ogg')}
    (folder/'resource-proof.json').write_text(json.dumps(dict(original_dependencies=resources,sounds=sounds,snow_added=False),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--original',type=Path,required=True);p.add_argument('--dependencies',type=Path)
    a=p.parse_args();build(a.original,a.dependencies)
