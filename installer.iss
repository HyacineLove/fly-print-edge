; Inno Setup script for FlyPrint Edge

#define MyAppName "FlyPrint Edge"
#define MyAppPublisher "FlyPrint"
#define MyAppExeName "flyprint-edge.exe"
#define MyLauncherExeName "flyprint-launcher.exe"

#ifndef MyAppVersion
  #define MyAppVersion "1.0.43"
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
UninstallDisplayName={#MyAppName}
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
english.BeveledLabel={#MyAppName}

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon} - {#MyAppName}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "autostart"; Description: "Start {#MyAppName} automatically when Windows starts"; GroupDescription: "Startup options:"; Flags: unchecked

[Files]
Source: "dist\flyprint-edge\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\flyprint-edge\{#MyLauncherExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\flyprint-edge\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\flyprint-edge\_internal\config.example.json"; DestDir: "{app}"; DestName: "config.example.json"; Flags: ignoreversion
Source: "dist\flyprint-edge\_internal\config.example.json"; DestDir: "{app}"; DestName: "config.json"; Flags: ignoreversion onlyifdoesntexist
Source: "dist\flyprint-edge\_internal\docs\*"; DestDir: "{app}\docs"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{app}\logs"
Name: "{app}\runtime"
Name: "{app}\temp"

[Icons]
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyLauncherExeName}"; Tasks: desktopicon; WorkingDir: "{app}"
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyLauncherExeName}"; WorkingDir: "{app}"
Name: "{group}\Logs"; Filename: "{app}\logs"; WorkingDir: "{app}"
Name: "{group}\Install Folder"; Filename: "{app}"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyLauncherExeName}"; Parameters: "--open-user"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent; Description: "{cm:LaunchProgram,{#MyAppName}}"

[UninstallRun]
Filename: "{app}\{#MyLauncherExeName}"; Parameters: "--exit"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: "StopFlyPrintEdge"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyLauncherExeName}"""; Flags: uninsdeletevalue; Tasks: autostart

[UninstallDelete]
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\temp"
Type: filesandordirs; Name: "{localappdata}\FlyPrint Edge"
