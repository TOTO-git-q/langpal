# Installs the branded LangPal desktop launcher (ASCII only, no CJK in this file).
#
# Result: %LOCALAPPDATA%\Programs\LangPal\LangPal.exe  +  Start Menu shortcut "LangPal".
#
# Why it lives OUTSIDE the repo: the first version built LangPal.exe inside
# desktop\node_modules, and a later workspace cleanup deleted node_modules - the
# taskbar pin silently broke. %LOCALAPPDATA%\Programs is the standard per-user app
# location; cleanups of rebuildable folders (node_modules, .venv) never touch it.
#
# The install is self-contained: the Electron runtime is copied there, electron.exe
# becomes LangPal.exe with our icon/version strings, and resources\app holds its own
# copy of main.js / preload.js / langpal.config.json. Re-run this script after
# editing any of those files (close LangPal first).
#
# The Start Menu shortcut carries System.AppUserModel.ID = com.langpal.desktop, the
# same id main.js sets via app.setAppUserModelId. Without a shortcut carrying that
# id, Windows cannot relaunch a pinned window that uses an explicit id, and the
# pinned icon and the running window show up as two separate taskbar buttons.

$ErrorActionPreference = "Stop"
$desktop = $PSScriptRoot
$src     = Join-Path $desktop "node_modules\electron\dist"
$target  = Join-Path $env:LOCALAPPDATA "Programs\LangPal"
$exe     = Join-Path $target "LangPal.exe"
$ico     = Join-Path $desktop "LangPal.ico"
$aumid   = "com.langpal.desktop"
$lnk     = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\LangPal.lnk"

if (-not (Test-Path (Join-Path $src "electron.exe"))) {
  throw "electron.exe not found in $src. Run 'npm install' in $desktop first."
}
if (-not (Test-Path $ico)) { throw "LangPal.ico missing in $desktop." }

$running = Get-CimInstance Win32_Process -Filter "Name='LangPal.exe'" |
  Where-Object { $_.ExecutablePath -eq $exe }
if ($running) { throw "LangPal is running from $target. Close it first, then re-run." }

# 1. Electron runtime -> target (mirror, so a re-run gives a clean copy)
New-Item -ItemType Directory -Force -Path $target | Out-Null
robocopy $src $target /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with code $LASTEXITCODE" }

# 2. electron.exe -> LangPal.exe with our icon and version strings
Move-Item (Join-Path $target "electron.exe") $exe -Force
$rcedit = Get-ChildItem (Join-Path $desktop "node_modules\rcedit") -Recurse -Filter "rcedit*.exe" |
  Where-Object { $_.Name -like "*x64*" } | Select-Object -First 1
if (-not $rcedit) { throw "rcedit not installed. Run: npm install (in $desktop)" }
& $rcedit.FullName $exe --set-icon $ico `
  --set-version-string "FileDescription" "LangPal" `
  --set-version-string "ProductName" "LangPal" `
  --set-version-string "CompanyName" "LangPal" `
  --set-version-string "InternalName" "LangPal" `
  --set-version-string "OriginalFilename" "LangPal.exe" `
  --set-file-version "0.1.0" --set-product-version "0.1.0"
if ($LASTEXITCODE -ne 0) { throw "rcedit failed" }
Copy-Item $ico (Join-Path $target "LangPal.ico") -Force

# 3. resources\app = self-contained shell (Electron loads it when given no arguments).
#    default_app.asar is removed so a broken app folder can never fall back to the
#    stock Electron welcome window.
$res = Join-Path $target "resources"
Remove-Item (Join-Path $res "default_app.asar") -Force -ErrorAction SilentlyContinue
$appDir = Join-Path $res "app"
New-Item -ItemType Directory -Force -Path $appDir | Out-Null
foreach ($f in @("main.js", "preload.js", "langpal.config.json")) {
  Copy-Item (Join-Path $desktop $f) (Join-Path $appDir $f) -Force
}
# Same "name" as desktop\package.json so userData (window size/zoom) stays the same.
Set-Content -Path (Join-Path $appDir "package.json") -Encoding ascii -Value @'
{
  "name": "langpal-desktop",
  "version": "0.1.0",
  "main": "main.js"
}
'@

# 4. Start Menu shortcut, then stamp the AppUserModelID onto it
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($lnk)
$s.TargetPath = $exe
$s.WorkingDirectory = $target
$s.IconLocation = "$exe,0"
$s.Description = "LangPal"
$s.Save()

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class LnkAumid {
    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    public struct PropertyKey { public Guid fmtid; public uint pid; }

    [StructLayout(LayoutKind.Explicit)]
    public struct PropVariant {
        [FieldOffset(0)] public ushort vt;
        [FieldOffset(8)] public IntPtr pwszVal;
    }

    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IPropertyStore {
        [PreserveSig] int GetCount(out uint cProps);
        [PreserveSig] int GetAt(uint iProp, out PropertyKey pkey);
        [PreserveSig] int GetValue(ref PropertyKey key, out PropVariant pv);
        [PreserveSig] int SetValue(ref PropertyKey key, ref PropVariant pv);
        [PreserveSig] int Commit();
    }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    static extern void SHGetPropertyStoreFromParsingName(
        string pszPath, IntPtr pbc, int flags, ref Guid riid, out IPropertyStore ppv);

    public static void Set(string lnkPath, string aumid) {
        Guid iid = typeof(IPropertyStore).GUID;
        IPropertyStore store;
        SHGetPropertyStoreFromParsingName(lnkPath, IntPtr.Zero, 2 /* GPS_READWRITE */, ref iid, out store);
        var key = new PropertyKey {
            fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5  // System.AppUserModel.ID
        };
        var pv = new PropVariant { vt = 31 /* VT_LPWSTR */, pwszVal = Marshal.StringToCoTaskMemUni(aumid) };
        try {
            int hr = store.SetValue(ref key, ref pv);
            if (hr != 0) Marshal.ThrowExceptionForHR(hr);
            hr = store.Commit();
            if (hr != 0) Marshal.ThrowExceptionForHR(hr);
        } finally {
            Marshal.FreeCoTaskMem(pv.pwszVal);
            Marshal.ReleaseComObject(store);
        }
    }
}
'@
[LnkAumid]::Set($lnk, $aumid)

Write-Host "Installed: $exe"
Write-Host "Start Menu shortcut: $lnk (AppUserModelID $aumid)"
Write-Host "Pin: right-click the running LangPal on the taskbar -> Pin to taskbar."
