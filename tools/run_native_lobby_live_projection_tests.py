"""Prior111 checks plus live city projection over actual TCP; isolated runtime only."""
from pathlib import Path
import importlib,io,json,shutil,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
F=ROOT/'reports/gameplay-completion/legacy-status-20261011/runtime-native-lobby-live-projection';stage=F/'isolated-runtime'
assert not (F/'isolated-tests-final.log').exists()
shutil.copyfile(ROOT/'tools/test_native_lobby_live_projection.py',F/'qa-tests/test_native_lobby_live_projection.py')
sys.path[:0]=[str(F/'qa-tests'),str(stage/'tests'),str(stage)]
names=json.loads((F.parent/'runtime-native-lobby-original-names/candidate.json').read_text())['test_modules']
names.append('test_native_lobby_live_projection');modules=[importlib.import_module(name) for name in names]
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module) for module in modules)
stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
(F/'isolated-tests-final.log').write_text(stream.getvalue(),encoding='utf8')
for name,file in (('test_native_lobby_departure_tcp','tcp-cases.json'),('test_native_lobby_live_projection','live-tcp-cases.json')):
    module=importlib.import_module(name);(F/file).write_text(json.dumps(dict(passed=result.wasSuccessful(),cases=module.RESULTS),indent=2)+'\n',encoding='utf8')
print(json.dumps(dict(passed=result.wasSuccessful(),tests=result.testsRun,failures=len(result.failures),errors=len(result.errors))))
if not result.wasSuccessful():print(stream.getvalue());raise SystemExit(1)
