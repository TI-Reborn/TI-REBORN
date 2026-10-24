using System.Diagnostics;
using System.Drawing.Drawing2D;

namespace TioLauncher;

static class Program
{
    [STAThread]
    static void Main(string[] args)
    {
        if (args.Length == 3 && args[0] == "--item-effect-tooltips-self-test")
        {
            Environment.ExitCode = ItemEffectTooltipSelfTest.Run(args[1], args[2]) ? 0 : 1;
            return;
        }
        if (args.Length == 3 && args[0] == "--rain-texture-self-test") { NativeRainWeather.Test(args[1],args[2]); return; }
        if (args.Length == 3 && args[0] == "--password-limit-self-test") { NativePasswordLimit.Test(args[1],args[2]); return; }
        Console.OutputEncoding = new System.Text.UTF8Encoding(false);
        ApplicationConfiguration.Initialize();
        if(args.Length==2 && args[0]=="--contracts-native-proof") { File.WriteAllBytes(args[1],NativeContractsUi.Build(0x21000000,0x1400000));return; }
        if(args.Length==2 && args[0]=="--native-flame-proof")
        {
            File.WriteAllText(args[1],System.Text.Json.JsonSerializer.Serialize(new {
                allocation=0x21000000u,silver=0x1400000u,
                size=NativeFlameStream.Plan.Size,silverPointer=NativeFlameStream.Plan.SilverPointer,
                code=Convert.ToHexStringLower(NativeFlameStream.Build(0x21000000,0x1400000)),
                hooks=NativeFlameStream.Plan.Hooks }));return;
        }
        if (args.Length == 2 && args[0] == "--launch-required-self-test") { LaunchRequiredSelfTest.Run(args[1]).GetAwaiter().GetResult(); return; }
        if (args.Length == 3 && args[0] == "--launch-verify-check")
        {
            try
            {
                var proof=LaunchVerification.Verify(args[1],CancellationToken.None).GetAwaiter().GetResult();
                File.WriteAllText(args[2],System.Text.Json.JsonSerializer.Serialize(new {passed=true,preface=Convert.ToHexStringLower(proof.Preface(31001,"russian"))}));
            }
            catch(Exception e) { File.WriteAllText(args[2],System.Text.Json.JsonSerializer.Serialize(new {passed=false,error=e.ToString()}));Environment.ExitCode=1; }
            return;
        }
        if (args.Length == 2 && args[0] == "--client-icon-self-test") { GameWindowIconSelfTest.Run(args[1]); return; }
        if (args.Length == 3 && args[0] == "--client-icon")
        {
            GameWindowIcon.AttachExisting(int.Parse(args[1]), args[2]).GetAwaiter().GetResult(); return;
        }
        if(args.Length==2 && args[0]=="--native-turn-proof")
        {
            uint allocation=0x21000000;
            File.WriteAllText(args[1],System.Text.Json.JsonSerializer.Serialize(new {
                allocation,code=Convert.ToHexStringLower(NativeBattleTurn.Build(allocation)),
                hook=Convert.ToHexStringLower(NativeDoorGrid.Jump(0x71da3d,allocation)[..5]) }));return;
        }
        if(args.Length==2 && args[0]=="--native-door-proof")
        {
            uint allocation=0x20000000;
            File.WriteAllText(args[1],System.Text.Json.JsonSerializer.Serialize(new {
                allocation,code=Convert.ToHexStringLower(NativeDoorGrid.Build(allocation)),
                fog_entry=NativeDoorGrid.Plan.FogEntry,door_entry=NativeDoorGrid.Plan.DoorEntry,
                recon_marker_hook=Convert.ToHexStringLower(NativeDoorGrid.ReconMarkerJump(0x400000)),
                fog_hook=Convert.ToHexStringLower(NativeDoorGrid.Jump(0x6e40a4,allocation+(uint)NativeDoorGrid.Plan.FogEntry)),
                door_hook=Convert.ToHexStringLower(NativeDoorGrid.Jump(0x72dc90,allocation+(uint)NativeDoorGrid.Plan.DoorEntry)) }));return;
        }
        if (args.Length > 0 && args[0].EndsWith("self-test", StringComparison.Ordinal)) L.Language="russian";
        if (args.Length == 2 && args[0] == "--steam-self-test") { SteamDistributionSelfTest.Run(args[1]).GetAwaiter().GetResult(); return; }
        if (args.Length == 3 && args[0] == "--steam-package-check" && SteamDistribution.Enabled)
        {
            using var offline = new Updater(args[1], SteamDistribution.ContentHandler());
            var release = offline.Fetch(CancellationToken.None).GetAwaiter().GetResult();
            offline.Apply(release, new Progress<UpdateProgress>(), CancellationToken.None).GetAwaiter().GetResult();
            File.WriteAllText(args[2], System.Text.Json.JsonSerializer.Serialize(new { passed=true, release.Version, files=release.Files.Length, remote_updates=false })); return;
        }
        if (args.Length == 3 && args[0] == "--native-english-self-test") { NativeEnglishSelfTest.Run(args[1],args[2]); return; }
        if (args.Length == 2 && args[0] == "--language-self-test") { GameLanguageSelfTest.Run(args[1]); return; }
        if (args.Length == 2 && args[0] == "--website-self-test") { GameWebsiteSelfTest.Run(args[1]); return; }
        if (args.Length == 3 && args[0] == "--language-qa-apply") { GameLanguage.Apply(args[1],args[2]); L.Language=args[2]; return; }
        if (args.Length == 3 && args[0] == "--preview-language") { GameLanguage.Validate(args[1]); L.Language=args[1]; args=["--preview",args[2]]; }
        if (args.Length == 2 && args[0] == "--launcher-update-helper") { LauncherUpdate.RunHelper(args[1]).GetAwaiter().GetResult(); return; }
        if (args.Length == 2 && args[0] == "--launcher-update-self-test") { LauncherUpdateSelfTest.Run(args[1]).GetAwaiter().GetResult(); return; }
        if (args.Length == 2 && args[0] == "--install-location-self-test") { InstallLocationSelfTest.Run(args[1]); return; }
        if (args.Length == 2 && args[0] == "--game-path-self-test") { GamePathSelfTest.Run(args[1]); return; }
        if (args.Length == 2 && args[0] == "--tls-endpoint-probe")
        {
            try
            {
                var bridge = new TlsBridge(TlsEndpoint.Production);
                try
                {
                    bridge.ValidateEndpoints(CancellationToken.None).GetAwaiter().GetResult();
                    File.WriteAllText(args[1], System.Text.Json.JsonSerializer.Serialize(new { passed = true, hostname = TlsEndpoint.Production.Host, connect_host = TlsEndpoint.Production.ConnectHost,
                        ports = new[] { TlsEndpoint.Production.LoginPort, TlsEndpoint.Production.SessionPort }, revocation = "Online", default_system_validation = true, native_bytes_sent = 0 }));
                }
                finally { bridge.DisposeAsync().AsTask().GetAwaiter().GetResult(); }
            }
            catch (Exception error) { File.WriteAllText(args[1], System.Text.Json.JsonSerializer.Serialize(new { passed = false, error = error.ToString(), native_bytes_sent = 0 })); Environment.ExitCode = 1; }
            return;
        }
        if (args.Length == 3 && args[0] is "--tls-native-probe" or "--probe-tls-route" or "--native-turn-self-test")
        {
            try
            {
                var verification=LaunchVerification.Verify(args[1],CancellationToken.None).GetAwaiter().GetResult();
                var bridge = new TlsBridge(TlsEndpoint.Production,verification:verification);
                using var lifetime = new GameLifetime();
                try
                {
                    uint pid = GameStarter.Start(args[1], true, new GameLaunchProfile(bridge.LoginPort, bridge.SessionPort, true,verification), lifetime.Assign);
                    File.WriteAllText(args[2], System.Text.Json.JsonSerializer.Serialize(new { passed = true, pid,
                        login_port = bridge.LoginPort, session_port = bridge.SessionPort, network_requests = 0,
                        scope = "Owned hidden native loader and TLS route only; no auth, relay or hosted validation",startup_events=GameStarter.LastTrace }));
                }
                finally { bridge.DisposeAsync().AsTask().GetAwaiter().GetResult(); }
            }
            catch (Exception ex) { File.WriteAllText(args[2], System.Text.Json.JsonSerializer.Serialize(new { passed = false, error = ex.ToString(),startup_events=GameStarter.LastTrace })); Environment.ExitCode = 1; }
            return;
        }
        if (args.Length == 2 && args[0] == "--tls-self-test") { TlsSelfTest.Run(args[1]).GetAwaiter().GetResult(); return; }
        if (args.Length == 2 && args[0] == "--tls-bootstrap-proof")
        {
            uint allocation = 0x20000000, orange = 0x40000000;
            byte[] thunk = NativeTlsRoute.BuildThunk(allocation + 2048, allocation + 2304, 0, 41001, 41002);
            File.WriteAllText(args[1], System.Text.Json.JsonSerializer.Serialize(new {
                allocation, orange_base = orange, unpacked_base = 0x30000000u, original_target = 0x30001670u,
                virtual_protect = 0x50000000u, flush_instruction_cache = 0x50001000u, exit_process = 0x50002000u,
                bootstrap_hex = Convert.ToHexStringLower(NativeTlsRoute.BuildBootstrap(allocation, orange, 0x50000000, 0x50001000, 0x50002000, thunk.Length)),
                initial_thunk_hex = Convert.ToHexStringLower(thunk), thunk_address = allocation + 2048,
                host_address = allocation + 2304, state_address = allocation + 4096,
                export_address = orange + 0x118f, loader_store = 0x718ff4u, loader_continue = 0x718ff9u,
                login_port = 41001, session_port = 41002,
                original_signature_hex = "a0f5509b0c84c074238b0df0509b0c85c974198b4424108b54240c508b44240c528b54240c5052e8"
            })); return;
        }
        if (args.Length == 4 && args[0] == "--tls-game" && args[3] is "qa" or "player")
        {
            SynchronizationContext.SetSynchronizationContext(null);
            SecureGame.RunChild(args[1], args[2], args[3] == "qa").GetAwaiter().GetResult(); return;
        }
        if (args.Length == 3 && args[0] == "--tls-qa-start")
        {
            try
            {
                var status = SecureGame.Start(args[1], true).GetAwaiter().GetResult();
                using var output = new FileStream(args[2], FileMode.CreateNew, FileAccess.Write, FileShare.Read);
                System.Text.Json.JsonSerializer.Serialize(output, status);
            }
            catch (Exception ex) { Environment.ExitCode = 1; Console.Error.WriteLine(SecureGame.Describe(ex)); }
            return;
        }
        if (args.Length == 2 && args[0] == "--tls-route-proof")
        {
            File.WriteAllText(args[1], System.Text.Json.JsonSerializer.Serialize(new {
                thunk_address = 0x20000000u, host_address = 0x20000080u, original_target = 0x30001670u,
                login_port = 41001, session_port = 41002,
                thunk_hex = Convert.ToHexStringLower(NativeTlsRoute.BuildThunk(0x20000000, 0x20000080, 0x30001670, 41001, 41002)),
                loopback_hex = Convert.ToHexStringLower(System.Text.Encoding.ASCII.GetBytes("127.0.0.1\0"))
            })); return;
        }
        if (args.Length == 3 && args[0] == "--probe-start")
        {
            try { File.WriteAllText(args[2],"PASS: ORANGE loaded, pid="+GameStarter.Start(args[1],true)); }
            catch(Exception ex) { File.WriteAllText(args[2],ex.ToString()); Environment.ExitCode=1; }
            return;
        }
        if (args.Length == 2 && args[0] == "--self-test") { SelfTest.Run(args[1]).GetAwaiter().GetResult(); return; }
        if (args.Length == 2 && args[0] == "--archive-self-test") { ArchiveSelfTest.Run(args[1]).GetAwaiter().GetResult(); return; }
        if (args.Length == 2 && args[0] == "--cache-self-test") { CacheSelfTest.Run(args[1]).GetAwaiter().GetResult(); return; }
        if (args.Length == 3 && args[0] is "--client-update-check" or "--client-full-check")
        {
            using var updater = new Updater(args[1]);
            var release = updater.Fetch(CancellationToken.None).GetAwaiter().GetResult();
            updater.Apply(release, new Progress<UpdateProgress>(), CancellationToken.None,args[0]=="--client-full-check").GetAwaiter().GetResult();
            File.WriteAllText(args[2], System.Text.Json.JsonSerializer.Serialize(new { passed=true, release.Version, files=release.Files.Length, archive=release.Archive,
                updater.ManifestBytesReceived,updater.ManifestNotModified,updater.Metrics })); return;
        }
        if (args.Length == 2 && args[0] == "--validate-manifest")
        {
            Updater.Validate(System.Text.Json.JsonSerializer.Deserialize<Release>(File.ReadAllText(args[1]), Updater.Json)!); return;
        }
        using var mutex = new Mutex(true, SteamDistribution.Enabled ? "TIO.Steam.Launcher" : "TIO.PrivateServer.Launcher", out bool first);
        if (!first) { MessageBox.Show(L.Text("Лаунчер уже открыт.")); return; }
        if (!SteamDistribution.Enabled) LauncherUpdate.CleanCompletedDownloads();
        using var form = new LauncherForm(args.Length == 2 && args[0] == "--setup-qa" ? new InstallLocation(args[1]) : null);
        if (args.Length == 2 && args[0] == "--preview")
        {
            form.Show(); Application.DoEvents();
            using var bitmap = new Bitmap(form.Width, form.Height);
            form.DrawToBitmap(bitmap, new Rectangle(Point.Empty, form.Size)); bitmap.Save(args[1]); return;
        }
        form.Shown += async (_, _) => await form.UpdateClient();
        Application.Run(form);
    }
}

