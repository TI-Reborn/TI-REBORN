"""Execute the exact launcher-native layout under ASLR with GUI ABI sentinels."""
import json
from pathlib import Path
import struct
import unittest

from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE
from unicorn.x86_const import *
from deploy.client_contracts_windows import build_plan,relocate,ENTRY,HEADER,RECORDS,STRIDE,COUNT,widgets

ROOT=Path(__file__).resolve().parents[1]
ALLOC=0x21000000
HEAP=0x30000000
STACK=0x31000000
STOP=0x32000000


class Gui:
    def __init__(self,silver):
        self.silver=silver;self.u=Uc(UC_ARCH_X86,UC_MODE_32);self.plan=build_plan()
        self.u.mem_map(silver,0x900000);self.u.mem_map(ALLOC,self.plan['size']);self.u.mem_write(ALLOC,relocate(self.plan,ALLOC,silver))
        self.u.mem_map(HEAP,0x100000);self.u.mem_map(STACK,0x10000);self.u.mem_map(STOP,0x1000)
        self.next=HEAP+0x10000;self.city=HEAP+0x1000;self.parent=HEAP+0x2000
        self.vmt=HEAP+0x3000;self.virtual=HEAP+0x4000;self.put(self.vmt,self.virtual)
        self.put(self.city+0x288,self.parent);self.children=[];self.calls=[];self.captions={};self.callbacks=[]
        self.put(self.va(0xac5d58),HEAP+0x5000);self.put(HEAP+0x5000,3)
        self.handlers={self.va(k):v for k,v in {
            0x8d3604:self.decorate,0xa4517c:self.button,0xa4341c:self.window,
            0xa47d78:self.label,0xa45ab4:self.edit,0xa55038:self.event,
            0xa42b04:self.caption,0xa43630:self.width,0xa43748:self.center,
            0xa424d4:self.count,0xa424c4:self.child,0x4095ac:self.instance,
        }.items()}
        self.handlers[self.virtual]=self.visible
        self.stop_at=None;self.u.hook_add(UC_HOOK_CODE,self.hook)
    def va(self,n):return self.silver+n-0x400000
    def get(self,p):return struct.unpack('<I',self.u.mem_read(p,4))[0]
    def put(self,p,n):self.u.mem_write(p,struct.pack('<I',n&0xffffffff))
    def reg(self,r,value=None):
        if value is not None:self.u.reg_write(r,value)
        return self.u.reg_read(r)
    def ret(self,n=0):
        sp=self.reg(UC_X86_REG_ESP);self.reg(UC_X86_REG_EIP,self.get(sp));self.reg(UC_X86_REG_ESP,sp+4+n)
    def hook(self,u,address,size,unused):
        if address==STOP or address==self.stop_at:self.u.emu_stop()
        elif address in self.handlers:self.handlers[address]()
    def create(self,kind):
        result=self.next;self.next+=0x400;self.put(result,self.vmt);self.calls.append((kind,self.reg(UC_X86_REG_ECX),self.reg(UC_X86_REG_EDX)&255))
        if kind=='button':
            parent=self.get(self.reg(UC_X86_REG_ESP)+4);self.calls[-1]+= (parent,)
            if parent==self.city:self.children.append(result)
        self.reg(UC_X86_REG_EAX,result);self.ret(4 if kind=='button' else 0)
    def button(self):self.create('button')
    def label(self):self.create('label')
    def edit(self):self.create('edit')
    def window(self):self.create('window')
    def decorate(self):
        sp=self.reg(UC_X86_REG_ESP);self.calls.append(('decoration',tuple(self.get(sp+4+i*4) for i in range(5))))
        self.reg(UC_X86_REG_EAX,0x12345678);self.ret(20)
    def event(self):self.callbacks.append(self.reg(UC_X86_REG_EDX));self.ret()
    def caption(self):
        p=self.reg(UC_X86_REG_EDX);size=self.get(p-4);self.captions[self.reg(UC_X86_REG_EAX)]=bytes(self.u.mem_read(p,size)).decode('utf-16-le');self.ret()
    def width(self):self.put(self.reg(UC_X86_REG_EAX)+0x38,self.reg(UC_X86_REG_EDX));self.ret()
    def center(self):self.ret()
    def count(self):self.reg(UC_X86_REG_EAX,len(self.children));self.ret()
    def child(self):self.reg(UC_X86_REG_EAX,self.children[self.reg(UC_X86_REG_EDX)]);self.ret()
    def instance(self):self.reg(UC_X86_REG_EAX,1);self.ret()
    def visible(self):self.u.mem_write(self.reg(UC_X86_REG_EAX)+0x49,bytes((self.reg(UC_X86_REG_EDX)&255,)));self.ret()
    def run(self,entry,stack=()):
        sp=STACK+0x8000;self.put(sp,STOP)
        for i,n in enumerate(stack):self.put(sp+4+i*4,n)
        self.reg(UC_X86_REG_ESP,sp);self.u.emu_start(ALLOC+entry,STOP+1,count=200000)
        if self.reg(UC_X86_REG_EIP) not in (STOP,self.stop_at):raise AssertionError('Native instruction budget exhausted')


