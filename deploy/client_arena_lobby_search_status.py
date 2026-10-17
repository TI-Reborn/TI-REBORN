"""Exact published .2 -> arena navigation plus occupied/search status colours.

The prior afaa navigation transformer is immutable. This new composition adds
only a status check to its appended ordinary Team/Wall eligible-row endpoints.
Authentic no-eligible rows remain red even when full/searching.
"""
from . import client_arena_lobby_navigation as prior
from .client_equipment_batch import Code
from .client_server_list_status import sha
BASE_SHA=prior.BASE_SHA
IMAGE_BASE=prior.IMAGE_BASE
BA_COLOUR_HELPER=prior.BA_COLOUR_HELPER
C8_COLOUR_HELPER=prior.C8_COLOUR_HELPER
GREEN=prior.GREEN
GRAY=prior.GRAY
SIGNATURE=b'TIO-arena-Team-Wall-navigation-owned-roster-colours-search-v3'

def endpoints(c,continuation):
    c.emit('c6462800 807e1e00');c.branch('0f85','gray')
    c.emit('b8');c.word(GREEN)
    c.emit('8a561d 3a561c');c.branch('0f82','colour')
    c.label('gray');c.emit('b8');c.word(GRAY)
    c.label('colour');c.emit('894624');c.jump(continuation)

def ba_colour():
    c=Code(BA_COLOUR_HELPER)
    c.emit('807e1001');c.branch('0f84','owned')
    c.emit('807e1004');c.branch('0f84','owned')
    c.emit('0fb6461a 3b45fc');c.branch('0f8f','red')
    c.emit('0fb6461b 3b45fc');c.branch('0f8c','red')
    c.jump(0x872ab2)
    c.label('owned');c.emit('9c60');c.base()
    c.emit('8b93');c.word(0xac618c-IMAGE_BASE);c.emit('b91f000000')
    c.label('slot');c.emit('8b02 85c0');c.branch('0f84','next')
    c.emit('80784100');c.branch('0f84','next')
    c.emit('8b80fc5f0000 83f801');c.branch('0f82','next')
    c.emit('83f814');c.branch('0f87','next')
    c.emit('0fb65e1a 3bc3');c.branch('0f82','next')
    c.emit('0fb65e1b 3bc3');c.branch('0f86','eligible')
    c.label('next');c.emit('83c204 49');c.branch('0f85','slot')
    c.emit('619d');c.jump(0x872aed)
    c.label('eligible');c.emit('619d');endpoints(c,0x872af8)
    c.label('red');c.jump(0x872aed)
    return c.finish(0x200)

def c8_colour():
    c=Code(C8_COLOUR_HELPER)
    c.emit('807e1001');c.branch('0f84','ordinary')
    c.emit('807e1004');c.branch('0f85','stock')
    c.label('ordinary');c.emit('837e2c00');c.branch('0f85','stock')
    endpoints(c,0x872ca0)
    c.label('stock')
    c.emit('0fb6461b 2b45fc 8945ec 837dec05');c.branch('0f8d','five')
    c.emit('8b45ec 8945e8');c.branch('e9','blend')
    c.label('five');c.emit('c745e805000000')
    c.label('blend');c.emit('6b4de829 badbefb100 b8ff606000');c.call(0xa897c8)
    c.emit('894624');c.jump(0x872ca0)
    return c.finish(0x200)

def payload():
    return (prior.payload()[:0x200]+ba_colour()+c8_colour()+SIGNATURE+b'\0').ljust(prior.APPEND_SIZE,b'\0')

def patch(source):
    original=prior.patch(source)
    result=original[:len(source)]+payload()
    assert len(result)==len(original)
    assert result[:len(source)+0x200]==original[:len(source)+0x200]
    return result

def review(source,candidate):
    if patch(source)!=candidate:raise ValueError('Candidate differs from exact ordinary search-status composition')
    review=prior.review(source,prior.patch(source))
    review['appended_sha256']=sha(candidate[len(source):]);return review

def metadata():
    data=prior.metadata()
    data.update(native_revision='search-status-v3',previous_afaa_presentation_unchanged_except_appended_eligible_endpoints=True,eligible_waiting_free_colour='ff50e070',eligible_full_or_nonzero_status_colour='ff606060',no_eligible_colour_priority='ff6060ff',search_status_byte='row+1e',all_existing_auth_texture_status_hooks_preserved=True)
    return data
