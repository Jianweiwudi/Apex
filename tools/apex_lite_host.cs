using System;
using System.Drawing;
using System.Reflection;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

// File properties (Details tab / Explorer tooltip). Without these the exe shows as a blank
// "Apex" with no version, which looks unfinished next to everything else.
[assembly: AssemblyTitle("Apex Lite")]
[assembly: AssemblyProduct("Apex Lite")]
[assembly: AssemblyDescription("ACC 儀表 HUD：單圈、四輪胎況、賽段與加油、啟動片頭")]
[assembly: AssemblyCompany("Apex")]
[assembly: AssemblyCopyright("Apex Licence 2.0")]
[assembly: AssemblyVersion("2.0.1.0")]
[assembly: AssemblyFileVersion("2.0.1.0")]

namespace ApexLite
{
    // The lite host is deliberately tiny: a window, a WebView2, and nothing else. The original
    // Apex host also carried the routines that located and rewrote the game's tyre curves,
    // torque curves, fuel and pressure values; this edition talks to the game only through the
    // page's read-only HTTP calls to 127.0.0.1:7798, so none of that code exists here.
    internal static class Program
    {
        // The previous host was system-DPI aware (awareness=1). Without this the process is DPI
        // unaware, Windows renders the window at 96 dpi and stretches the bitmap: on a 125 %
        // screen the whole panel - WebView included - comes out soft and slightly the wrong size.
        [DllImport("user32.dll")]
        private static extern bool SetProcessDPIAware();

        [STAThread]
        private static void Main()
        {
            try { SetProcessDPIAware(); } catch { }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new Shell());
        }
    }

    internal sealed class Shell : Form
    {
        private readonly WebView2 view = new WebView2();

        public Shell()
        {
            Text = "Apex Lite";
            StartPosition = FormStartPosition.CenterScreen;
            // Size against the working area instead of a hard-coded pixel size: with DPI
            // awareness on, 1400x900 on a 2560x1440 desktop at 125 % is a smallish window,
            // and a fixed size would look wrong on every other screen as well.
            var wa = Screen.PrimaryScreen.WorkingArea;
            MinimumSize = new Size((int)(wa.Width * 0.52), (int)(wa.Height * 0.55));
            Size = new Size((int)(wa.Width * 0.86), (int)(wa.Height * 0.88));
            BackColor = Color.FromArgb(11, 13, 16);
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

            view.Dock = DockStyle.Fill;
            Controls.Add(view);
            Load += async (s, e) => await Boot();
        }

        private async System.Threading.Tasks.Task Boot()
        {
            try
            {
                // Keep Chromium's profile out of the app folder: %LOCALAPPDATA%\Apex Lite\WebView2
                // matches the state folder the rest of this edition uses, and it keeps the
                // portable folder free of a few hundred cache files.
                var dataDir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Apex Lite", "WebView2");
                Directory.CreateDirectory(dataDir);
                // The page is loaded from file:// and reads legal/*.json with fetch(); Chromium
                // blocks one file origin from reading another unless this switch is set, which is
                // why the terms dialog fell back to its built-in summary.
                var opts = new CoreWebView2EnvironmentOptions
                {
                    AdditionalBrowserArguments = "--allow-file-access-from-files"
                };
                var env = await CoreWebView2Environment.CreateAsync(null, dataDir, opts);
                await view.EnsureCoreWebView2Async(env);
            }
            catch (Exception ex)
            {
                MessageBox.Show("WebView2 runtime is missing.\n\n" + ex.Message,
                                "Apex Lite", MessageBoxButtons.OK, MessageBoxIcon.Error);
                Close();
                return;
            }

            var core = view.CoreWebView2;
            core.Settings.AreDevToolsEnabled = false;
            core.Settings.AreDefaultContextMenusEnabled = false;
            core.Settings.IsStatusBarEnabled = false;
            core.Settings.AreBrowserAcceleratorKeysEnabled = false;
            core.Settings.IsZoomControlEnabled = false;

            // The page is a local file; the backend is http on loopback. Anything the page posts
            // is ignored on purpose - this host has no commands to run.
            core.WebMessageReceived += (s, e) => { };

            var page = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "ui", "index.html");
            if (!File.Exists(page))
            {
                MessageBox.Show("ui\\index.html not found next to Apex.exe.",
                                "Apex Lite", MessageBoxButtons.OK, MessageBoxIcon.Error);
                Close();
                return;
            }
            core.Navigate(new Uri(page).AbsoluteUri);

            // probe: APEX_PROBE=1 dumps whether the legal JSON is readable, then leaves a file
            if (Environment.GetEnvironmentVariable("APEX_PROBE") == "1")
            {
                core.NavigationCompleted += async (s, e) =>
                {
                    // ExecuteScriptAsync does not await promises, so ask synchronously
                    var js = "(function(){var out=[];try{var x=new XMLHttpRequest();" +
                             "x.open('GET','legal/zh-Hant.json',false);x.send();" +
                             "out.push('legal='+x.responseText.length);}catch(e){out.push('legal=ERR');}" +
                             "var p=document.querySelector('.pill');" +
                             "out.push('pill='+(p?p.textContent.trim():'none'));" +
                             "var c=document.getElementById('car');" +
                             "out.push('car='+(c?c.textContent.trim():'none'));" +
                             "return out.join(' | ');})()";
                    var res = await core.ExecuteScriptAsync(js);
                    File.WriteAllText(Path.Combine(Path.GetTempPath(), "apex_probe.txt"), res);
                };
            }
        }
    }
}
