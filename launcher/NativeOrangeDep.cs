using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace TioLauncher;

// Adapts only the pinned ORANGE VM's generated SEH handlers to DEP-valid image entry points.
internal static class NativeOrangeDep
{
    internal const uint ImageCave = 0x80c600;
    internal const int MaximumHandlers = 64;
    internal sealed record Plan(uint Allocation, uint OrangeBase, uint RemoveHandler)
    {
        internal uint State => Allocation + 8192;
    }
    [DllImport("kernel32",SetLastError=true)] static extern bool GetProcessDEPPolicy(IntPtr process,out uint flags,out bool permanent);
    [DllImport("kernel32",SetLastError=true)] static extern bool VirtualFreeEx(IntPtr process,IntPtr address,nuint size,uint kind);
    [DllImport("kernel32",SetLastError=true)] static extern IntPtr CreateRemoteThread(IntPtr process,IntPtr attributes,nuint stackSize,IntPtr start,IntPtr argument,uint flags,out uint id);
    [DllImport("kernel32",SetLastError=true)] static extern uint WaitForSingleObject(IntPtr handle,uint milliseconds);
    [DllImport("kernel32",SetLastError=true)] static extern bool GetExitCodeThread(IntPtr thread,out uint code);
    [DllImport("kernel32")] static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32",SetLastError=true)] static extern IntPtr VirtualAllocEx(IntPtr process,IntPtr address,nuint size,uint allocation,uint protection);
    [DllImport("kernel32",SetLastError=true)] static extern bool WriteProcessMemory(IntPtr process,IntPtr address,byte[] data,nuint size,out nuint written);
    [DllImport("kernel32",SetLastError=true)] static extern bool VirtualProtectEx(IntPtr process,IntPtr address,nuint size,uint protection,out uint old);
    [DllImport("kernel32",SetLastError=true)] static extern bool FlushInstructionCache(IntPtr process,IntPtr address,nuint size);

    internal static bool Enabled(IntPtr process)
    {
        if(!GetProcessDEPPolicy(process,out uint flags,out _)) throw new Win32Exception(Marshal.GetLastWin32Error());
        return (flags&1)!=0;
    }