class ContractsNativeWindowsTests(unittest.TestCase):
    def test_city_constructor_preserves_native_call_and_registers(self):
        for silver in (0x400000,0x1400000):
            gui=Gui(silver);gui.reg(UC_X86_REG_EBX,gui.city);gui.reg(UC_X86_REG_EFLAGS,0x246)
            gui.run(ENTRY['construct'],(11,22,33,44,55))
            self.assertEqual(gui.calls[0],('decoration',(11,22,33,44,55)))
            self.assertEqual(gui.reg(UC_X86_REG_EAX),0x12345678);self.assertEqual(gui.reg(UC_X86_REG_EBX),gui.city)
            self.assertEqual(gui.reg(UC_X86_REG_EFLAGS)&0xfff,0x246)
            self.assertEqual(len(gui.children),2);self.assertEqual(gui.get(ALLOC+HEADER+24),gui.city)
    def test_native_window_parent_geometry_controls_and_state_update(self):
        for silver in (0x400000,0x1400000):
            gui=Gui(silver);gui.put(ALLOC+HEADER+24,gui.city);gui.run(ENTRY['initialize'])
            self.assertEqual(gui.calls[0],('window',gui.parent,1));self.assertEqual(len(gui.calls),len(widgets())+1)
            window=gui.get(ALLOC+RECORDS+2*STRIDE)
            self.assertEqual(gui.get(window+0x38),800);self.assertEqual(gui.get(window+0x3c),576)
            self.assertEqual(bytes(gui.u.mem_read(window+0x2ac,1)),b'\1')
            for i in range(3,COUNT):
                row=ALLOC+RECORDS+i*STRIDE;gui.put(row+4,int(i%2==0));gui.put(row+8,1)
                text=f'Строка {i}'.encode('utf-16-le');gui.put(row+12,len(text));gui.u.mem_write(row+16,text+b'\0\0')
            gui.put(ALLOC+HEADER,1);gui.run(ENTRY['update']);self.assertEqual(gui.get(ALLOC+HEADER),0)
            for i in range(3,COUNT):
                p=gui.get(ALLOC+RECORDS+i*STRIDE);self.assertNotEqual(p,0)
                self.assertEqual(bytes(gui.u.mem_read(p+0x49,1)),bytes((int(i%2==0),)))
                if i!=31:self.assertEqual(gui.captions[p],f'Строка {i}')
                else:self.assertNotIn(p,gui.captions,'Polling must not overwrite typed invitation names')
    def test_callbacks_are_bounded_and_preserve_flags_and_stack(self):
        gui=Gui(0x1400000)
        for i in (0,1,5,22,32,44,50,56):
            gui.put(ALLOC+HEADER+4,0);gui.reg(UC_X86_REG_EAX,0xabc123);gui.reg(UC_X86_REG_EFLAGS,0x246)
            gui.run(0x6000+i*32)
            self.assertEqual(gui.get(ALLOC+HEADER+4),i+1);self.assertEqual(gui.reg(UC_X86_REG_EAX),0xabc123)
            self.assertEqual(gui.reg(UC_X86_REG_EFLAGS)&0xfff,0x246);self.assertEqual(gui.reg(UC_X86_REG_ESP),STACK+0x8004)
            gui.run(0x6000+((i+1)%COUNT)*32);self.assertEqual(gui.get(ALLOC+HEADER+4),i+1)
    def test_resource_plan_is_reproducible_and_sections_do_not_overlap(self):
        plan=build_plan();self.assertEqual(plan,json.loads((ROOT/'launcher/Assets/native-contracts-windows.json').read_text()))
        occupied=[]
        for block in plan['blocks']:
            start=block['offset'];end=start+len(bytes.fromhex(block['hex']))
            self.assertLess(end,HEADER);self.assertFalse(any(start<b and a<end for a,b in occupied));occupied.append((start,end))
        self.assertLess(RECORDS+COUNT*STRIDE,plan['size'])


if __name__=='__main__':unittest.main()
