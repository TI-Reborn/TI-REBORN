// Real offscreen D3D9 sampler acceptance. No game, account or existing window.
using System;
using System.Runtime.InteropServices;
public static class TextureSamplerNative {
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern IntPtr CreateWindowEx(uint ex,string cls,string title,uint style,int x,int y,int w,int h,IntPtr parent,IntPtr menu,IntPtr instance,IntPtr param);
    [DllImport("user32.dll")] static extern bool DestroyWindow(IntPtr hwnd);
    [DllImport("d3d9.dll")] static extern IntPtr Direct3DCreate9(uint sdk);
    [StructLayout(LayoutKind.Sequential)] struct Present { public uint Width,Height,Format,Count,MultiSampleType,MultiSampleQuality,SwapEffect; public IntPtr Window; public int Windowed,EnableDepth; public uint DepthFormat,Flags,Refresh,Interval; }
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int CreateDevice(IntPtr self,uint adapter,uint type,IntPtr hwnd,uint flags,ref Present pp,out IntPtr device);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int SetSamplerState(IntPtr self,uint sampler,uint state,uint value);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetSamplerState(IntPtr self,uint sampler,uint state,out uint value);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate uint Release(IntPtr self);
    static Delegate Method(IntPtr self,int index,Type type) {return Marshal.GetDelegateForFunctionPointer(Marshal.ReadIntPtr(Marshal.ReadIntPtr(self),index*IntPtr.Size),type);}
    static void Free(IntPtr self) {if(self!=IntPtr.Zero)((Release)Method(self,2,typeof(Release)))(self);}
    public sealed class Result {public uint Stage,State,Expected,Actual;public string Device;public int SetHResult,GetHResult;}
    public static Result[] Verify() {
        IntPtr d3d=Direct3DCreate9(32),device=IntPtr.Zero;
        IntPtr hwnd=CreateWindowEx(0,"STATIC","TIO sampler verification",0,0,0,16,16,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero);
        if(d3d==IntPtr.Zero||hwnd==IntPtr.Zero)throw new Exception("Offscreen D3D9 unavailable");
        try {
            Present pp=new Present();pp.Width=16;pp.Height=16;pp.Count=1;pp.SwapEffect=1;pp.Window=hwnd;pp.Windowed=1;pp.Interval=0x80000000;
            int hr=((CreateDevice)Method(d3d,16,typeof(CreateDevice)))(d3d,0,1,hwnd,0x20,ref pp,out device);
            if(hr<0)throw new Exception("HAL CreateDevice HRESULT "+hr.ToString("X8"));
            SetSamplerState set=(SetSamplerState)Method(device,69,typeof(SetSamplerState));
            GetSamplerState get=(GetSamplerState)Method(device,68,typeof(GetSamplerState));
            Result[] results=new Result[32];int index=0;
            for(uint stage=0;stage<8;stage++)for(uint state=5;state<=7;state++) {
                Result r=new Result();r.Stage=stage;r.State=state;r.Expected=2;r.Device="HAL";
                r.SetHResult=set(device,stage,state,2);r.GetHResult=get(device,stage,state,out r.Actual);
                if(r.SetHResult<0||r.GetHResult<0||r.Actual!=2)throw new Exception("Linear sampler not accepted/read back");
                results[index++]=r;
            }
            for(uint stage=0;stage<8;stage++) {
                Result r=new Result();r.Stage=stage;r.State=7;r.Expected=0;r.Device="HAL";
                r.SetHResult=set(device,stage,7,0);r.GetHResult=get(device,stage,7,out r.Actual);
                if(r.SetHResult<0||r.GetHResult<0||r.Actual!=0)throw new Exception("Disabled atlas mips not preserved");
                results[index++]=r;
            }
            return results;
        } finally {Free(device);Free(d3d);DestroyWindow(hwnd);}
    }
}