    internal static Plan? Prepare(IntPtr process, ProcessModule[] modules, uint orange)
    {
        if(!Enabled(process)) return null;
        // The SHA-pinned TI image has an unused executable virtual tail after its last resource byte.
        for(uint i=0;i<512;i+=4) if(NativeStartupProbe.ReadUInt32(process,ImageCave+i)!=0) throw new System.IO.IOException("Unexpected bridge image padding");
        uint Api(string name) => NativeTlsRoute.RemoteExport(process,modules,"kernel32.dll",name);
        uint add=Api("AddVectoredExceptionHandler"), remove=Api("RemoveVectoredExceptionHandler"), query=Api("VirtualQuery"), protect=Api("VirtualProtect"), flush=Api("FlushInstructionCache"), exit=Api("ExitProcess");
        IntPtr memory=VirtualAllocEx(process,IntPtr.Zero,12288,0x3000,0x04);
        if(memory==IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
        if(memory.ToInt64()<0 || memory.ToInt64()>uint.MaxValue-12288) throw new IOException("ORANGE DEP allocation is not an x86 address.");
        uint allocation=(uint)memory.ToInt64(), state=allocation+8192, callback=allocation+512, hook=orange+0xf94b;
        var c=new NativeTlsRoute.X86Code(allocation);
        c.Emit(0x9c,0x60,0x64,0xa1);c.U32(0x24);c.Emit(0xa3);c.U32(state+12);

        c.Push(callback);c.Push(1);c.Call(add);c.Emit(0xa3);c.U32(state);
        c.Emit(0x61,0x9d,0x55,0x8b,0xec);c.Jump(hook+9);
        c.Label("fail");c.Push(1);c.Emit(0xb8);c.U32(exit);c.Emit(0xff,0xd0);
        byte[] install=c.Finish();
        byte[] handler=Build(callback,state,query,protect,flush,exit);
        void Write(uint address,byte[] bytes)
        {
            if(!WriteProcessMemory(process,new IntPtr(address),bytes,(nuint)bytes.Length,out var n) || n!=(nuint)bytes.Length) throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        Write(allocation,install);Write(callback,handler);
        if(!VirtualProtectEx(process,memory,8192,0x20,out _) || !FlushInstructionCache(process,memory,8192)) throw new Win32Exception(Marshal.GetLastWin32Error());
        NativeTlsRoute.GuardedPatch(process,hook,Convert.FromHexString("558beceb04"),[0xe9,..BitConverter.GetBytes(unchecked(allocation-hook-5))]);
        return new Plan(allocation,orange,remove);
    }

    internal static uint Complete(IntPtr process, Plan plan)
    {
        uint handle=NativeStartupProbe.ReadUInt32(process,plan.State);
        uint count=NativeStartupProbe.ReadUInt32(process,plan.State+8);
        if(handle==0) throw new IOException("ORANGE DEP handler did not register.");
        if(count>MaximumHandlers) throw new IOException("ORANGE DEP handler count is invalid.");
        uint hook=plan.OrangeBase+0xf94b;
        NativeTlsRoute.GuardedPatch(process,hook,[0xe9,..BitConverter.GetBytes(unchecked(plan.Allocation-hook-5))],Convert.FromHexString("558beceb04"));
        IntPtr thread=CreateRemoteThread(process,IntPtr.Zero,0,new IntPtr(plan.RemoveHandler),new IntPtr(handle),0,out _);
        if(thread==IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
        try
        {
            uint wait=WaitForSingleObject(thread,5000);
            if(wait==258) throw new TimeoutException("ORANGE DEP handler removal timed out.");
            if(wait!=0 || !GetExitCodeThread(thread,out uint removed)) throw new Win32Exception(Marshal.GetLastWin32Error());
            if(removed==0) throw new IOException("ORANGE DEP handler was not removed.");
        }
        finally { CloseHandle(thread); }
        for(uint i=0;i<count;i++)
        {
            uint original=NativeStartupProbe.ReadUInt32(process,plan.State+16+i*4), slot=ImageCave+i*8;
            NativeTlsRoute.GuardedPatch(process,slot,[0xe9,..BitConverter.GetBytes(unchecked(original-slot-5))],new byte[5]);
        }
        if(!VirtualFreeEx(process,new IntPtr(plan.Allocation),0,0x8000)) throw new Win32Exception(Marshal.GetLastWin32Error());
        if(!Enabled(process)) throw new IOException("DEP changed during ORANGE startup.");
        return count;
    }

    internal static byte[] Build(uint address,uint state,uint query,uint protect,uint flush,uint exit)
    {
        // A vectored observer repairs the original registration, then Windows performs normal SEH dispatch.
        var c=new NativeTlsRoute.X86Code(address);
        const uint cave=ImageCave;
        c.Emit(0x55,0x8b,0xec,0x53,0x56,0x57,0x83,0xec,0x30);
        c.Emit(0xbb);c.U32(state);
        c.Emit(0x64,0xa1);c.U32(0x24);c.Emit(0x3b,0x43,0x0c);c.Branch(0x85,"done");
        c.Emit(0x8b,0x45,0x08,0x8b,0x00,0x8b,0x00);
        foreach(uint code in new uint[]{0xc000001d,0xc0000094,0xc0000005,0x4000001f,0x4000001e,0x80000003,0x80000004})
        {
            c.Emit(0x3d);c.U32(code);c.Branch(0x84,"inspect");
        }
        c.Goto("done");
        c.Label("inspect");
        c.Emit(0xc7,0x44,0x24,0x2c);c.U32(16);c.Emit(0x64,0xa1);c.U32(0);c.Label("node");c.Emit(0xa9);c.U32(3);c.Branch(0x85,"done");
        c.Emit(0x64,0x3b,0x05);c.U32(8);c.Branch(0x82,"done");
        c.Emit(0x64,0x3b,0x05);c.U32(4);c.Branch(0x83,"done");
        c.Emit(0x64,0x8b,0x15);c.U32(4);c.Emit(0x2b,0xd0,0x83,0xfa,0x08);c.Branch(0x82,"done");
        c.Emit(0x8b,0xf0,0x8b,0x7e,0x04,0x8d,0x04,0x24);
        c.Push(28);c.Emit(0x50,0x57);c.Emit(0xb8);c.U32(query);c.Emit(0xff,0xd0,0x85,0xc0);c.Branch(0x84,"next");
        c.Emit(0x81,0x7c,0x24,0x18);c.U32(0x20000);c.Branch(0x85,"next");
        c.Emit(0x83,0x7c,0x24,0x14,0x40);c.Branch(0x85,"next");
        c.Emit(0x81,0x7c,0x24,0x10);c.U32(0x1000);c.Branch(0x85,"next");
        c.Emit(0x8b,0x44,0x24,0x00,0x03,0x44,0x24,0x0c,0x2b,0xc7,0x83,0xf8,0x34);c.Branch(0x82,"next");
        c.Emit(0x8b,0xc7,0xb9);c.U32(8);
        c.Label("normalize");c.Emit(0x80,0x38,0xeb);c.Branch(0x85,"prefix");
        c.Emit(0x0f,0xb6,0x50,0x01,0x83,0xfa,0x04);c.Branch(0x87,"next");
        c.Emit(0x8d,0x44,0x10,0x02,0x49);c.Branch(0x84,"next");c.Goto("normalize");
        c.Label("prefix");c.Emit(0x8b,0x00,0x3d);c.U32(0x0c24548b);c.Branch(0x84,"prefix_valid");c.Emit(0x25);c.U32(0xffffff);c.Emit(0x3d);c.U32(0xec8b55);c.Branch(0x85,"next");c.Label("prefix_valid");
        c.Emit(0x83,0x7b,0x04,0x00);c.Branch(0x85,"known");
        c.Emit(0x8b,0x45,0x08,0x8b,0x00,0x81,0x38);c.U32(0xc000001d);c.Branch(0x85,"next");
        c.Emit(0x8b,0x40,0x0c,0x05);c.U32(0xcf);c.Emit(0x3b,0xc7);c.Branch(0x85,"next");
        c.Emit(0x81,0x7c,0x24,0x0c);c.U32(0x55000);c.Branch(0x85,"next");
        c.Emit(0x8b,0x45,0x08,0x8b,0x00,0x8b,0x40,0x0c,0x3b,0x04,0x24);c.Branch(0x82,"next");
        c.Emit(0x66,0x81,0x38,0x0f,0x0b);c.Branch(0x85,"next");
        c.Emit(0x8b,0x44,0x24,0x04,0x89,0x43,0x04);
        c.Label("known");
        c.Emit(0x8b,0x44,0x24,0x04,0x3b,0x43,0x04);c.Branch(0x85,"next");
        c.Emit(0x8b,0xc7,0x2b,0x43,0x04,0x3d);c.U32(0x55000);c.Branch(0x83,"next");
        c.Emit(0x31,0xc0,0x8b,0x4b,0x08);
        c.Emit(0x83,0xf9,(byte)MaximumHandlers);c.Branch(0x87,"done");
        c.Label("lookup");
        c.Emit(0x3b,0xc1);c.Branch(0x83,"new");
        c.Emit(0x3b,0x7c,0x83,0x10);c.Branch(0x84,"reuse");
        c.Emit(0x40);c.Goto("lookup");
        c.Label("new");
        c.Emit(0x83,0xf8,(byte)MaximumHandlers);c.Branch(0x83,"done");
        c.Emit(0x89,0x44,0x24,0x20,0x8d,0x14,0xc5);c.U32(cave);c.Emit(0x89,0x54,0x24,0x24);
        c.Emit(0x8d,0x44,0x24,0x1c,0x50);c.Push(0x40);c.Push(5);c.Emit(0x52);c.Call(protect);
        c.Emit(0x8b,0x54,0x24,0x24,0xc6,0x02,0xe9,0x8b,0xc7,0x2b,0xc2,0x83,0xe8,0x05,0x89,0x42,0x01);
        c.Push(5);c.Emit(0x52);c.Push(uint.MaxValue);c.Call(flush);
        c.Emit(0x8d,0x44,0x24,0x28,0x50,0xff,0x74,0x24,0x20);c.Push(5);c.Emit(0xff,0x74,0x24,0x30);c.Call(protect);
        c.Emit(0x8b,0x44,0x24,0x20,0x89,0x7c,0x83,0x10,0xff,0x43,0x08);
        c.Label("reuse");
        c.Emit(0x8d,0x14,0xc5);c.U32(cave);c.Emit(0x89,0x56,0x04);
        c.Goto("done");
        c.Label("next");
        c.Emit(0xff,0x4c,0x24,0x2c);c.Branch(0x84,"done");
        c.Emit(0x8b,0x06,0x3b,0xc6);c.Branch(0x86,"done");c.Goto("node");
        c.Label("done");

        c.Emit(0x83,0xc4,0x30,0x5f,0x5e,0x5b,0x5d,0x31,0xc0,0xc2,0x04,0x00);
        c.Label("fail");c.Push(1);c.Emit(0xb8);c.U32(exit);c.Emit(0xff,0xd0);
        return c.Finish();
    }
}
