"""The actual deployment command must accept config-only and mixed patches."""
import ast
from pathlib import Path
import unittest


class DeploymentImportTests(unittest.TestCase):
    def command(self, files):
        source = Path(__file__).resolve().parents[1] / 'tools/deploy_game_operations_remote.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        call, = (node for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                 and node.func.id == 'run' and len(node.args) >= 3
                 and isinstance(node.args[1], ast.Constant) and node.args[1].value == '-c')
        return eval(compile(ast.Expression(call.args[2]), str(source), 'eval'),
                    {'files': files})

    def test_config_only_generates_valid_python(self):
        exec(compile(self.command({'config/mining.json'}), '<deploy-imports>', 'exec'), {})

    def test_mixed_patch_still_imports_each_changed_module(self):
        namespace = {}
        exec(self.command({'config/mining.json', 'json.py', 'pathlib.py'}), namespace)
        self.assertEqual(namespace['json'].__name__, 'json')
        self.assertEqual(namespace['pathlib'].__name__, 'pathlib')
        with self.assertRaises(ModuleNotFoundError):
            exec(self.command({'no_such_deployment_adapter_20261117.py'}), {})


if __name__ == '__main__':
    unittest.main()
