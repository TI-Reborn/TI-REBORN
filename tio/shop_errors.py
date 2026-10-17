"""Translate known shop rejections into the client's localized parameter error."""
from .protocol.system_message import encode_shop_error, encode_insufficient_credits


def shop_error_reply(error):
    if str(error)=='Insufficient credits':
        return encode_insufficient_credits()
    reasons = {
        'Inventory is full': 'покупки: в инвентаре недостаточно свободных мест',
        'Insufficient gold': 'покупки: недостаточно Gold',
        'Premium catalog changed; reopen shop': 'цены: откройте магазин заново',
        'SC local catalog accepts Gold only': 'оплаты SC: выберите покупку за Gold',
        'Unknown SC offer': 'товара SC: предложение недоступно',
        'SC stock exhausted': 'товара SC: предложение закончилось',
        'SC stock or cart quantity limit exceeded': 'корзины SC: достигнуто доступное количество',
        'Empty or oversized SC purchase': 'корзины SC: выберите от 1 до 1000 товаров',
        'Wallet or owned SC recipient missing': 'получателя SC: выберите своего наёмника',
        'SC purchases require the city and an owned recipient': 'покупки SC: выйдите из боя и выберите своего наёмника',
        'Armor requires a female mercenary': 'экипировки: эта броня предназначена только для женщин',
        'Insufficient credits': 'покупки: недостаточно кредитов',
        'Quantity must be 1..1000 (local policy)': 'количества: допустимо от 1 до 1000',
        'Unknown or ambiguous offer': 'товара: предложение недоступно',
        'Wallet or owned recipient missing': 'получателя: наёмник не найден',
        'Sale item missing or unsupported': 'продажи: предмет недоступен',
        'Only individual weapon instances supported': 'продажи: выберите один предмет',
        'Worn, equipped or modified item sale not yet supported': 'продажи: этот предмет пока не поддерживается',
        'Inventory template not implemented': 'товара: этот предмет пока не поддерживается',
        'Credit balance overflow': 'баланса: превышен предел кредитов',
    }
    return encode_shop_error(reasons.get(str(error), 'операции магазина: запрос не выполнен'))
