"""Owned hosted two-account check for the Blender flame atlas."""
import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import flame_fire_gui_20261021 as qa
qa.OUT=ROOT/'reports/flame-blender-20261021'
qa.flame.qa.OUT=qa.OUT;qa.flame.qa.PRIVATE=ROOT/'.secrets/flame-blender-20261021.json'
qa.LAUNCHER=ROOT/'work/flame-blender-20261021/qa-launcher/TIO Launcher.exe'
qa.TRACE=qa.TRACE.replace('silver.add(0x87a080)','allocation.add(0x7020)')
qa.AUTO_ROUTE=True
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','launch','cleanup'));p.add_argument('--auto',action='store_true');a=p.parse_args()
 if a.mode=='launch':qa.launch(a.auto)
 elif a.mode=='provision':qa.flame.qa.provision()
 else:qa.flame.qa.cleanup()
