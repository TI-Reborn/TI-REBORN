"""Private city chat adapter; backend provides the current authenticated actor."""
from datetime import datetime,timezone
from functools import lru_cache
from textwrap import wrap

from tio.clans import warehouse_log
from tio.item_catalog import items_root
from tio.social_completion import clan_delay,alliance_status,alliance_cancel
from tio.protocol.chat import encode_system_message


@lru_cache(maxsize=1)
def _item_names() -> dict[int, str]:
    return {int(item.get('id')): item.get('name') for item in items_root().iter('item') if item.get('name')}


def _warehouse_log(db, account: str, argument: str) -> tuple[bytes, ...]:
    if not argument.isascii() or not argument.isdecimal() or len(argument)>6:
        raise ValueError('Укажите номер страницы: !clan log 2')
    page = int(argument)
    entries, more = warehouse_log(db, account, page)
    lines = [f'Клановый склад — журнал, стр. {page} (UTC).']
    for created, actor, deposits, withdrawals in entries:
        stamp = datetime.fromtimestamp(created, timezone.utc).strftime('%d.%m.%Y %H:%M')
        for verb, items in (('положил', deposits), ('забрал', withdrawals)):
            if items:
                names = ', '.join(f"{_item_names().get(template, f'#{key}')} ×{count}"
                                  for template, key, count in items)
                lines.extend(wrap(f'{stamp} {actor} {verb} {names}', width=155, subsequent_indent='  '))
    if not entries:
        lines.append('На этой странице нет операций.')
    if more:
        lines.append(f'Следующая страница — !clan log {page + 1}')
    return tuple(encode_system_message(4,b'Clan',line) for line in lines)


def command(db, session, text, *, city_idle, now=None):
    parts=text.strip().split(maxsplit=2)
    if not parts or parts[0].casefold()!='!clan':return None
    action=parts[1].casefold() if len(parts)>1 else 'help'
    if action=='log':
        return _warehouse_log(db,session.account,parts[2] if len(parts)==3 else '1')
    if action in ('help','delay','status') and len(parts)<=2:
        delay=clan_delay(db,session.account,now=now)
        lines=['!clan delay — время до вступления в клан; !clan status — состояние альянса.',
               '!clan alliancecancel ИМЯ АЛЬЯНСА — отмена назначенного роспуска.',
               '!clan log [страница] — журнал кланового склада.'] if action=='help' else []
        hours,minutes=divmod((delay['remaining_seconds']+59)//60,60)
        lines.append('Вступление в клан доступно по приглашению.' if delay['can_join'] else f"До вступления в клан: {hours} ч. {minutes} мин.")
        status=alliance_status(db,session.account,now=now)
        if status:
            line=f"Альянс {status['name']}: "+('действует.' if status['state']=='active' else 'роспуск назначен.' if status['state']=='dissolving' else 'срок отмены роспуска истёк.')
            lines.append(line)
            if status['can_cancel']:
                until=datetime.fromtimestamp(status['dissolution_until'],timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
                lines.append(f"Отмена до {until}: !clan alliancecancel {status['name']}")
        return tuple(encode_system_message(4,b'Clan',line) for line in lines)
    if action=='alliancecancel' and len(parts)==3:
        if not city_idle:raise ValueError('Отмена роспуска доступна в городе вне боя и заявок')
        alliance_cancel(db,session.database,session.account,parts[2],now=now)
        return (encode_system_message(4,b'Clan','Роспуск альянса отменён. Название и состав сохранены; дополнительных расходов нет.'),)
    raise ValueError('Неверная клановая команда; !clan help')
