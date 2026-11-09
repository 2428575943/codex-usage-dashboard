using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;
[assembly: AssemblyTitle("Codex Quota Guard")]
[assembly: AssemblyCompany("Codex Quota Guard community project")]
[assembly: AssemblyVersion("0.1.3.0")]
[assembly: AssemblyFileVersion("0.1.3.0")]
class Guard : Form {
    static readonly string Root=Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
    static readonly string State=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"CodexQuotaGuard");
    static readonly string Identity=WindowsIdentity.GetCurrent().User.Value;
    static readonly string MutexName="Local\\CodexQuotaGuard-"+Identity;
    static readonly string EventName="Local\\CodexQuotaGuardStop-"+Identity;
    static readonly string ShowName="Local\\CodexQuotaGuardShow-"+Identity;
    const string RunName="Codex Quota Guard";
    static readonly JavaScriptSerializer Json=new JavaScriptSerializer();
    static string Q(string x){if(x.Contains("\""))throw new ArgumentException();return "\""+x+"\"";}
    static Dictionary<string,object> Read(string p){try{return Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(p));}catch{return new Dictionary<string,object>();}}
    static string S(Dictionary<string,object> x,string k){return x.ContainsKey(k)?Convert.ToString(x[k]):"";}
    static int Worker(string extra){
        var p=new ProcessStartInfo(Path.Combine(Root,"python","python.exe"),"-X utf8 "+Q(Path.Combine(Root,"runtime.py"))+" --state "+Q(State)+" "+extra){UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=Root,RedirectStandardOutput=true,RedirectStandardError=true};
        using(var proc=Process.Start(p)){
            var output=proc.StandardOutput.ReadToEndAsync();var error=proc.StandardError.ReadToEndAsync();
            if(!proc.WaitForExit(115000)){try{proc.Kill();}catch{} throw new TimeoutException("额度检查超时");}
            Task.WaitAll(output,error);return proc.ExitCode;
        }
    }
    static void Stop(){
        try{using(var e=EventWaitHandle.OpenExisting(EventName)){e.Set();}}catch(WaitHandleCannotBeOpenedException){}
        using(var m=new Mutex(false,MutexName)){
            try{if(m.WaitOne(125000))m.ReleaseMutex();else throw new TimeoutException("请先关闭额度守护窗口");}catch(AbandonedMutexException){m.ReleaseMutex();}
        }
    }
    static void Startup(bool enable){using(var k=Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run",true)){
        if(enable)k.SetValue(RunName,Q(Path.Combine(Root,"CodexQuotaGuard.exe"))+" --background");else k.DeleteValue(RunName,false);
    }}
    readonly TextBox Info=new TextBox{Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Vertical,BorderStyle=BorderStyle.None,Dock=DockStyle.Fill,BackColor=Color.FromArgb(25,31,43),ForeColor=Color.FromArgb(225,233,246),Font=new Font("Microsoft YaHei UI",11),Margin=new Padding(20)};
    readonly NotifyIcon Tray=new NotifyIcon();
    readonly System.Windows.Forms.Timer Tick=new System.Windows.Forms.Timer{Interval=30000};
    readonly EventWaitHandle StopEvent;
    readonly EventWaitHandle ShowEvent;
    readonly System.Windows.Forms.Timer Signals=new System.Windows.Forms.Timer{Interval=1000};
    bool busy,exiting;bool background;
    public Guard(bool background){
        this.background=background;Text="Codex 额度守护 · 预览版 0.1.3";ClientSize=new Size(710,540);MinimumSize=new Size(640,480);StartPosition=FormStartPosition.CenterScreen;
        BackColor=Info.BackColor;Padding=new Padding(24);Controls.Add(Info);
        var buttons=new FlowLayoutPanel{Dock=DockStyle.Bottom,Height=52,Padding=new Padding(0,10,0,0)};
        var refresh=new Button{Text="刷新状态",Width=110,Height=30,BackColor=Color.FromArgb(223,232,245),ForeColor=Color.Black,UseVisualStyleBackColor=false,FlatStyle=FlatStyle.Flat};refresh.Click+=async(s,e)=>await Cycle();buttons.Controls.Add(refresh);
        var restore=new Button{Text="停用并恢复",Width=120,Height=30,BackColor=Color.FromArgb(223,232,245),ForeColor=Color.Black,UseVisualStyleBackColor=false,FlatStyle=FlatStyle.Flat};restore.Click+=async(s,e)=>{
            if(busy)return;busy=true;Tick.Stop();
            try{int code=await Task.Run(()=>Worker("--restore"));if(code!=0)throw new Exception("恢复失败，请查看本地状态文件。");Startup(false);Info.Text="已停用并恢复本软件管理的配置。\r\n\r\n请完整退出并重新打开 Codex。\r\n备份保留在：\r\n"+State;}
            catch(Exception ex){Info.Text=ex.Message;}finally{busy=false;}
        };buttons.Controls.Add(restore);
        Controls.Add(buttons);
        var menu=new ContextMenuStrip();menu.Items.Add("打开状态",null,(s,e)=>{Show();WindowState=FormWindowState.Normal;Activate();});menu.Items.Add("退出守护（保留配置）",null,(s,e)=>{exiting=true;Close();});
        Tray.Icon=SystemIcons.Information;Tray.Text="Codex 额度守护";Tray.ContextMenuStrip=menu;Tray.Visible=true;Tray.DoubleClick+=(s,e)=>{Show();Activate();};
        StopEvent=new EventWaitHandle(false,EventResetMode.ManualReset,EventName);
        ShowEvent=new EventWaitHandle(false,EventResetMode.AutoReset,ShowName);
        Signals.Tick+=(s,e)=>{if(StopEvent.WaitOne(0)&&!busy){exiting=true;Close();return;}if(ShowEvent.WaitOne(0)){Show();WindowState=FormWindowState.Normal;Activate();}};
        Tick.Tick+=async(s,e)=>{if(!StopEvent.WaitOne(0))await Cycle();};
        Shown+=async(s,e)=>{Signals.Start();if(background)Hide();await Cycle();Tick.Start();};
        FormClosing+=(s,e)=>{if(!exiting){e.Cancel=true;Hide();}else if(busy){e.Cancel=true;StopEvent.Set();}else{Tick.Stop();Signals.Stop();Tray.Visible=false;Tray.Dispose();StopEvent.Dispose();ShowEvent.Dispose();}};
    }
    void Display(){
        var s=Read(Path.Combine(State,"status.json"));
        string quota=S(s,"remaining_percent"),tier=S(s,"tier");
        string models="";if(s.ContainsKey("visible_models")){foreach(var x in (System.Collections.IEnumerable)s["visible_models"])models+="  • "+x+"\r\n";}
        string error=S(s,"error");
        string update=S(s,"update");
        switch(update){case "deferred":update="暂缓，次日自动重试";break;case "up_to_date":update="已是最新版本";break;case "ready":update="已验证，正在准备安装";break;case "not_configured":update="更新源尚未接入";break;case "cooldown":update="等待下次每日检查";break;}
        Info.Text="CODEX 额度守护\r\n\r\n"+(quota==""?"5 小时剩余：未知（保守档）":"5 小时剩余："+quota+"%")+"\r\n\r\n当前配置允许：\r\n"+models+
        "\r\n思考强度：轻度 / 中 / 高\r\n额度查询：每 3 分钟；软件更新：最多每天一次\r\n\r\n"+
        (error!=""?"兼容检查失败，未继续改写配置："+error+"\r\n\r\n":"")+
        "本版控制启动时的模型菜单及默认值。\r\n配置变更后，请完整退出并重新打开 Codex。\r\n已有聊天的模型与手动覆盖不受强制拦截。\r\n\r\n更新状态："+update+"\r\n配置与恢复备份："+State;
    }
    async Task Cycle(){
        if(busy)return;busy=true;
        try{await Task.Run(()=>Worker(""));if(IsDisposed)return;Display();ApplyUpdate();}
        catch(Exception e){if(!IsDisposed)Info.Text="守护检查暂缓："+e.Message+"\r\n下次会自动重试。";}
        finally{busy=false;}
    }
    void ApplyUpdate(){
        var pending=Read(Path.Combine(State,"pending-update.json"));if(pending.Count==0)return;
        var trust=Read(Path.Combine(Root,"update-trust.json"));
        if(Convert.ToInt32(S(pending,"sequence"))<=Convert.ToInt32(S(trust,"sequence"))){File.Delete(Path.Combine(State,"pending-update.json"));return;}
        // Derive the path locally. Packaged Windows apps may give Python and .NET
        // different aliases for the same LocalAppData directory.
        int sequence=Convert.ToInt32(S(pending,"sequence"));
        if(sequence<1)return;
        string file=Path.Combine(State,"updates","setup-"+sequence+".exe");
        if(!File.Exists(file))return;
        string attempt=Path.Combine(State,"update-apply-after.txt");long after;
        if(File.Exists(attempt)&&Int64.TryParse(File.ReadAllText(attempt),out after)&&DateTime.UtcNow.Ticks<after)return;
        using(var sha=SHA256.Create())using(var stream=File.OpenRead(file)){
            string hash=BitConverter.ToString(sha.ComputeHash(stream)).Replace("-","").ToLowerInvariant();if(hash!=S(pending,"sha256"))return;
        }
        // Verified standard installer performs the replacement and restarts the tray.
        File.WriteAllText(attempt,DateTime.UtcNow.AddHours(24).Ticks.ToString());
        Process.Start(new ProcessStartInfo(file,"/VERYSILENT /SUPPRESSMSGBOXES /NORESTART"){UseShellExecute=false,CreateNoWindow=true});exiting=true;Close();
    }
    [STAThread]static int Main(string[] args){
        try{
            Directory.CreateDirectory(State);
            if(Array.IndexOf(args,"--self-test")>=0)return 0;
            if(Array.IndexOf(args,"--stop")>=0){Stop();return 0;}
            if(Array.IndexOf(args,"--uninstall")>=0){Stop();int code=Worker("--restore");if(code==0)Startup(false);return code;}
            if(Array.IndexOf(args,"--once")>=0)return Worker("");
            using(var mutex=new Mutex(false,MutexName)){
                bool acquired=false;try{acquired=mutex.WaitOne(0);}catch(AbandonedMutexException){acquired=true;}
                if(!acquired){if(Array.IndexOf(args,"--background")<0)try{using(var show=EventWaitHandle.OpenExisting(ShowName)){show.Set();}}catch(WaitHandleCannotBeOpenedException){}return 0;}
                try{Startup(true);Application.EnableVisualStyles();Application.Run(new Guard(Array.IndexOf(args,"--background")>=0));}finally{mutex.ReleaseMutex();}
            }
            return 0;
        }catch(Exception ex){MessageBox.Show(ex.Message,"Codex 额度守护");return 1;}
    }
}
