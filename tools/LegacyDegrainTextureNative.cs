// Offscreen native D3DX9 validation. No game client or player session is simulated.
using System;
using System.IO;
using System.Runtime.InteropServices;

public static class LegacyDegrainTextureNative {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] static extern bool SetDllDirectory(string path);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern IntPtr CreateWindowEx(uint ex,string cls,string title,uint style,int x,int y,int w,int h,IntPtr parent,IntPtr menu,IntPtr instance,IntPtr param);
    [DllImport("user32.dll")] static extern bool DestroyWindow(IntPtr hwnd);
    [DllImport("d3d9.dll")] static extern IntPtr Direct3DCreate9(uint sdk);
    [DllImport("d3dx9_26.dll")] static extern int D3DXGetImageInfoFromFileInMemory(byte[] data,uint length,out Info info);
    [DllImport("d3dx9_26.dll")] static extern int D3DXCreateTextureFromFileInMemoryEx(IntPtr device,byte[] data,uint length,uint width,uint height,uint levels,uint usage,uint format,uint pool,uint filter,uint mipFilter,uint colorKey,out Info info,IntPtr palette,out IntPtr texture);
    [StructLayout(LayoutKind.Sequential)] public struct Info { public uint Width,Height,Depth,MipLevels,Format,ResourceType,ImageFileFormat; }
    [StructLayout(LayoutKind.Sequential)] public struct Description { public uint Format,Type,Usage,Pool,MultiSampleType,MultiSampleQuality,Width,Height; }
    [StructLayout(LayoutKind.Sequential)] struct Present { public uint Width,Height,Format,Count,MultiSampleType,MultiSampleQuality,SwapEffect; public IntPtr Window; public int Windowed,EnableDepth; public uint DepthFormat,Flags,Refresh,Interval; }
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int CreateDevice(IntPtr self,uint adapter,uint type,IntPtr hwnd,uint flags,ref Present pp,out IntPtr device);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetDescription(IntPtr self,uint level,out Description desc);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate uint LevelCount(IntPtr self);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate uint Release(IntPtr self);
    static Delegate Method(IntPtr self,int index,Type type) { return Marshal.GetDelegateForFunctionPointer(Marshal.ReadIntPtr(Marshal.ReadIntPtr(self),index*IntPtr.Size),type); }
    static void Free(IntPtr self) { if(self!=IntPtr.Zero)((Release)Method(self,2,typeof(Release)))(self); }
    public sealed class Result { public string Path; public uint Width,Height,TextureWidth,TextureHeight,TextureLevels,ImageFormat,TextureFormat; public string Device,Codec; }
    public static Result[] Verify(string list,string dllFolder) {
        if(IntPtr.Size!=4)throw new Exception("The original D3DX9 DLL requires an x86 process.");
        SetDllDirectory(dllFolder);
        IntPtr d3d=Direct3DCreate9(32),device=IntPtr.Zero;
        IntPtr hwnd=CreateWindowEx(0,"STATIC","TIO texture verification",0,0,0,16,16,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero);
        if(d3d==IntPtr.Zero||hwnd==IntPtr.Zero)throw new Exception("Unable to create an offscreen D3D9 device.");
        string selected="HAL";
        try {
            Present pp=new Present();pp.Width=16;pp.Height=16;pp.Count=1;pp.SwapEffect=1;pp.Window=hwnd;pp.Windowed=1;pp.Interval=0x80000000;
            CreateDevice create=(CreateDevice)Method(d3d,16,typeof(CreateDevice));
            int hr=create(d3d,0,1,hwnd,0x20,ref pp,out device);
            if(hr<0){selected="NULLREF";hr=create(d3d,0,4,hwnd,0x20,ref pp,out device);}
            if(hr<0)throw new Exception("CreateDevice HRESULT "+hr.ToString("X8"));
            string[] paths=File.ReadAllLines(list);Result[] results=new Result[paths.Length];
            for(int i=0;i<paths.Length;i++){
                byte[] data=File.ReadAllBytes(paths[i]);Info info;IntPtr texture=IntPtr.Zero;string codec="standard image";
                if(data.Length>55 && data[0]==7 && data[1]==0xe1 && data[2]==0x81){
                    byte[] plain=new byte[data.Length];int key=100;
                    for(int j=0;j<data.Length;j++){int cipher=data[j];plain[j]=(byte)(cipher^(key>>8));key=unchecked((key+cipher)*0xce6d+0x58bf)&65535;}
                    if(System.Text.Encoding.ASCII.GetString(plain,0,8)!="\x07"+"AJPG_EX")throw new Exception("Invalid AJPG header");
                    int colors=checked((int)BitConverter.ToUInt64(plain,39)),masks=checked((int)BitConverter.ToUInt64(plain,47));
                    if(55+colors+masks!=plain.Length)throw new Exception("Invalid AJPG stream lengths");
                    byte[] mask=new byte[masks];Array.Copy(plain,55+colors,mask,0,masks);
                    Info maskInfo;IntPtr maskTexture=IntPtr.Zero;
                    hr=D3DXCreateTextureFromFileInMemoryEx(device,mask,(uint)mask.Length,0,0,1,0,0,1,1,1,0,out maskInfo,IntPtr.Zero,out maskTexture);
                    if(hr<0)throw new Exception(paths[i]+" mask HRESULT "+hr.ToString("X8"));
                    Free(maskTexture);
                    data=new byte[colors];Array.Copy(plain,55,data,0,colors);
                    hr=D3DXGetImageInfoFromFileInMemory(data,(uint)data.Length,out info);
                    if(hr<0||info.Width!=maskInfo.Width||info.Height!=maskInfo.Height)throw new Exception("AJPG plane dimensions differ");
                    codec="AJPG_EX: native D3DX color and original mask planes";
                }
                hr=D3DXGetImageInfoFromFileInMemory(data,(uint)data.Length,out info);
                if(hr<0)throw new Exception(paths[i]+" image HRESULT "+hr.ToString("X8"));
                hr=D3DXCreateTextureFromFileInMemoryEx(device,data,(uint)data.Length,0,0,1,0,0,1,1,1,0,out info,IntPtr.Zero,out texture);
                if(hr<0)throw new Exception(paths[i]+" texture HRESULT "+hr.ToString("X8"));
                try {
                    Description desc;hr=((GetDescription)Method(texture,17,typeof(GetDescription)))(texture,0,out desc);
                    if(hr<0)throw new Exception(paths[i]+" GetLevelDesc HRESULT "+hr.ToString("X8"));
                    results[i]=new Result();results[i].Path=paths[i];results[i].Width=info.Width;results[i].Height=info.Height;results[i].TextureWidth=desc.Width;results[i].TextureHeight=desc.Height;
                    results[i].TextureLevels=((LevelCount)Method(texture,13,typeof(LevelCount)))(texture);results[i].ImageFormat=info.Format;results[i].TextureFormat=desc.Format;results[i].Device=selected;results[i].Codec=codec;
                } finally {Free(texture);}
            }
            return results;
        } finally {Free(device);Free(d3d);DestroyWindow(hwnd);}
    }
}

