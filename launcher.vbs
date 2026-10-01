Option Explicit
Dim shell, files, appDir, pythonPath
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
appDir = files.GetParentFolderName(WScript.ScriptFullName)
pythonPath = appDir & "\.venv\Scripts\pythonw.exe"
If Not files.FileExists(pythonPath) Then
    MsgBox "Run install.ps1 in the FilterGuardian folder first, then reopen this launcher.", vbInformation, "FilterGuardian installation"
    WScript.Quit 1
End If
shell.CurrentDirectory = appDir
shell.Run """" & pythonPath & """ """ & appDir & "\main.py""", 0, False
