"""Freeze a faulty shared match and finish its accounts without stopping peers."""
import logging
from .failure_policy import storage_failure
from tio import battle_settlement

LOG=logging.getLogger('tio.server')


class BattleSettlementError(RuntimeError):
    """An individual report failed; its match must stop accepting actions."""


class BattleFailures:
    def prepare_settlements(self,battle,requests):
        cache=battle.setdefault('settlement_inputs',{})
        staged={}
        for owner,result,escaped in requests:
            if owner in battle['settled']:continue
            if owner in cache:
                if cache[owner][0]!=result:raise ValueError('Conflicting frozen battle result')
                staged[owner]=cache[owner]
            else:staged[owner]=(result,self.settlement_inputs(battle,owner,escaped=escaped))
        if not staged:return
        paths={str(self.players[o].database) for o in staged}
        if len(paths)!=1:raise ValueError('Shared battle settlement requires one database')
        reports=[(self.players[o].account,r,k) for o,(r,k) in staged.items()]
        battle_settlement.enqueue(next(iter(paths)),battle['match_id'],reports)
        cache.update(staged)

    def fail_session(self,session,error):
        with self.lock:
            owner=self.identities.get(session)
            battle=self.battles.get(owner)
            if battle is not None:self.quarantine(battle,error)
            elif getattr(getattr(session,'arena',None),'_fields',None):self.fail_private(session,error)

    def fail_private(self,session,error):
        if storage_failure(error):raise error
        session.arena._faulted=True
        self.private[session.account]=(session,self.clock()+5)
        for match in session.arena._match_ids.values():
            try:battle_settlement.record_failure(session.database,match,(session.account,),error)
            except Exception as audit_error:
                if storage_failure(audit_error):raise
                LOG.error('private_failure_audit_deferred account=%s error_type=%s',session.account,type(audit_error).__name__)
        LOG.error('private_match_quarantined account=%s error_type=%s',session.account,type(error).__name__)

    def finish_private(self,session):
        matches=tuple(session.arena._match_ids.values())
        session.arena.disconnect(session.probe_character_id)
        for match in matches:battle_settlement.complete_failure(session.database,match)

    def quarantine(self,battle,error):
        if storage_failure(error):raise error
        if self.team_rating_report(battle) is None:
            self.cancel_team_rating(battle,'server_fault')
        if not battle.get('faulted'):
            battle['faulted']=type(error).__name__
            LOG.error('match_quarantined match=%s error_type=%s',battle['match_id'],type(error).__name__,
                      exc_info=(type(error),error,error.__traceback__))
        self.retry_quarantined(battle)

    def retry_quarantined(self,battle):
        if battle.get('kind') == 'contract':
            # A generic PvP recovery must not invent a terminal contract receipt.
            return
        if self.clock()<battle.get('fault_retry',0):return
        battle['fault_retry']=self.clock()+5
        owners=tuple(battle['humans'])
        requests=[]
        for owner in owners:
            cached=battle.get('settlement_inputs',{}).get(owner)
            requests.append((owner,cached[0] if cached else 0,True))
        try:
            if owners and not battle.get('failure_audited'):
                battle_settlement.record_failure(self.players[owners[0]].database,battle['match_id'],
                    (self.players[o].account for o in owners),battle['faulted'])
                battle['failure_audited']=True
            self.prepare_settlements(battle,requests)
        except Exception as error:
            if storage_failure(error):raise
            LOG.error('match_report_capture_failed match=%s error_type=%s',battle['match_id'],type(error).__name__)
            return
        for owner,result,_ in requests:
            try:self.settle(battle,owner,result,escaped=True)
            except Exception as error:
                if storage_failure(error):raise
                LOG.error('match_settlement_pending match=%s account=%s error_type=%s',
                          battle['match_id'],self.players[owner].account,type(error).__name__)
        if not set(owners)<=battle['settled']:return
        self.abort_assault(battle,'server_fault')
        if owners:battle_settlement.complete_failure(self.players[owners[0]].database,battle['match_id'])
        # Do not refresh a broken view or run another gameplay action. All
        # participants are settled first, then only this match is discarded.
        battle['finished']=True
        for owner in owners:
            self.battles.pop(owner,None)
            session=self.players[owner]
            battle['field'].remove_owner(owner)
            battle['humans'].discard(owner)
            self.forget(owner)
            session.stop()
        LOG.warning('match_quarantine_completed match=%s',battle['match_id'])
