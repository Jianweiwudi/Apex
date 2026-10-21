' Apex launcher without a console window.
' wscript.exe runs this with no console at all, so nothing flashes when the panel starts.
Set sh = CreateObject("WScript.Shell")
base = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\") - 1)
sh.CurrentDirectory = base
sh.Run "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & base & "\ApexLauncher.ps1""", 0, False
