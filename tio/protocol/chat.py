"""21 send (9ff706), 22 receive (9fed8c); UTF-16LE terminated text."""
from .binary import Reader,Writer,PacketError


def text_read(r):
    raw=bytearray()
    while (word:=r.read(2))!=b'\0\0':
        raw.extend(word)
        if len(raw)>800:raise PacketError('Сообщение чата слишком длинное (максимум 200 символов)')
    try:text=raw.decode('utf-16-le')
    except UnicodeError as exc:raise PacketError('Invalid Unicode') from exc
    # Clipboard text can contain line breaks even in the native single-line edit.
    text=text.replace('\r\n',' ').translate(str.maketrans('\r\n\t','   '))
    if len(text)>200:raise PacketError('Сообщение чата слишком длинное (максимум 200 символов)')
    if not text.strip() or any(ord(c)<32 for c in text):raise PacketError('Сообщение чата пустое или содержит недопустимые символы')
    return text


def decode_send(packet):
    r=Reader(packet)
    if r.u8()!=0x21:raise PacketError('Expected chat request')
    channel=r.u8();text=text_read(r);recipient=bytearray()
    if channel==1:
        while (c:=r.u8())!=0:
            recipient.append(c)
            if len(recipient)>32:raise PacketError('Recipient too long')
        if not recipient:raise PacketError('Recipient required')
    r.finish()
    return channel,text,bytes(recipient)


def encode_message(channel,name,text):
    if not name or b'\0' in name or len(name)>255:raise PacketError('Invalid sender')
    w=Writer().u8(0x22).u32(0).u8(channel)
    w.data.extend(name+b'\0'+text.encode('utf-16-le')+b'\0\0')
    return w.build()


def encode_system_message(channel,name,text):
    """Only server-authored text; ordinary encode_message remains opaque."""
    from tio.localization import LocalizedPacket,english
    return LocalizedPacket(encode_message(channel,name,text),
        lambda:encode_message(channel,english(name.decode('cp1251')).encode('cp1251'),english(text)))
