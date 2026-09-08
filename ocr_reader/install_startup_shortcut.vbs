' Creates a shortcut in the current user's Startup folder that silently
' launches start_reader.vbs at login - no Task Scheduler, no admin rights,
' no elevation prompt (schtasks' onlogon trigger can require elevated
' rights in some environments; a Startup-folder shortcut never does,
' since it's just a normal per-user folder). To undo, delete the shortcut
' this creates - see uninstall.bat.
Option Explicit
Dim shell, fso, scriptDir, startupFolder, shortcut

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
startupFolder = shell.SpecialFolders("Startup")

Set shortcut = shell.CreateShortcut(startupFolder & "\MKX Accessibility Reader.lnk")
shortcut.TargetPath = "wscript.exe"
shortcut.Arguments = """" & scriptDir & "\start_reader.vbs"""
shortcut.WorkingDirectory = scriptDir
shortcut.Description = "Starts the Mortal Kombat X accessibility reader quietly in the background"
shortcut.Save
