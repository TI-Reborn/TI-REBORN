"""Private city chat adapter; backend provides the current authenticated actor."""
from datetime import datetime,timezone

from tio.social_completion import clan_delay,alliance_status,alliance_cancel
from tio.protocol.chat import encode_system_message


def command(db, session, text, *, city_idle, now=None):
    parts=text.strip().split(maxsplit=2)
    if not parts or parts[0].casefold()!='!clan':return None
    action=parts[1].casefold() if len(parts)>1 else 'help'
    if action in ('help','delay','status') and len(parts)<=2:
        delay=clan_delay(db,session.account,now=now)
        lines=['!clan delay — время до вступления в клан; !clan status — состояние альянса.',
               '!clan alliancecancel ИМЯ АЛЬЯНСА — отмена назначенного роспуска.'] if action=='help' else []
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
