' Launched from Steam's launch options (see PROGRESS.md) so the
' accessibility reader starts automatically whenever the game is launched.
' Ported from the MK Legacy Kollection accessibility project - see that
' project's start_reader.vbs for why duplicate-instance protection lives in
' main.py's PID lock file rather than a pre-check here.
Option Explicit
Dim shell, fso, scriptDir, batPath

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = scriptDir & "\run_reader.bat"

If fso.FileExists(batPath) Then
    shell.Run """" & batPath & """", 0, False
End If
