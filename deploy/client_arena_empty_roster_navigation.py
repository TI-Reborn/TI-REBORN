"""Compose actual Arena mode0 browsing over immutable search-status candidate.

Original Arena/help_arena85A0F2 passes selector mode0. The prior mode4-only
presentation fix covered a different caller. Modes0 and4 now both preserve
Team/Wall browsing with an empty eligible roster. Other native paths remain.
"""
from . import client_arena_lobby_search_status as prior
from . import client_arena_lobby_navigation as navigation
from .client_equipment_batch import Code
from .client_server_list_status import sha
BASE_SHA=prior.BASE_SHA
GREEN=prior.GREEN
GRAY=prior.GRAY
SIGNATURE=b'TIO-arena-actual-mode0-Team-Wall-browse-owned-roster-search-v4'

def payload():
    c=Code(navigation.OPEN_HELPER);c.emit('9c60');c.base()
    c.emit('8b44241c 8883');c.word(navigation.MODE)
    c.emit('3c04');c.branch('0f84','enable')
    c.emit('84c0');c.branch('0f85','done')
    c.label('enable')
    for field in (navigation.TEAM,navigation.WALL):
        c.emit('8b83');c.word(field);c.emit('c6404a01')
    c.label('done');c.emit('619d c3');result=c.finish(0x100)
    c=Code(navigation.EMPTY_HELPER);c.emit('9c 53 52');c.base()
    c.emit('8a93');c.word(navigation.MODE)
    c.emit('80fa04');c.branch('0f84','enable')
    c.emit('84d2');c.branch('0f84','enable')
    c.emit('31d2');c.branch('e9','write')
    c.label('enable');c.emit('b201')
    c.label('write')
    for field in (navigation.TEAM,navigation.WALL):
        c.emit('8b83');c.word(field);c.emit('88504a')
    c.emit('5a 5b 9d');c.jump(0x9442f5)
    return (result+c.finish(0x100)+prior.payload()[0x200:0x600]+SIGNATURE+b'\0').ljust(navigation.APPEND_SIZE,b'\0')

def patch(source):
    previous=prior.patch(source);candidate=previous[:len(source)]+payload()
    assert len(candidate)==len(previous)
    assert candidate[:len(source)]==previous[:len(source)]
    assert candidate[len(source)+0x200:len(source)+0x600]==previous[len(source)+0x200:len(source)+0x600]
    return candidate

def review(source,candidate):
    if patch(source)!=candidate:raise ValueError('Empty-roster navigation differs from exact native composition')
    review=prior.review(source,prior.patch(source));review['appended_sha256']=sha(candidate[len(source):]);return review

def metadata():
    value=prior.metadata();value.update(native_revision='actual-Arena-mode0-browse-v4',selector_mode=0,selector_modes_enabled=[0,4],actual_Arena_native_entry='85a0dc push0 ->85a0f2 ->93fe70',original_help_arena_key='85a41c',previous_colour_helpers_unchanged=True,published=False)
    return value