sealed class LauncherForm : Form
{
    static readonly Color Gold = Color.FromArgb(221, 200, 112);
    readonly Image backdrop;
    readonly Label state = new(), folder = new(), version = new();
    readonly RichTextBox news = new();
    readonly ProgressBar progress = new();
    readonly Button check = new(), play = new(), choose = new(), cancel = new();
    readonly ComboBox language = new();
    readonly InstallLocation installLocation;
    string gameRoot;
    bool hasGameRoot;
    string? folderReason;
    CancellationTokenSource? operation;
    bool verified;
    bool launching;
    Release? latestRelease;
    public LauncherForm(InstallLocation? location = null)
    {
        installLocation = location ?? new InstallLocation();
        Text = L.Text("Total Influence · Лаунчер ") + LauncherUpdate.CurrentVersion; ClientSize = new Size(860, 570);
        using (var stream = typeof(LauncherForm).Assembly.GetManifestResourceStream("TioLauncher.icon.ico")!)
            Icon = new Icon(stream);
        DoubleBuffered = true;
        using (var stream = typeof(LauncherForm).Assembly.GetManifestResourceStream("TioLauncher.wasteland.png")!)
        using (var source = Image.FromStream(stream)) backdrop = new Bitmap(source);
        MinimumSize = MaximumSize = Size; MaximizeBox = false; StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(17, 19, 17); ForeColor = Color.FromArgb(222, 223, 206);
        Font = new Font("Segoe UI", 10); AutoScaleMode = AutoScaleMode.Dpi;
        if (SteamDistribution.Enabled) { gameRoot=SteamDistribution.GameRoot; hasGameRoot=true; }
        else hasGameRoot = installLocation.TryLoadSaved(out gameRoot, out folderReason);
        AddLabel("TOTAL INFLUENCE", 28, 22, 740, 55, new Font("Georgia", 30, FontStyle.Bold), Gold);
        AddLabel(L.Text("ЧАСТНЫЙ СЕРВЕР   /   МУЛЬТИПЛЕЕР"), 31, 85, 480, 24, new Font("Segoe UI", 10, FontStyle.Bold), Gold);
        var register = Button(L.Text("РЕГИСТРАЦИЯ"), 645, 82, 180, 34);
        register.Click += (_, _) => Process.Start(new ProcessStartInfo("https://ti-reborn.com/" + (L.Language == "english" ? "en" : "ru") + "/register") { UseShellExecute = true });
        AddLabel(L.Text("НОВОСТИ СЕРВЕРА"), 30, 142, 460, 25, new Font("Segoe UI", 12, FontStyle.Bold), Gold);
        news.SetBounds(30, 181, 475, 182); news.ReadOnly = true; news.BorderStyle = BorderStyle.None;
        news.BackColor = Color.FromArgb(24, 29, 24); news.ForeColor = ForeColor; news.Font = new Font("Segoe UI", 11);
        news.Text = L.Text("Арена ждёт соперника\n\n«Выживание» подбирает другого игрока. Войдите под своим аккаунтом и выберите отряд в казарме.\n\nНажмите «Проверить файлы», чтобы получить новости и актуальную версию клиента с сервера.");
        Controls.Add(news);
        AddLabel(L.Text("ЯЗЫК ИГРЫ / GAME LANGUAGE"), 545, 145, 280, 25, new Font("Segoe UI", 10, FontStyle.Bold), Gold);
        language.SetBounds(545, 181, 280, 32); language.DropDownStyle = ComboBoxStyle.DropDownList;
        language.Items.AddRange(["Русский", "English"]); language.SelectedIndex = L.Language == "english" ? 1 : 0;
        Controls.Add(language);
        language.SelectedIndexChanged += (_, _) =>
        {
            string selected = language.SelectedIndex == 1 ? "english" : "russian";
            try { GameLanguage.Save(selected); L.Language = selected; L.Refresh(this); if (latestRelease != null) news.Text = L.Language == "english" ? latestRelease.NewsEn ?? latestRelease.News : latestRelease.News; }
            catch (Exception ex) { state.Text = ex.Message; }
        };
        version.SetBounds(30, 375, 570, 25); version.Text = L.Text("Версия клиента ещё не проверена"); Controls.Add(version);
        folder.SetBounds(30, 408, 610, 25); folder.AutoEllipsis = true; folder.Text = hasGameRoot ? gameRoot : L.Text("Выберите папку для установки игры"); Controls.Add(folder);
        Style(choose, L.Text("ПАПКА ИГРЫ"), 650, 400, 175, 35);
        choose.Click += (_, _) =>
        {
            if (!ChooseFolder()) return;
            state.Text = L.Text("Папка выбрана. Нажмите «Проверить файлы», чтобы установить или проверить клиент.");
        };
        state.SetBounds(30, 447, 795, 25); state.AutoEllipsis = true; state.Text = L.Text("Готов к проверке обновлений"); Controls.Add(state);
        version.BackColor = folder.BackColor = state.BackColor = Color.Transparent;
        progress.SetBounds(30, 480, 795, 8); Controls.Add(progress);
        Style(check, L.Text("ПРОВЕРИТЬ ФАЙЛЫ"), 30, 509, 235, 38);
        Style(cancel, L.Text("ОТМЕНА"), 280, 509, 130, 38); cancel.Enabled = false;
        Style(play, L.Text("ИГРАТЬ"), 600, 505, 225, 46); play.BackColor = Color.FromArgb(72, 78, 38); play.Enabled = false;
        if (SteamDistribution.Enabled) { choose.Visible=false; choose.Enabled=false; }
        check.Click += async (_, _) => await UpdateClient(fullVerification:true);
        cancel.Click += (_, _) => operation?.Cancel();
        play.Click += async (_, _) =>
        {
            if (!verified || Updater.GameRunning()) return;
            launching=true;
            play.Enabled = check.Enabled = choose.Enabled = language.Enabled = false;
            bool started = false;
            try { state.Text=L.Text("Проверка обновлений перед запуском игры…"); await SecureGame.Start(gameRoot); started = true; }
            catch (Exception ex) { state.Text = L.Text("Не удалось запустить игру: ") + ex.Message; }
            finally { launching=false; play.Enabled=verified; check.Enabled=language.Enabled=true; choose.Enabled=!SteamDistribution.Enabled; }
            if (started) Close();
        };
        FormClosing += (_, e) => { if (launching) { e.Cancel=true; return; } if (operation != null) { operation.Cancel(); e.Cancel = true; state.Text = L.Text("Отмена загрузки. Дождитесь завершения операции."); } };
        L.Refresh(this);
    }
    void AddLabel(string text, int x, int y, int w, int h, Font font, Color color)
        => Controls.Add(new Label { Text = text, Bounds = new Rectangle(x,y,w,h), Font = font, ForeColor = color, BackColor = Color.Transparent });
    Button Button(string text, int x, int y, int w, int h) { var b = new Button(); Style(b,text,x,y,w,h); return b; }
    void Style(Button b, string text, int x, int y, int w, int h)
    {
        b.Text = text; b.SetBounds(x,y,w,h); b.FlatStyle = FlatStyle.Flat; b.FlatAppearance.BorderColor = Color.FromArgb(105,108,73);
        b.BackColor = Color.FromArgb(27, 32, 25);
        b.FlatAppearance.MouseOverBackColor = Color.FromArgb(58, 65, 40);
        b.ForeColor = Gold; b.Font = new Font("Segoe UI", 10, FontStyle.Bold); b.Cursor = Cursors.Hand; Controls.Add(b);
    }
    public async Task UpdateClient(bool fullVerification=false)
    {
        if (operation is not null || launching) return;
        operation = new CancellationTokenSource(); check.Enabled = choose.Enabled = play.Enabled = false; cancel.Enabled = true; verified = false;
        bool restart = false;
        bool checkingLauncher = !SteamDistribution.Enabled;
        state.Text = L.Text("Проверка версии лаунчера ") + LauncherUpdate.CurrentVersion + "…";
        try
        {
            var report = new Progress<UpdateProgress>(p => { state.Text = p.Message; progress.Value = Math.Clamp(p.Percent,0,100); });
            if (!SteamDistribution.Enabled)
            {
                using var launcherUpdate = new LauncherUpdate();
                var launcherRelease = await launcherUpdate.Fetch(operation.Token);
                if (LauncherUpdate.IsNewer(launcherRelease, LauncherUpdate.CurrentVersion))
                {
                    state.Text = L.Text("Доступен лаунчер ") + launcherRelease.Version + L.Text(". Загрузка обновления…");
                    await launcherUpdate.HandOff(launcherRelease, report, operation.Token);
                    state.Text = L.Text("Обновление загружено. Перезапуск лаунчера…");
                    restart = true;
                    return;
                }
            }
            checkingLauncher = false;
            operation.Token.ThrowIfCancellationRequested();
            cancel.Enabled = false;
            if (!hasGameRoot && !ChooseFolder())
            {
                state.Text = L.Text("Установка отменена. Выберите папку игры, чтобы продолжить.");
                return;
            }
            cancel.Enabled = true;
            state.Text = SteamDistribution.Enabled ? SteamDistribution.Message("Проверка установленного клиента Steam…", "Checking the installed Steam client…") : L.Text("Подключение к серверу обновлений клиента…");
            using var updater = new Updater(gameRoot, SteamDistribution.Enabled ? SteamDistribution.ContentHandler() : null);
            var release = await updater.Fetch(operation.Token);
            latestRelease = release; news.Text = L.Language == "english" ? release.NewsEn ?? release.News : release.News; version.Text = L.Text("Доступна версия ") + release.Version;
            await Task.Run(() => updater.Apply(release, report, operation.Token,fullVerification));
            verified = true; version.Text = L.Text("Установлена версия ") + release.Version;
        }
        catch (OperationCanceledException) { state.Text = checkingLauncher ? L.Text("Проверка или загрузка лаунчера прервана. Повторите проверку.") : L.Text("Загрузка отменена. Проверенные файлы сохранены для повторной попытки."); }
        catch (UnauthorizedAccessException) { state.Text = checkingLauncher ? L.Text("Нет прав для обновления лаунчера. Переместите его EXE в доступную для записи папку.") : L.Text("Нет прав на папку. Выберите папку вне Program Files."); }
        catch (HttpRequestException) { state.Text = checkingLauncher ? L.Text("Не удалось проверить версию лаунчера. Проверьте интернет и повторите проверку.") : L.Text("Обновления клиента недоступны. Проверьте интернет или повторите позже."); }
        catch (Exception ex) { state.Text = ex.Message; }
        finally
        {
            operation.Dispose(); operation = null; check.Enabled = !restart; choose.Enabled = !restart && !SteamDistribution.Enabled; cancel.Enabled = false; play.Enabled = verified && !restart;
            if (restart) Close();
        }
    }
    bool ChooseFolder()
    {
        if (!installLocation.TryChooseFolder(this, gameRoot, out string selected, folderReason)) return false;
        gameRoot = selected; hasGameRoot = true; folderReason = null; folder.Text = gameRoot;
        verified = false; play.Enabled = false; progress.Value = 0;
        return true;
    }
    protected override void OnPaintBackground(PaintEventArgs e)
    {
        var bounds = ClientRectangle;
        e.Graphics.DrawImage(backdrop, bounds);
        using var shade = new LinearGradientBrush(bounds, Color.FromArgb(85, 8, 14, 10), Color.FromArgb(12, 8, 14, 10), 0f);
        e.Graphics.FillRectangle(shade, bounds);
        float scale = DeviceDpi / 96f;
        using var footer = new LinearGradientBrush(new RectangleF(0, 365*scale, bounds.Width, bounds.Height-365*scale),
            Color.FromArgb(170, 12, 18, 13), Color.FromArgb(245, 12, 18, 13), 90f);
        e.Graphics.FillRectangle(footer, 0, 365*scale, bounds.Width, bounds.Height-365*scale);
        using var card = new SolidBrush(Color.FromArgb(24, 29, 24));
        e.Graphics.FillRectangle(card, 20*scale, 137*scale, 495*scale, 234*scale);
    }
    protected override void Dispose(bool disposing)
    {
        if (disposing) backdrop.Dispose();
        base.Dispose(disposing);
    }
    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        using var pen = new Pen(Color.FromArgb(83,85,57));
        e.Graphics.DrawLine(pen,30,125,825,125); e.Graphics.DrawLine(pen,30,393,825,393);
    }
}
