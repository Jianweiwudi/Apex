using System;
using System.Drawing;
using System.IO;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace ApexLite
{
    // The lite host is deliberately tiny: a window, a WebView2, and nothing else. The original
    // Apex host also carried the routines that located and rewrote the game's tyre curves,
    // torque curves, fuel and pressure values; this edition talks to the game only through the
    // page's read-only HTTP calls to 127.0.0.1:7798, so none of that code exists here.
    internal static class Program
    {
        [STAThread]
        private static void Main()
        {
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
            MinimumSize = new Size(980, 640);
            Size = new Size(1400, 900);
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
                var env = await CoreWebView2Environment.CreateAsync(null, dataDir, null);
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
        }
    }
}
