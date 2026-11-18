' LangPal desktop launcher - no console window (ASCII only, no CJK in this file).
'
' Runs the installed LangPal.exe (built by desktop\make-launcher.ps1 into
' %LOCALAPPDATA%\Programs\LangPal). The Start Menu entry "LangPal" does the same;
' this file is only for double-clicking from the project folder.
'
' To pin to the taskbar, pin the running LangPal window (right-click its taskbar
' button -> Pin to taskbar), not this .vbs - a pinned .vbs shows the Windows
' Script Host icon.
'
' Backend address comes from langpal.config.json (backendUrl) next to main.js.

Option Explicit
Dim sh, fso, exePath

Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

exePath = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\LangPal\LangPal.exe"

If fso.FileExists(exePath) Then
  sh.Run """" & exePath & """", 0, False
Else
  MsgBox "LangPal is not installed yet." & vbCrLf & vbCrLf & _
         "In the desktop folder run once:" & vbCrLf & _
         "  npm install" & vbCrLf & _
         "  powershell -ExecutionPolicy Bypass -File make-launcher.ps1" & vbCrLf & vbCrLf & _
         "Looked for:" & vbCrLf & exePath, vbExclamation, "LangPal"
End If
