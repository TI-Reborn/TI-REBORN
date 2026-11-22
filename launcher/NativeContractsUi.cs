using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace TioLauncher;

// Uses the game's own TGUIWindow, TGUIButton, TGUILabel and TGUIEdit classes.
// Rendering, focus, dragging, hit-testing and close behavior remain native.
internal sealed class NativeContractsUi : IDisposable
{
    static uint allocation;
    static readonly JsonDocument plan=JsonDocument.Parse(ReadPlan());
    static byte[] ReadPlan(){using var stream=typeof(NativeContractsUi).Assembly.GetManifestResourceStream("TioLauncher.native-contracts-windows.json")!;using var output=new MemoryStream();stream.CopyTo(output);return output.ToArray();}
    [DllImport("kernel32",SetLastError=true)] static extern IntPtr VirtualAllocEx(IntPtr process,IntPtr address,nuint size,uint type,uint protection);
    [DllImport("kernel32",SetLastError=true)] static extern bool VirtualProtectEx(IntPtr process,IntPtr address,nuint size,uint protection,out uint old);
    [DllImport("kernel32",SetLastError=true)] static extern bool FlushInstructionCache(IntPtr process,IntPtr address,nuint size);
    [DllImport("kernel32",SetLastError=true)] static extern bool WriteProcessMemory(IntPtr process,IntPtr address,byte[] bytes,nuint size,out nuint written);
    [DllImport("kernel32",SetLastError=true)] static extern bool ReadProcessMemory(IntPtr process,IntPtr address,byte[] bytes,nuint size,out nuint read);
    internal static byte[] Build(uint address,uint silver)
    {
        byte[] output=new byte[plan.RootElement.GetProperty("size").GetInt32()];
        foreach(var block in plan.RootElement.GetProperty("blocks").EnumerateArray())
        {
            Convert.FromHexString(block.GetProperty("hex").GetString()!).CopyTo(output,block.GetProperty("offset").GetInt32());
            foreach(var fix in block.GetProperty("relocations").EnumerateArray())
            {
                int at=fix.GetProperty("at").GetInt32();uint value=unchecked((fix.GetProperty("kind").GetString()=="allocation"?address:silver)+fix.GetProperty("offset").GetUInt32());
                if(fix.GetProperty("relative").GetBoolean())value=unchecked(value-address-(uint)at-4);
                BitConverter.GetBytes(value).CopyTo(output,at);
            }
        }
        return output;
    }
    static void Write(IntPtr process,uint address,byte[] bytes)
    {
        if(!WriteProcessMemory(process,new IntPtr(address),bytes,(nuint)bytes.Length,out var count) || count!=(nuint)bytes.Length)
            throw new IOException("Cannot update native contract controls.");
    }
    internal static void Install(IntPtr process,uint silver,string image)
    {
        if(!SilverRegions.Matches(File.ReadAllBytes(image),"contracts"))
            throw new InvalidDataException("Unsupported native contracts window image.");
        int size=plan.RootElement.GetProperty("size").GetInt32();var memory=VirtualAllocEx(process,IntPtr.Zero,(nuint)size,0x3000,0x04);
        if(memory==IntPtr.Zero || memory.ToInt64()>uint.MaxValue-size)throw new IOException("Cannot allocate native contracts window.");
        allocation=checked((uint)memory.ToInt64());Write(process,allocation,Build(allocation,silver));
        if(!VirtualProtectEx(process,memory,0x8000,0x20,out _) || !FlushInstructionCache(process,memory,0x8000))
            throw new IOException("Cannot initialize native contracts code.");
        foreach(var hook in plan.RootElement.GetProperty("hooks").EnumerateArray())
        {
            uint source=silver+hook.GetProperty("rva").GetUInt32(),target=allocation+hook.GetProperty("target").GetUInt32();
            byte[] before=Convert.FromHexString(hook.GetProperty("before").GetString()!);
            byte[] after=Enumerable.Repeat((byte)0x90,before.Length).ToArray();after[0]=hook.GetProperty("opcode").GetByte();
            BitConverter.GetBytes(unchecked(target-source-5)).CopyTo(after,1);
            NativeTlsRoute.GuardedPatch(process,source,before,after);
        }
    }
    readonly TlsBridge bridge;
    readonly Process game;
    readonly CancellationTokenSource stopping=new();
    readonly Task worker;
    JsonElement state;
    int view,template,member,petPage,invitation;
    readonly HashSet<int> selected=new();
    HashSet<long> seenInvites=new();
    string status="";
    bool dirty,initialized;
    double lastResult;
    DateTime nextPoll=DateTime.MinValue;
    NativeContractsUi(TlsBridge bridge,Process game){this.bridge=bridge;this.game=game;worker=Task.Run(Run);}
    internal static IDisposable Attach(TlsBridge bridge,Process game)=>allocation==0?new Empty():new NativeContractsUi(bridge,game);
    sealed class Empty:IDisposable{public void Dispose(){}}
    uint Header=>allocation+0x8000;
    static uint Record(int index)=>allocation+0x8100+(uint)index*544;
    byte[] Read(uint address,int size)
    {
        byte[] data=new byte[size];
        if(!ReadProcessMemory(game.Handle,new IntPtr(address),data,(nuint)size,out var read) || read!=(nuint)size)throw new IOException("Native contract window unavailable.");
        return data;
    }
    uint U32(uint address)=>BitConverter.ToUInt32(Read(address,4));
    void Put(uint address,uint value)=>Write(game.Handle,address,BitConverter.GetBytes(value));
    string T(string ru,string en)=>L.Language=="english"?en:ru;
    static bool Has(JsonElement value,string key)=>value.ValueKind==JsonValueKind.Object && value.TryGetProperty(key,out var x) && x.ValueKind!=JsonValueKind.Null;
    static bool B(JsonElement value,string key)=>Has(value,key) && value.GetProperty(key).ValueKind==JsonValueKind.True;
    static string S(JsonElement value,string key)=>Has(value,key)?value.GetProperty(key).ToString():"";
    JsonElement[] Array(string key)=>state.GetProperty(key).EnumerateArray().ToArray();
    JsonElement[] Members()=>Has(state,"party")?state.GetProperty("party").GetProperty("members").EnumerateArray().ToArray():[];
    string Edit()
    {
        uint control=U32(Record(31));if(control==0)return "";uint text=U32(control+0x58);if(text==0)return "";
        uint length=U32(text-4);if(length>32)throw new InvalidDataException("Character name too long.");
        return Encoding.Unicode.GetString(Read(text,checked((int)length*2))).Trim();
    }
    void Open(){Put(Header+8,1);}
    async Task Run()
    {
        try
        {
            while(!stopping.IsCancellationRequested && !game.HasExited)
            {
                uint nativeEvent=U32(Header+4);
                if(nativeEvent!=0)
                {
                    Put(Header+4,0);
                    try{await Click(checked((int)nativeEvent-1));}
                    catch(Exception e) when(e is IOException or System.Net.Sockets.SocketException or System.Security.Authentication.AuthenticationException or JsonException || e is OperationCanceledException && !stopping.IsCancellationRequested)
                    {status=T("Нет ответа. Состояние будет обновлено.","No reply. The state will refresh.");nextPoll=DateTime.MinValue;}
                    Render();
                }
                if(DateTime.UtcNow>=nextPoll)
                {
                    nextPoll=DateTime.UtcNow.AddSeconds(3);
                    try
                    {
                        var reply=await bridge.Contracts(new{action="state"},stopping.Token);
                        if(B(reply,"ok"))Apply(reply.GetProperty("state"));
                        else{state=default;status=S(reply,"error");Render();}
                    }
                    catch(Exception e) when(e is IOException or System.Net.Sockets.SocketException or System.Security.Authentication.AuthenticationException or JsonException || e is OperationCanceledException && !stopping.IsCancellationRequested)
                    {state=default;status=T("Связь со штабом прервана. Подключение…","HQ connection interrupted. Reconnecting…");nextPoll=DateTime.UtcNow.AddSeconds(8);Render();}
                }
                await Task.Delay(100,stopping.Token);
            }
        }
        catch(OperationCanceledException)when(stopping.IsCancellationRequested){}
        catch(Exception e)when(e is IOException or InvalidOperationException or System.ComponentModel.Win32Exception){}
    }
    async Task Act(string action,object? value=null)
    {
        var body=new Dictionary<string,object>{{"action",action},{"request_id",Guid.NewGuid().ToString("N")}};
        if(value is not null)body["value"]=value;
        var reply=await bridge.Contracts(body,stopping.Token);
        if(!B(reply,"ok")){status=S(reply,"error");return;}
        if(action=="select")dirty=false;
        status=T("Группа обновлена.","Party updated.");Apply(reply.GetProperty("state"));
        if(action is "depart" or "start")Put(Header+8,2);
        nextPoll=DateTime.UtcNow.AddSeconds(2);
    }
    async Task Click(int index)
    {
        if(index is 0 or 1 or 3 or 4 or 57){view=index is 1 or 4?2:index==57?1:0;template=0;Open();return;}
        if(index==56){Put(Header+8,2);return;}
        if(state.ValueKind!=JsonValueKind.Object)return;
        var templates=Templates(state,view);var members=Members();var pets=Array("pets").Where(p=>B(p,"available")).ToArray();var invites=Array("invitations");
        if(index is >=5 and <=7){template=Math.Min(index-5,templates.Length-1);return;}
        if(index is >=27 and <=30){member=index-27;return;}
        if(index is >=35 and <=40)
        {
            int row=petPage*6+index-35;if(row>=pets.Length)return;int id=pets[row].GetProperty("id").GetInt32();
            if(!selected.Remove(id)){if(selected.Count>=2){status=T("Можно выбрать не более двух бойцов.","Select at most two fighters.");return;}selected.Add(id);}dirty=true;return;
        }
        if(index==41){petPage=Math.Max(0,petPage-1);return;}if(index==42){petPage=Math.Min((pets.Length-1)/6,petPage+1);return;}
        if(index==52){invitation=invites.Length==0?0:(invitation+1)%invites.Length;return;}
        switch(index)
        {
            case 22:await Act("take",S(templates[template],"id"));if(Has(state,"contract"))view=2;break;
            case 23:await Act("depart");break;case 24:await Act("start");break;case 25:await Act("cancel");break;
            case 32:await Act("invite",Edit());break;
            case 33:case 34:if(member<members.Length)await Act(index==33?"leader":"kick",S(members[member],"name"));break;
            case 43:await Act("select",selected.Order().ToArray());break;
            case 44:if(dirty){status=T("Сначала сохраните выбранных бойцов.","Save the selected fighters first.");break;}await Act("ready");break;
            case 45:await Act("unready");break;case 46:await Act("create");break;case 47:await Act("leave");break;case 48:await Act("disband");break;
            case 50:case 51:if(invitation<invites.Length)await Act(index==50?"accept":"decline",invites[invitation].GetProperty("id").GetInt64());break;
        }
    }
    void Apply(JsonElement value)
    {
        string previous=Has(state,"contract")?S(state.GetProperty("contract"),"state"):"";
        state=value.Clone();
        if(Has(state,"contract") && S(state.GetProperty("contract"),"state")=="arrived" && previous!="arrived")
        {view=state.GetProperty("contract").GetProperty("party_size")[1].GetInt32()==1?0:1;status=T("Цель достигнута. Лидер может начать бой.","Target reached. The leader may start battle.");Open();}
        if(Has(state,"contract") && S(state.GetProperty("contract"),"state")=="active" && previous!="active")Put(Header+8,2);
        if(!dirty){selected.Clear();foreach(var id in Array("selected"))selected.Add(id.GetInt32());}
        var invites=Array("invitations").Select(i=>i.GetProperty("id").GetInt64()).ToHashSet();
        if(invites.Except(seenInvites).Any()){view=2;Open();}seenInvites=invites;
        if(Has(state,"result"))
        {
            double stamp=state.GetProperty("result").GetProperty("finished_at").GetDouble();
            if(stamp>lastResult){if(initialized){view=0;Open();}lastResult=stamp;}
        }
        if(!initialized)status=T("Выберите одиночный контракт или соберите группу.","Choose a solo contract or gather a party.");
        initialized=true;Render();
    }
    string Phase(string value)=>value switch{"accepted"=>T("ожидание готовности","waiting for readiness"),"travelling"=>T("в пути","travelling"),"arrived"=>T("у цели","at target"),"active" or "battle"=>T("в бою","in battle"),"city"=>T("в городе","in city"),"at_target"=>T("у цели","at target"),_=>value};
    internal static JsonElement[] Templates(JsonElement value,int tab)=>value.GetProperty("catalog").EnumerateArray()
        .Where(t=>(t.TryGetProperty("party_size",out var size)?size[1].GetInt32()==1:false)==(tab!=1)).ToArray();
    void Render()
    {
        if(U32(Header)!=0)return;
        int count=plan.RootElement.GetProperty("count").GetInt32();
        var rows=new (string Text,bool Visible,bool Enabled)[count];
        void Set(int i,string text,bool visible=true,bool enabled=true)=>rows[i]=(text,visible,enabled);
        bool valid=state.ValueKind==JsonValueKind.Object;
        Set(0,T("Контракты","Contracts"));Set(1,T("Группа","Party"));Set(2,T("Контракты - Полевой штаб","Contracts - Field HQ"));
        Set(3,(view==0?"> ":"")+T("Одиночные","Solo"));Set(57,(view==1?"> ":"")+T("Групповые","Group"));Set(4,(view==2?"> ":"")+T("Моя группа","My party"));
        Set(53,status);Set(56,T("Закрыть","Close"));
        if(valid)
        {
            bool board=view!=2;var permissions=state.GetProperty("permissions");bool P(string name)=>B(permissions,name);
            var templates=Templates(state,view);template=Math.Clamp(template,0,Math.Max(0,templates.Length-1));
            if(templates.Length==0){Set(26,T("Одиночные контракты требуют обновления сервера.","Solo contracts require a server update."));}
            var chosen=templates.Length>0?templates[template]:Array("catalog")[0];
            for(int i=0;i<Math.Min(3,templates.Length);i++)Set(5+i,(i==template?"> ":"")+S(templates[i],"name"),board);
            var reward=chosen.GetProperty("reward");var levels=chosen.GetProperty("levels");
            string[] lines=[S(chosen,"name"),"",S(chosen,"objective"),"",view==0?T("Игрок: 1. Бойцов: 1-2.","Players: 1. Fighters: 1-2."):T("Игроков: 2-4. Бойцов на игрока: 1-2.","Players: 2-4. Fighters per player: 1-2."),
                $"{T("Уровни","Levels")}: {levels[0]}-{levels[1]}   {T("Противников","Enemies")}: {S(chosen,"enemies")}","",
                T("Награда каждому участнику за победу:","Victory reward per player:"),$"{S(reward,"credits")} {T("кредитов","credits")}  /  {S(reward,"experience")} {T("опыта выбранным бойцам","XP shared by selected fighters")}","",
                T("Примите задание, затем подтвердите готовность.","Accept a contract, then confirm readiness."),T("Лидер отправляет группу к цели и начинает бой.","The leader travels to the target and starts battle."),"",
                Has(state,"contract")?S(state.GetProperty("contract"),"name")+": "+Phase(S(state.GetProperty("contract"),"state")):T("Активного контракта нет.","No active contract.")];
            for(int i=0;i<14;i++)Set(8+i,lines[i],board);
            int partyCount=Members().Length;
            bool fits=view==0?partyCount<=1:partyCount>=2;
            Set(22,T("Принять задание","Accept contract"),board,P("take")&&fits&&templates.Length>0);Set(23,T("Отправиться к цели","Travel to target"),board,P("depart"));
            Set(24,T("Начать бой","Start battle"),board,P("start"));Set(25,T("Отменить задание","Cancel contract"),board,P("cancel"));
            var members=Members();member=Math.Clamp(member,0,Math.Max(0,members.Length-1));
            Set(26,Has(state,"party")?T("Группа: ","Party: ")+Phase(S(state.GetProperty("party"),"state")):T("Создайте группу или примите приглашение.","Create a party or accept an invitation."),!board);
            for(int i=0;i<members.Length && i<4;i++)
            {
                var m=members[i];Set(27+i,(i==member?"> ":"")+S(m,"name")+(B(m,"self")?T(" (вы)"," (you)"):"")+"  |  "+
                    (B(m,"leader")?T("Лидер","Leader"):T("Участник","Member"))+"  |  "+(!B(m,"online")?T("Не в сети","Offline"):B(m,"ready")?T("Готов","Ready"):T("Не готов","Not ready"))+"  |  "+
                    T("Бойцы: ","Fighters: ")+string.Join(",",m.GetProperty("selected").EnumerateArray().Select(v=>v.ToString())),!board);
            }
            Set(31,"",!board,P("invite"));Set(32,T("Пригласить по имени","Invite by name"),!board,P("invite"));
            bool other=members.Length>member && !B(members[member],"self");
            Set(33,T("Передать лидерство","Make leader"),!board,P("invite")&&other);Set(34,T("Исключить участника","Remove member"),!board,P("invite")&&other);
            var pets=Array("pets").Where(p=>B(p,"available")).ToArray();petPage=Math.Clamp(petPage,0,Math.Max(0,(pets.Length-1)/6));
            for(int i=0;i<6 && petPage*6+i<pets.Length;i++)
            {
                var pet=pets[petPage*6+i];bool picked=selected.Contains(pet.GetProperty("id").GetInt32());
                Set(35+i,(picked?"[+] ":"[ ] ")+S(pet,"name")+$"  {T("ур.","lvl")} {S(pet,"level")}  HP {S(pet,"hp")}",!board,P("edit"));
            }
            Set(41,"<",!board,petPage>0);Set(42,">",!board,(petPage+1)*6<pets.Length);
            Set(43,T("Сохранить бойцов","Save fighters"),!board,P("edit")&&selected.Count is 1 or 2);Set(44,T("Готов","Ready"),!board,P("ready"));Set(45,T("Не готов","Not ready"),!board,P("ready"));
            Set(46,T("Создать группу","Create party"),!board,P("create"));Set(47,T("Выйти из группы","Leave party"),!board,P("edit"));Set(48,T("Распустить группу","Disband party"),!board,P("invite"));
            var invites=Array("invitations");invitation=Math.Clamp(invitation,0,Math.Max(0,invites.Length-1));
            string inviteText=T("Нет приглашений.","No invitations.");
            if(invites.Length>0)
            {
                var invite=invites[invitation];int seconds=Math.Max(0,(int)(invite.GetProperty("expires_at").GetDouble()-state.GetProperty("server_time").GetDouble()));
                inviteText=T("Приглашает ","Invited by ")+S(invite,"leader")+$"  ({seconds} {T("сек.","sec")})";
            }
            Set(49,inviteText,!board);Set(50,T("Принять","Accept"),!board&&invites.Length>0);Set(51,T("Отклонить","Decline"),!board&&invites.Length>0);Set(52,T("Другое приглашение","Next invitation"),!board&&invites.Length>1);
            Set(55,T("Мои бойцы: ","My fighters: ")+selected.Count+"/2"+(dirty?T(" - выбор не сохранён"," - unsaved selection"):""),!board);
            if(Has(state,"result"))
            {
                var result=state.GetProperty("result");string text=S(result,"name")+": "+(S(result,"outcome")=="victory"?T("Победа","Victory"):T("Задание не выполнено","Mission failed"));
                if(B(result,"paid"))text+=T(" - награда начислена"," - reward paid");Set(54,text);
            }
        }
        else Set(26,T("Войдите персонажем в игру.","Enter the game with your character."),true);
        Put(Header,2);
        try
        {
            for(int i=0;i<count;i++)
            {
                byte[] bytes=new byte[540];BitConverter.GetBytes(rows[i].Visible?1:0).CopyTo(bytes,0);BitConverter.GetBytes(rows[i].Enabled?1:0).CopyTo(bytes,4);
                string text=rows[i].Text??"";if(text.Length>254)text=text[..254];byte[] caption=Encoding.Unicode.GetBytes(text);
                BitConverter.GetBytes(caption.Length).CopyTo(bytes,8);caption.CopyTo(bytes,12);Write(game.Handle,Record(i)+4,bytes);
            }
        }
        finally{Put(Header,1);}
    }
    public void Dispose(){stopping.Cancel();_ = worker.ContinueWith(_=>stopping.Dispose(),TaskScheduler.Default);}
}
