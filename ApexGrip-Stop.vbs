' Stop the grip backend without a console window.
Set sh = CreateObject("WScript.Shell")
base = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\") - 1)
sh.CurrentDirectory = base
sh.Run """" & base & "\ApexGrip-Stop.cmd""", 0, False
