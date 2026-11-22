using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;

namespace TioLauncher;

// The original ORANGE packer chooses apphelp.dll instead of user32.dll on some
// Windows installations. See ORANGE_LOADER.md. Only the SHA-pinned client's
// single in-memory module pointer is corrected; files and network code stay intact.
static class GameStarter
{
    internal static readonly TimeSpan StartupTimeout = TimeSpan.FromSeconds(90);
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    struct Startup
    {
        public int cb; public string? reserved, desktop, title;
        public int x,y,w,h,xchars,ychars,fill,flags;
        public short show,reserved2; public IntPtr reservedPtr,input,output,error;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct Info { public IntPtr process,thread; public uint pid,tid; }
    [DllImport("kernel32",CharSet=CharSet.Unicode,SetLastError=true)]
    static extern bool CreateProcess(string app, StringBuilder command, IntPtr pa, IntPtr ta, bool inherit, uint flags, IntPtr environment, string directory, ref Startup startup, out Info info);
    [DllImport("kernel32",SetLastError=true)] static extern bool WaitForDebugEvent(IntPtr data,uint milliseconds);
    [DllImport("kernel32",SetLastError=true)] static extern bool ContinueDebugEvent(uint pid,uint tid,uint status);
    [DllImport("kernel32",SetLastError=true)] static extern bool DebugActiveProcessStop(uint pid);
    [DllImport("kernel32")] static extern bool DebugSetProcessKillOnExit(bool kill);
    [DllImport("kernel32")] static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32")] static extern IntPtr OpenThread(uint access,bool inherit,uint tid);
    [DllImport("kernel32",SetLastError=true)] static extern bool Wow64GetThreadContext(IntPtr thread,IntPtr context);
    [DllImport("kernel32",SetLastError=true)] static extern bool WriteProcessMemory(IntPtr process,IntPtr address,byte[] data,nuint size,out nuint written);
    [DllImport("kernel32")] static extern bool TerminateProcess(IntPtr process,uint code);
    static readonly List<object> startupTrace=new();
    internal static object[] LastTrace => startupTrace.ToArray();
    static void Pin(string path,string hash)
    {
        using var file=File.OpenRead(path);
        if (Convert.ToHexStringLower(SHA256.HashData(file))!=hash)
            throw new InvalidDataException(L.Text("Неподдерживаемая версия ")+Path.GetFileName(path)+L.Text(". Проверьте файлы клиента."));
    }
    public static uint Start(string root,bool probe=false,GameLaunchProfile? profile=null,Action<IntPtr>? attachLifetime=null)
    {
        startupTrace.Clear();
        if (profile?.Verification is null) throw new InvalidDataException("Запускайте игру через TIO Launcher с проверкой обновлений.");
        string interfaceMode = profile.Interface;
        Pin(Path.Combine(root,"ti.exe"),NativeLaunchGate.ImageSha256);
        Pin(Path.Combine(root,"orange.dll"),"5fcf649fe389c32c5caed89719a8fc32049b0bca21b6c20cec8ea50afb28b589");
        if(profile is not null)
        {
            NativeTlsRoute.ValidateImage(Path.Combine(root,"orange.dll"));
            if(profile.OwnedQa && (!File.Exists(Path.Combine(root,".tio-owned-qa")) ||
                File.Exists(Path.Combine(root,"login.ini")) || File.Exists(Path.Combine(root,"base","login.ini"))))
                throw new InvalidDataException(L.Text("Защищённая QA-проверка требует отдельный клиент .tio-owned-qa без login.ini."));
        }
        string selectedRoot = root;
        GameWebsite.Apply(root);
        root = GamePath.ForNativeClient(root);
        startupTrace.Add(new { phase = "native_path_compatibility", short_alias = !string.Equals(selectedRoot, root, StringComparison.OrdinalIgnoreCase) });
        var startup=new Startup { cb=Marshal.SizeOf<Startup>(),flags=1,show=(short)(probe?0:1) };
        string exe=Path.Combine(root,"ti.exe");
        if (!CreateProcess(exe,new StringBuilder('"'+exe+'"'),IntPtr.Zero,IntPtr.Zero,false,2,IntPtr.Zero,root,ref startup,out var info))
            throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        DebugSetProcessKillOnExit(false);
        IntPtr data=Marshal.AllocHGlobal(176), context=Marshal.AllocHGlobal(716);
        uint packed=0; bool success=false, corrected=false; var timer=Stopwatch.StartNew();
        bool englishCaptions=L.Language!="english";
        bool initialNativeBreak=false, initialWowBreak=false, detached=false, canDetach=false,routeInstalled=false;
        NativeTlsRoute.InProcessPlan? route=null;
        NativeOrangeDep.Plan? depBridge=null;
        uint nativeGrid=0;
        bool reconConfigured=false;
        bool guiThemeConfigured=false;
        bool interfaceConfigured=false;
        try
        {
            attachLifetime?.Invoke(info.process);
            while(timer.Elapsed < StartupTimeout)
            {
                if (!detached && WaitForDebugEvent(data,100))
                {
                    uint kind=(uint)Marshal.ReadInt32(data,0), pid=(uint)Marshal.ReadInt32(data,4), tid=(uint)Marshal.ReadInt32(data,8);
                    uint status=0x00010002; // DBG_CONTINUE
                    try
                    {
                        if (kind==1)
                        {
                            uint code=(uint)Marshal.ReadInt32(data,16);
                            long address=Marshal.ReadInt64(data,32);
                            startupTrace.Add(new { phase="exception",code=code.ToString("x8"),address=address.ToString("x") });
                            status=0x80010001u;
                            if(code==0x80000003 && !initialNativeBreak) { initialNativeBreak=true; status=0x00010002; }
                            if(code==0x4000001f && !initialWowBreak) { initialWowBreak=true; status=0x00010002; }
                            IntPtr thread=OpenThread(0x0008,false,tid);
                            try
                            {
                                Marshal.Copy(new byte[716],0,context,716);
                                Marshal.WriteInt32(context,0,0x00010003);
                                if(thread!=IntPtr.Zero && Wow64GetThreadContext(thread,context))
                                {
                                    uint edx=(uint)Marshal.ReadInt32(context,168);
                                    if(packed==0 && (long)edx+0x4055==address) packed=edx;
                                    if(packed!=0 && address==(long)packed+0xf8be)
                                    {
                                        using var process=Process.GetProcessById((int)info.pid);
                                        var modules=process.Modules.Cast<ProcessModule>().ToArray();
                                        var user=modules.Single(m=>m.ModuleName.Equals("user32.dll",StringComparison.OrdinalIgnoreCase));
                                        var app=modules.SingleOrDefault(m=>m.ModuleName.Equals("apphelp.dll",StringComparison.OrdinalIgnoreCase));
                                        uint before=NativeStartupProbe.ReadUInt32(info.process,packed+0x4a13);
                                        uint userBase=(uint)user.BaseAddress.ToInt64();
                                        if(before!=userBase)
                                        {
                                            if(app is null || before!=(uint)app.BaseAddress.ToInt64() || NativeStartupProbe.ReadUInt32(info.process,packed+0xbc80)!=0x81ec8b55)
                                                throw new IOException(L.Text("Неизвестное состояние загрузчика ORANGE; исправление не применено."));
                                            byte[] bytes=BitConverter.GetBytes(userBase);
                                            if(!WriteProcessMemory(info.process,new IntPtr(packed+0x4a13),bytes,4,out var written) || written!=4)
                                                throw new IOException(L.Text("Не удалось исправить загрузку ORANGE."));
                                            corrected=true;
                                        }
                                        if(profile is not null)
                                        {
                                            var orange=modules.Single(m=>m.ModuleName.Equals("orange.dll",StringComparison.OrdinalIgnoreCase));
                                            if((uint)orange.BaseAddress.ToInt64()!=packed) throw new IOException(L.Text("Неизвестный модуль ORANGE."));
                                            depBridge=NativeOrangeDep.Prepare(info.process,modules,packed);
                                            if(depBridge is not null) startupTrace.Add(new {phase="orange_dep_bridge_prepared"});
                                            route=NativeTlsRoute.PrepareInProcess(info.process,modules,packed,profile);
                                            startupTrace.Add(new { phase="tls_bootstrap_prepared" });
                                        }
                                        canDetach=true;
                                    }
                                }
                                else throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
                            }
                            finally { if(thread!=IntPtr.Zero) CloseHandle(thread); }
                        }
                        else if(kind==3 || kind==6)
                        {
                            var file=Marshal.ReadIntPtr(data,16);
                            if(kind==3)
                            {
                                NativeLaunchGate.Release(info.process,checked((uint)Marshal.ReadInt64(data,40)),profile);
                                startupTrace.Add(new { phase="verified_launch_gate_released" });
                                nativeGrid=NativeDoorGrid.Apply(info.process,checked((uint)Marshal.ReadInt64(data,40)));
                                startupTrace.Add(new { phase="native_door_grid_installed" });
                                NativeBattleTurn.Apply(info.process,checked((uint)Marshal.ReadInt64(data,40)));
                                startupTrace.Add(new { phase="native_turn_selection_installed" });
                                bool hdMaps=NativeHdMapTextures.Apply(info.process,checked((uint)Marshal.ReadInt64(data,40)),interfaceMode);
                                startupTrace.Add(new { phase="native_hd_map_textures",enabled=hdMaps });
                            }
                            if(kind==6 && nativeGrid!=0 && file!=IntPtr.Zero && file!=new IntPtr(-1) && NativeEnglish.IsSilver(file))
                            {
                                bool guiTheme = NativeGuiTheme.Apply(info.process, checked((uint)Marshal.ReadInt64(data,24)), root);
                                guiThemeConfigured=true;
                                startupTrace.Add(new { phase="native_gui_theme", enabled=guiTheme });
                                bool bound=NativeDoorGrid.BindRecon(info.process,nativeGrid,checked((uint)Marshal.ReadInt64(data,24)),Path.Combine(root,"silver.dll"));
                                bool moderation = NativePlayerModeration.Apply(info.process,
                                    checked((uint)Marshal.ReadInt64(data,24)), Path.Combine(root,"silver.dll"));
                                startupTrace.Add(new { phase="native_player_moderation", enabled=moderation });
                                bool bidTitle = NativeAuctionBidTitle.Apply(info.process,
                                    checked((uint)Marshal.ReadInt64(data,24)), Path.Combine(root,"silver.dll"));
                                startupTrace.Add(new { phase="native_auction_bid_title", enabled=bidTitle });
                                bool mailCredits = NativeMailCredits.Apply(info.process,
                                    checked((uint)Marshal.ReadInt64(data,24)), Path.Combine(root,"silver.dll"));
                                startupTrace.Add(new { phase="native_mail_credits", enabled=mailCredits });
                                reconConfigured=true;
                                startupTrace.Add(new { phase="native_recon_fog_bound",bound });
                            }
                            if(kind==6 && !interfaceConfigured && file!=IntPtr.Zero && file!=new IntPtr(-1) && NativeEnglish.IsSilver(file))
                            {
                                NativeInterfaceMode.Apply(info.process,checked((uint)Marshal.ReadInt64(data,24)),interfaceMode);
                                interfaceConfigured=true;
                                startupTrace.Add(new { phase="native_interface_mode",mode=interfaceMode });
                            }
                            if(kind==6 && L.Language=="english" && file!=IntPtr.Zero && file!=new IntPtr(-1) && NativeEnglish.IsSilver(file))
                            {
                                uint module=checked((uint)Marshal.ReadInt64(data,24));
                                int captionCount=NativeEnglish.Apply(info.process,module,Path.Combine(root,"silver.dll"));
                                englishCaptions=true;
                                startupTrace.Add(new { phase="native_english_captions",count=captionCount });
                            }
                            if(file!=IntPtr.Zero && file!=new IntPtr(-1)) CloseHandle(file);
                            if(kind==3 && profile is not null)
                            {
                                if(profile.OwnedQa)
                                {
                                    NativeTlsRoute.GuardedPatch(info.process,0x75906f,Convert.FromHexString("e80c25ffff84c07569e86725ffff84c07560"),Convert.FromHexString("e80c25ffff84c09090e86725ffff84c09090"));
                                }
                            }
                        }
                        else if(kind==5) throw new IOException(L.Text("Игра завершилась до загрузки сетевого модуля. Код: ")+Marshal.ReadInt32(data,16));
                    }
                    finally { ContinueDebugEvent(pid,tid,status); }
                    if(canDetach && !detached)
                    {
                        if(!DebugActiveProcessStop(info.pid)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
                        detached=true;
                        startupTrace.Add(new { phase="debugger_detached" });
                    }
                }
                if(detached) Thread.Sleep(50);
                if(detached && NativeStartupProbe.ExitCode(info.process) is uint exitCode)
                    throw new IOException(L.Text("Игра завершилась до загрузки сетевого модуля. Код: ")+exitCode);
                if(NativeStartupProbe.ReadUInt32(info.process,0x76da80)!=0)
                {
                    if(!reconConfigured)
                    {
                        using var gridProcess=Process.GetProcessById((int)info.pid);
                        var silver=gridProcess.Modules.Cast<ProcessModule>().SingleOrDefault(m=>m.ModuleName.Equals("silver.dll",StringComparison.OrdinalIgnoreCase));
                        if(silver is null) continue;
                        bool bound=NativeDoorGrid.BindRecon(info.process,nativeGrid,checked((uint)silver.BaseAddress.ToInt64()),Path.Combine(root,"silver.dll"));
                        bool moderation = NativePlayerModeration.Apply(info.process,
                            checked((uint)silver.BaseAddress.ToInt64()), Path.Combine(root,"silver.dll"));
                        startupTrace.Add(new { phase="native_player_moderation", enabled=moderation });
                        bool bidTitle = NativeAuctionBidTitle.Apply(info.process,
                            checked((uint)silver.BaseAddress.ToInt64()), Path.Combine(root,"silver.dll"));
                        startupTrace.Add(new { phase="native_auction_bid_title", enabled=bidTitle });
                        bool mailCredits = NativeMailCredits.Apply(info.process,
                            checked((uint)silver.BaseAddress.ToInt64()), Path.Combine(root,"silver.dll"));
                        startupTrace.Add(new { phase="native_mail_credits", enabled=mailCredits });
                        reconConfigured=true;
                        startupTrace.Add(new { phase="native_recon_fog_bound",bound });
                    }
                    if(!guiThemeConfigured)
                    {
                        using var themeProcess=Process.GetProcessById((int)info.pid);
                        var silver=themeProcess.Modules.Cast<ProcessModule>().SingleOrDefault(m=>m.ModuleName.Equals("silver.dll",StringComparison.OrdinalIgnoreCase));
                        if(silver is null) continue;
                        bool enabled=NativeGuiTheme.Apply(info.process,checked((uint)silver.BaseAddress.ToInt64()),root);
                        guiThemeConfigured=true;
                        startupTrace.Add(new { phase="native_gui_theme",enabled });
                    }
                    if(!interfaceConfigured)
                    {
                        using var interfaceProcess=Process.GetProcessById((int)info.pid);
                        var silver=interfaceProcess.Modules.Cast<ProcessModule>().SingleOrDefault(m=>m.ModuleName.Equals("silver.dll",StringComparison.OrdinalIgnoreCase));
                        if(silver is null) continue;
                        NativeInterfaceMode.Apply(info.process,checked((uint)silver.BaseAddress.ToInt64()),interfaceMode);
                        interfaceConfigured=true;
                        startupTrace.Add(new { phase="native_interface_mode",mode=interfaceMode });
                    }
                    if(!englishCaptions)
                    {
                        // ORANGE becomes ready before Silver loads. After the
                        // debugger detaches, wait for its actual module base.
                        using var captionProcess=Process.GetProcessById((int)info.pid);
                        var silver=captionProcess.Modules.Cast<ProcessModule>().SingleOrDefault(m=>m.ModuleName.Equals("silver.dll",StringComparison.OrdinalIgnoreCase));
                        if(silver is null) continue;
                        int captionCount=NativeEnglish.Apply(info.process,checked((uint)silver.BaseAddress.ToInt64()),Path.Combine(root,"silver.dll"));
                        englishCaptions=true;
                        startupTrace.Add(new { phase="native_english_captions",count=captionCount });
                    }
                    if(profile is not null)
                    {
                        if(route is null) throw new IOException(L.Text("Защищённый маршрут игры не подготовлен."));
                        route.Verify(info.process);routeInstalled=true;
                        startupTrace.Add(new { phase="tls_route_verified" });
                    }
                    if(!detached && !DebugActiveProcessStop(info.pid)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
                    if(depBridge is not null)
                    {
                        uint count=NativeOrangeDep.Complete(info.process,depBridge);
                        startupTrace.Add(new {phase="orange_dep_bridge_removed",handlers=count,dep_enabled=true});
                        depBridge=null;
                    }
                    success=true;
                    if(probe)
                    {
                        Thread.Sleep(2000);
                        using var live=Process.GetProcessById((int)info.pid);
                        if(live.HasExited || !live.Modules.Cast<ProcessModule>().Any(m=>m.ModuleName.Equals("orange.dll",StringComparison.OrdinalIgnoreCase)))
                            throw new IOException(L.Text("ORANGE не сохранился после завершения загрузки."));
                    }
                    string dir=SteamDistribution.SettingsRoot;
                    Directory.CreateDirectory(dir);
                    File.WriteAllText(Path.Combine(dir,"startup.log"),$"{DateTime.UtcNow:O} pid={info.pid} orange_loaded=true pointer_corrected={corrected} tls_route={routeInstalled}\n");
                    return info.pid;
                }
            }
            throw new IOException(string.Format(L.Text("Сетевой модуль игры не загрузился за {0} секунд."), StartupTimeout.TotalSeconds));
        }
        catch (Exception error)
        {
            // Observe before cleanup terminates the process and destroys its original state.
            error.Data["native_startup"] = NativeStartupProbe.Capture(info.process, info.pid, route?.PhaseAddress);
            throw;
        }
        finally
        {
            if(!success || probe) TerminateProcess(info.process,1);
            if(!success) DebugActiveProcessStop(info.pid);
            CloseHandle(info.thread); CloseHandle(info.process);
            Marshal.FreeHGlobal(context); Marshal.FreeHGlobal(data);
        }
    }
}
