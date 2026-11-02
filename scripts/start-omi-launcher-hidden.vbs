Option Explicit

Dim fso
Dim shell
Dim scriptDir
Dim launcherScript
Dim powershellPath
Dim command

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
launcherScript = fso.BuildPath(scriptDir, "omi-launcher.ps1")
powershellPath = shell.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"

If Not fso.FileExists(launcherScript) Then
    MsgBox "Missing launcher script: " & launcherScript, vbCritical, "Open Market Intelligence"
    WScript.Quit 1
End If

If Not fso.FileExists(powershellPath) Then
    MsgBox "Missing PowerShell executable: " & powershellPath, vbCritical, "Open Market Intelligence"
    WScript.Quit 1
End If

command = """" & powershellPath & """ -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File """ & launcherScript & """"
If WScript.Arguments.Named.Exists("UpdateRequestId") Then
    Dim requestId, uuidPattern
    requestId = WScript.Arguments.Named.Item("UpdateRequestId")
    Set uuidPattern = New RegExp
    uuidPattern.Pattern = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    If Not uuidPattern.Test(requestId) Then WScript.Quit 2
    command = command & " -UpdateRequestId " & requestId
End If
shell.Run command, 0, False
