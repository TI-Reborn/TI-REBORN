import ast
import json
from pathlib import Path
import unittest

from tools import deploy_clan_warfare as deploy


class ClanWarfareDeploymentTests(unittest.TestCase):
    def test_narrow_complete_whitelist_and_compile_generated_remote_program_without_execution(self):
        self.assertTrue({'server/battle_failures.py','tools/survival_scene.py','evidence/zones_diagnostic.xml'}<=deploy.ALLOWED)
        self.assertNotIn('reservation.sqlite3',deploy.ALLOWED)
        self.assertNotIn('server/accounts.py',deploy.ALLOWED)
        code=deploy.remote_program();compile(code,'reviewed remote program','exec')
        self.assertIn("sha(root/name)!=entry['before']",code)
        self.assertIn("hashlib.sha256(raw).hexdigest()!=entry['after']",code)
        self.assertIn('idle_rows()',code)

    def test_only_towns_xml_without_dtd_entities_or_unbounded_input(self):
        deploy.validate_candidate('evidence/zones_diagnostic.xml',b'<?xml version="1.0"?><towns><town id="6"/></towns>')
        for raw in (b'<wrong/>',b'<towns>',b'<!DOCTYPE towns SYSTEM "file:///etc/passwd"><towns/>',
                    b'<!DOCTYPE towns [<!ENTITY x "expansion">]><towns>&x;</towns>',b' '* (2*1024*1024+1)):
            with self.assertRaises(Exception):deploy.validate_candidate('evidence/zones_diagnostic.xml',raw)
        with self.assertRaises(json.JSONDecodeError):deploy.validate_candidate('config/unexpected.xml',b'<towns/>')

    def test_local_and_remote_zone_validation_are_identical_and_before_service_stop(self):
        code=deploy.remote_program();tree=ast.parse(code)
        validator=next(node for node in ast.walk(tree) if isinstance(node,ast.If) and
            isinstance(node.test,ast.Compare) and ast.unparse(node.test)=="name == 'evidence/zones_diagnostic.xml'")
        body=ast.Module(body=validator.body,type_ignores=[]);ast.fix_missing_locations(body)
        for raw,accepted in ((b'<towns/>',True),(b'<wrong/>',False),(b'<!DOCTYPE towns><towns/>',False),
                             (b'<!ENTITY x "x"><towns/>',False),(b'<towns',False)):
            for action in (lambda:deploy.validate_candidate('evidence/zones_diagnostic.xml',raw),
                           lambda:exec(compile(body,'remote XML validator','exec'),{'raw':raw})):
                if accepted:action()
                else:
                    with self.assertRaises(Exception):action()
        self.assertLess(code.index("elif name=='evidence/zones_diagnostic.xml':"),
                        code.index("run('systemctl','stop','tio-server')"))


if __name__=='__main__':unittest.main()
