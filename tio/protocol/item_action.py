"""Shared item action33 envelope, also reached from the Wear button.

The option byte indexes a target mask; it is not itself an inventory slot.
"""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError

# Original a7a050, used at a65280 when a target control was supplied.
TARGET_MASKS = (1, 2, 4, 8, 0x10, 0x20, 0x40, 0x80, 0x100, 0x200,
                0x400, 0x4000, 0x8000, 0x10000, 0x20000, 0x40000,
                0x80000, 0x100000, 0x200000)


def item_target_option(mask: int) -> int:
    """Match client conversion, including FF for an unrecognized target."""
    return TARGET_MASKS.index(mask) if mask in TARGET_MASKS else 255


@dataclass(frozen=True)
class ItemAction:
    pet_id: int
    instance_id: int
    option: int

    @property
    def target_mask(self) -> int | None:
        """None means unspecified; reject unknown explicit target indices."""
        if self.option == 255:
            return None
        if not 0 <= self.option < len(TARGET_MASKS):
            raise PacketError('Unknown item action target option')
        return TARGET_MASKS[self.option]


def encode_item_action(action: ItemAction) -> bytes:
    return (Writer().u8(0x33).u32(action.pet_id).u32(action.instance_id)
            .u8(action.option).build())


def decode_item_action(packet: bytes) -> ItemAction:
    r = Reader(packet)
    if r.u8() != 0x33:
        raise PacketError('Expected item action33')
    action = ItemAction(r.u32(), r.u32(), r.u8())
    r.finish()
    return action
