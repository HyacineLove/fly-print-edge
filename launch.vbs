' launch.vbs — Silent launcher for FlyPrint Edge Kiosk
' Starts the server in background, waits for readiness, opens the user page.
'
' Usage:
'   wscript.exe launch.vbs              opens user page after service ready
'   wscript.exe launch.vbs /admin        opens admin page after service ready
'   wscript.exe launch.vbs /silent       starts service only, no browser
'
' The EXE path is resolved relative to this script's directory.

Option Explicit

Const PORT = 7860
Const STARTUP_TIMEOUT_SEC = 30
Const POLL_INTERVAL_MS = 800

Dim WshShell, FSO
Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

' Determine install directory (same directory as this script)
Dim InstallDir
InstallDir = FSO.GetParentFolderName(WScript.ScriptFullName)

Dim ExePath
ExePath = InstallDir & "\flyprint-edge.exe"

If Not FSO.FileExists(ExePath) Then
    MsgBox "Could not find flyprint-edge.exe in:" & vbCrLf & InstallDir, 16, "FlyPrint Edge"
    WScript.Quit 1
End If

' Parse /admin or /silent flags
Dim OpenMode, FirstArg
OpenMode = "user"  ' default: open user page after ready
FirstArg = ""
If WScript.Arguments.Unnamed.Count > 0 Then
    FirstArg = WScript.Arguments.Unnamed(0)
End If
If WScript.Arguments.Named.Exists("admin") Or InStr(1, FirstArg, "/admin", 1) > 0 Then
    OpenMode = "admin"
End If
If WScript.Arguments.Named.Exists("silent") Or InStr(1, FirstArg, "/silent", 1) > 0 Then
    OpenMode = "silent"
End If

' --- Start the service and wait for it to become ready ---
Dim StatusUrl, StartTime, Ready, Http
StatusUrl = "http://127.0.0.1:" & PORT & "/api/status"
Ready = False

Function IsServerReady()
    Dim H
    IsServerReady = False
    On Error Resume Next
    Err.Clear
    Set H = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    If Err.Number <> 0 Then Exit Function
    H.SetTimeouts 2000, 2000, 2000, 2000
    H.Open "GET", StatusUrl, False
    H.Send
    If H.Status = 200 And InStr(1, H.ResponseText, "online", 1) > 0 Then
        IsServerReady = True
    End If
    On Error GoTo 0
End Function

' Always start the service (do not pre-check — MSXML may return false positives)
WshShell.CurrentDirectory = InstallDir
WshShell.Run """" & ExePath & """", 0, False
StartTime = Timer

Do While Timer - StartTime < STARTUP_TIMEOUT_SEC
    WScript.Sleep POLL_INTERVAL_MS
    If IsServerReady() Then
        Ready = True
        Exit Do
    End If
Loop

If Not Ready Then
    MsgBox "FlyPrint Edge did not start within " & STARTUP_TIMEOUT_SEC & " seconds." & vbCrLf & _
           "Check logs in: " & InstallDir & "\logs", 48, "FlyPrint Edge"
    WScript.Quit 2
End If

' --- Open browser ---
Dim Url
Select Case OpenMode
    Case "admin"
        Url = "http://127.0.0.1:" & PORT & "/admin"
    Case "user"
        Url = "http://127.0.0.1:" & PORT
    Case Else
        Url = ""
End Select

If Url <> "" Then
    WshShell.Run Url
End If

WScript.Quit 0
