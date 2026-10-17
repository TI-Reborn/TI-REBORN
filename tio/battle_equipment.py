"""Restore owned instance metadata after the native template-only actor snapshot."""


def inventory_after_snapshot(fields, viewer, packet):
    if packet[:1]!=b'\x3b' or len(packet)<9:return None
    actor_id=int.from_bytes(packet[1:5],'little')
    owner=int.from_bytes(packet[5:9],'little')
    if owner!=viewer:return None
    for field in fields:
        actor=field._actors.get(actor_id)
        combat=getattr(field,'combat',None)
        if actor is not None and actor.owner_id==viewer and combat is not None and actor_id in combat.inventories:
            return combat.inventory_packet(actor_id)
    return None


def attack_error(error):
    return {
        'Target outside weapon range':'атаки: цель дальше максимальной дальности оружия',
        'Shot is blocked':'атаки: линию огня закрывает препятствие',
        'Visible enemy required':'атаки: нет видимого противника в выбранной клетке',
        'Insufficient action points':'атаки: недостаточно очков действия',
        'Insufficient ammunition':'атаки: недостаточно подходящих патронов',
        'Character does not own an active turn':'атаки: сейчас не ваш ход',
        'Actor not selected for turn':'атаки: этот боец не выбран для текущего хода',
        'Weapon effect is not implemented':'атаки: действие этого оружия пока не реализовано',
    }.get(str(error),'атаки: запрос не выполнен')
