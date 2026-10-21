' Grip backend without a console window (used by the launcher and the watchdog).
Set sh = CreateObject("WScript.Shell")
base = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\") - 1)
sh.CurrentDirectory = base
sh.Run """" & base & "\ApexGrip.cmd""", 0, False
