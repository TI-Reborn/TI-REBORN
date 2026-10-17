"""Build a scoped candidate from the inspected hosted runtime, never old locals."""
import hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/direct-trade-20261014'
NEW=('tio/player_trade.py','tio/protocol/player_trade.py','server/player_trade.py')
CHANGED=('server/multi.py','tools/loopback_exchange.py','config/english_translations.json')
TRANSLATIONS={
 'Выбранный боец не принадлежит аккаунту':'The selected soldier does not belong to this account',
 'Недостаточно средств для обмена':'Insufficient funds for this trade',
 'Предмет недоступен для обмена':'This item is not available for trade',
 'Предмет изменился во время обмена':'An offered item changed during the trade',
 'Это не стопка предметов':'This item cannot be split',
 'Кошелёк получателя переполнен':'The recipient wallet is full',
 'Игрок недоступен для обмена':'The player is not available for trade',
 'Обмен доступен только свободным игрокам в городе':'Trade requires both players to be idle in a town',
 'Для обмена нужно находиться в одном городе':'Both players must be in the same town',
 'Нельзя обмениваться с самим собой':'You cannot trade with yourself',
 'Время ожидания обмена истекло':'The trade timed out',
 'Обмен отменён: участник отключился':'Trade canceled: a player disconnected',
 'Обмен отменён: условия сделки изменились':'Trade canceled: the terms changed',
 'Обмен отменён: началось другое действие':'Trade canceled: another action started',
 'Слишком частые приглашения на обмен':'Trade invitations are too frequent',
 'Один из игроков уже участвует в обмене':'One of the players is already trading',
 'Приглашение на обмен отправлено':'Trade invitation sent',
 'Приглашение на обмен недействительно':'The trade invitation is no longer valid',
 'Приглашение на обмен отклонено':'Trade invitation declined',
 'Приглашение должен принять второй игрок':'The other player must accept the invitation',
 'Выберите вещи и деньги; подтвердить обмен должны оба игрока':'Choose items and money; both players must confirm the trade',
 'Нет активного обмена':'There is no active trade',
 'После подтверждения состав обмена менять нельзя':'The offer cannot change after confirmation',
 'Недопустимое количество для обмена':'Invalid trade quantity',
 'Обмен отменён':'Trade canceled',
 'Один участник подтвердил обмен; ожидается подтверждение второго':'One player confirmed the trade; waiting for the other player',
 'Обмен успешно завершён':'Trade completed successfully',
 'Два разных владельца обязательны':'Two different owners are required',
}

def replace_once(source,before,after):
    if source.count(before)!=1:raise ValueError('Hosted integration anchor changed: '+before[:100])
    return source.replace(before,after)

def build():
    baseline=FOLDER/'runtime';candidate=FOLDER/'candidate'
    if candidate.exists():raise FileExistsError(candidate)
    shutil.copytree(baseline,candidate)
    for name in NEW:
        if (baseline/name).exists():raise ValueError('New module already exists on hosting')
        (candidate/name).write_bytes((ROOT/name).read_bytes())
    path=candidate/'server/multi.py';source=path.read_text(encoding='utf-8')
    source=replace_once(source,'        self.contracts = None\n','        from .player_trade import PlayerTrade\n        self.player_trade = PlayerTrade(self, self.config.database)\n        self.contracts = None\n')
    source=replace_once(source,'                self.presence.disconnect(exchange)\n','                self.player_trade.disconnect(exchange)\n                self.presence.disconnect(exchange)\n')
    path.write_text(source,encoding='utf-8')
    path=candidate/'tools/loopback_exchange.py';source=path.read_text(encoding='utf-8')
    source=replace_once(source,'                self.router.presence.sync(self)\n','                if getattr(self.router, "player_trade", None) is not None:\n                    self.router.player_trade.tick()\n                self.router.presence.sync(self)\n')
    anchor="                    # F0/449 opens the town asynchronously."
    insert='''                    trades = getattr(self.router, 'player_trade', None)
                    if trades is not None:
                        if trades.handle(self, packet):
                            self.router.presence.drain(self, game, outbound)
                            continue
                        trades.guard(self, packet)
'''
    source=replace_once(source,anchor,insert+anchor);path.write_text(source,encoding='utf-8')
    path=candidate/'config/english_translations.json';data=json.loads(path.read_text(encoding='utf-8'));data.update(TRANSLATIONS)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    names=(*NEW,*CHANGED)
    result={n:{'before':hashlib.sha256((baseline/n).read_bytes()).hexdigest() if (baseline/n).exists() else None,
                'after':hashlib.sha256((candidate/n).read_bytes()).hexdigest()} for n in names}
    (FOLDER/'package.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'candidate':str(candidate),'changed':names,'local_player_data_used':False}))
if __name__=='__main__':build()
