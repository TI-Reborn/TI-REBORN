"""Proven original BD request builders89d5a0..89dd2c.

The pinned build has no working BD receive route. The separately reviewed
explicit F8 extension fills the real GUI; these outgoing BD builders stay stock.
"""
from .binary import Reader,PacketError


def decode(packet):
    r=Reader(packet)
    if r.u8()!=0xbd:raise PacketError('Expected SC auction BD')
    op=r.u8()
    if op==1:values=(r.u8(),r.u16())
    elif op==3:values=(r.u32(),r.u16())
    # Ordinary GUI: BD06 manual bid; BD07 own closed-lot claim form.
    elif op in (6,7):values=(r.u32(),)
    elif op==9:
        values=(r.u32(),r.u8())
        if values[1] not in (0,1):raise PacketError('Invalid SC action flag')
    elif op==18:values=()
    elif op==20:
        mode,lot=r.u8(),r.u32()
        if mode not in (0,1,2):raise PacketError('Invalid SC bot action')
        if mode==1:
            # Actual GUI89430c ->89dd2c emits FROM,N,TO, not FROM,TO,N.
            low,bids,high=r.u32(),r.u32(),r.u32();values=(mode,lot,low,high,bids)
        else:values=(mode,lot,0,0,0)
    else:raise PacketError('Unsupported SC auction operation')
    r.finish();return op,values
