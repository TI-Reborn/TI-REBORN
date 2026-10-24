"""Two excluded QA accounts for the Groza primary/secondary icon transition."""
import argparse,json
from pathlib import Path
from tools import verify_groza_hosted_20261019 as qa

qa.OUT=qa.ROOT/'reports/groza-icon-20261019';qa.OUT.mkdir(exist_ok=True)
qa.PRIVATE=qa.ROOT/'.secrets/groza-icon-20261019.json'
old='item(91001,339,1,1,16),item(91002,340,4,0,0),item(91003,36,20,0,0)'
new='item(91001,301,1,1,16),item(91002,340,4,0,0),item(91003,36,20,0,0),item(91004,339,1,1,128),item(91005,13,20,0,0)'
assert old in qa.PREPARE
qa.PREPARE=qa.PREPARE.replace(old,new)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','hold','state','cleanup'));args=p.parse_args()
 if args.mode=='state':print(json.dumps(qa.state(qa.load())))
 else:getattr(qa,args.mode)()
