"""Execute exactly the prior111 suite against the isolated original-name variant."""
from pathlib import Path
import importlib,io,json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
F=ROOT/'reports/gameplay-completion/legacy-status-20261011/runtime-native-lobby-original-names'
stage=F/'isolated-runtime'
sys.path[:0]=[str(F/'qa-tests'),str(stage/'tests'),str(stage)]
candidate=json.loads((F/'candidate.json').read_text(encoding='utf8'))
assert 'server.team_arena' not in sys.modules
modules=[importlib.import_module(name) for name in candidate['test_modules']]
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module) for module in modules)
assert suite.countTestCases()==111
stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
(F/'isolated-tests-final.log').write_text(stream.getvalue(),encoding='utf8')
tcp=importlib.import_module('test_native_lobby_departure_tcp')
(F/'tcp-cases.json').write_text(json.dumps(dict(passed=result.wasSuccessful(),cases=tcp.RESULTS),indent=2)+'\n',encoding='utf8')
print(json.dumps(dict(passed=result.wasSuccessful(),tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),tcp_cases=len(tcp.RESULTS))))
if not result.wasSuccessful():
 print(stream.getvalue());raise SystemExit(1)
