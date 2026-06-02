; Inno Setup script for FlyPrint Edge Kiosk
;
; Prerequisites:
;   1. Run PyInstaller first: pyinstaller flyprint-edge.spec --clean --noconfirm
;   2. Copy config.example.json to dist/flyprint-edge/ (handled by build_installer.py)
;
; Build:
;   iscc installer.iss
;   Output: dist\flyprint-edge-setup-{version}.exe
;
; The installer is per-user (no admin required) — installs to %LOCALAPPDATA%\Programs\FlyPrint Edge.

#define MyAppName "FlyPrint Edge"
#define MyAppNameEn "FlyPrint Edge Kiosk"
#define MyAppPublisher "FlyPrint"
#define MyAppURL "http://127.0.0.1:7860"
#define MyAppExeName "flyprint-edge.exe"
; MyAppVersion is set via /DMyAppVersion=X.Y.Z from build_installer.py
; Provide a safe default if not overridden
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

[Setup]
AppId={{B8F4A3D2-7E5C-4A1B-9D6F-2C8E0A7B5F3D}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={userpf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename=flyprint-edge-setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UninstallDisplayName={#MyAppNameEn}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
english.BeveledLabel={#MyAppNameEn}

[Tasks]
Name: "desktopicon_user"; Description: "{cm:CreateDesktopIcon} — {#MyAppName}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "desktopicon_admin"; Description: "Create desktop shortcut — {#MyAppName} Admin"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "autostart"; Description: "Start {#MyAppName} automatically when Windows starts"; GroupDescription: "Startup options:"; Flags: unchecked

[Files]
; Main application and dependencies
Source: "dist\flyprint-edge\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\flyprint-edge\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

; Launcher scripts
Source: "launch.vbs"; DestDir: "{app}"; Flags: ignoreversion

; Config template — install as both the example reference and as initial config (on fresh install)
Source: "dist\flyprint-edge\_internal\config.example.json"; DestDir: "{app}"; DestName: "config.example.json"; Flags: ignoreversion
Source: "dist\flyprint-edge\_internal\config.example.json"; DestDir: "{app}"; DestName: "config.json"; Flags: ignoreversion onlyifdoesntexist

; Empty directories for runtime
[Dirs]
Name: "{app}\logs"
Name: "{app}\temp"

[Icons]
; Desktop shortcuts
Name: "{userdesktop}\{#MyAppName}"; Filename: "wscript.exe"; Parameters: """{app}\launch.vbs"""; Tasks: desktopicon_user; WorkingDir: "{app}"
Name: "{userdesktop}\{#MyAppName} Admin"; Filename: "wscript.exe"; Parameters: """{app}\launch.vbs"" /admin"; Tasks: desktopicon_admin; WorkingDir: "{app}"

; Start menu group
Name: "{group}\{#MyAppName}"; Filename: "wscript.exe"; Parameters: """{app}\launch.vbs"""; WorkingDir: "{app}"
Name: "{group}\{#MyAppName} Admin"; Filename: "wscript.exe"; Parameters: """{app}\launch.vbs"" /admin"; WorkingDir: "{app}"
Name: "{group}\Config folder"; Filename: "{app}"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
; Optionally start the app after installation
Filename: "wscript.exe"; Parameters: """{app}\launch.vbs"" /admin"; Flags: nowait postinstall skipifsilent; Description: "{cm:LaunchProgram,{#MyAppName}}"

[Registry]
; Auto-start with Windows (current user)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: "wscript.exe ""{app}\launch.vbs"""; Flags: uninsdeletevalue; Tasks: autostart

[UninstallDelete]
; Clean up runtime files that may be created after installation
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\temp"
