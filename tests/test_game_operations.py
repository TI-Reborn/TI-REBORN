from dataclasses import FrozenInstanceError
from types import SimpleNamespace
import unittest

from server.game_operations import (OperationCommand, OperationRegistry,
    OperationRejected, OperationResult, OperationSpec)


class GameOperationTests(unittest.TestCase):
    def registry(self, events):
        def validate(arguments):
            events.append('validate')
            if type(arguments['count']) is not int or arguments['count'] < 1:
                raise OperationRejected('invalid count')
        def perform(command, context):
            events.append('execute')
            return OperationResult(command, {'count': command.arguments['count']}, False, ('alice',))
        return OperationRegistry((OperationSpec('sample', frozenset(('count',)), validate, perform),))

    def test_prepare_snapshots_nested_input_and_rejects_mutation(self):
        raw={'entries':[{'count':1}]}
        command=OperationCommand('sample','operation-1',raw)
        raw['entries'][0]['count']=999
        self.assertEqual(command.arguments['entries'][0]['count'],1)
        with self.assertRaises(TypeError):command.arguments['entries'][0]['count']=2
        with self.assertRaises(FrozenInstanceError):command.name='other'

    def test_execution_always_rechecks_before_performing(self):
        events=[];registry=self.registry(events)
        context=SimpleNamespace(check=lambda:events.append('context'))
        command=registry.prepare('sample','operation-1',{'count':1})
        events.clear();registry.check(command,context)
        self.assertEqual(events,['validate','context'])
        events.clear();result=registry.execute(command,context)
        self.assertEqual(events,['validate','context','execute'])
        self.assertEqual(result.changed_owners,('alice',))

    def test_denied_context_never_performs(self):
        events=[];registry=self.registry(events)
        command=registry.prepare('sample','operation-1',{'count':1})
        def denied():raise OperationRejected('busy')
        with self.assertRaises(OperationRejected):registry.execute(command,SimpleNamespace(check=denied))
        self.assertNotIn('execute',events)

    def test_hand_constructed_command_does_not_bypass_validation(self):
        events=[];registry=self.registry(events)
        for args in ({'count':True},{'count':0},{'count':1,'owner':'bob'}):
            with self.assertRaises(OperationRejected):
                registry.execute(OperationCommand('sample','operation-1',args),SimpleNamespace(check=lambda:None))
        self.assertNotIn('execute',events)

    def test_unknown_operations_and_bad_identities_are_rejected(self):
        registry=self.registry([])
        for name,identity in [('other','good'),('sample',''),('sample','bad id'),('Sample','good')]:
            with self.assertRaises(OperationRejected):registry.prepare(name,identity,{'count':1})
        for value in (float('nan'),float('inf'),object()):
            with self.assertRaises(OperationRejected):OperationCommand('sample','good',{'value':value})

    def test_results_are_immutable_and_serialization_returns_fresh_data(self):
        command=OperationCommand('sample','good',{})
        raw={'receipt':{'creditsDelta':-3}}
        result=OperationResult(command,raw,False,('alice',))
        raw['receipt']['creditsDelta']=-9
        first=result.as_dict();first['receipt']['creditsDelta']=-8
        self.assertEqual(result.as_dict()['receipt']['creditsDelta'],-3)
        with self.assertRaises(TypeError):result.data['receipt']['creditsDelta']=-10

    def test_replayed_result_cannot_claim_mutation(self):
        command=OperationCommand('sample','good',{})
        with self.assertRaises(RuntimeError):OperationResult(command,{},True,('alice',))
        with self.assertRaises(RuntimeError):OperationResult(command,{'bad':object()},False,())

    def test_duplicate_registration_rejected_and_registry_is_immutable(self):
        registry=self.registry([]);spec=registry.specs['sample']
        with self.assertRaises(ValueError):OperationRegistry((spec,spec))
        with self.assertRaises(TypeError):registry.specs['new']=spec

    def test_unrelated_result_is_a_programming_failure(self):
        command=OperationCommand('sample','good',{})
        other=OperationCommand('sample','other',{})
        registry=OperationRegistry((OperationSpec('sample',frozenset(),lambda _:None,
            lambda cmd,ctx:OperationResult(other,{},False,())),))
        with self.assertRaises(RuntimeError):registry.execute(command,SimpleNamespace(check=lambda:None))


if __name__=='__main__':unittest.main()
