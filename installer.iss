; Inno Setup script for PiiBlur — wraps the PyInstaller onedir build into a
; compressed Windows installer. Best-practice bits: per-user install (no admin),
; lzma2/ultra64 solid compression (small download), EN+RU, desktop shortcut,
; launch after install. The app registers its own run-on-login on first launch.
;
;   build:  python build.py           (recommended, one shot)
;   or:     ISCC /DAppVer=0.1.0 installer.iss   (after `pyinstaller PiiBlur.spec`)

#ifndef AppVer
  #define AppVer "0.1.0"
#endif

[Setup]
AppId={{9C2F7A61-4B3D-4E8A-9F12-7E5A1C0D3B44}
AppName=PiiBlur
AppVersion={#AppVer}
VersionInfoVersion={#AppVer}
AppPublisher=PiiBlur
DefaultDirName={localappdata}\PiiBlur
DisableDirPage=no
DefaultGroupName=PiiBlur
OutputDir=installer_output
OutputBaseFilename=PiiBlur_Setup
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\PiiBlur.exe
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; The whole PyInstaller onedir folder (exe + Python runtime + OCR models).
Source: "dist\PiiBlur\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PiiBlur"; Filename: "{app}\PiiBlur.exe"
Name: "{group}\Uninstall PiiBlur"; Filename: "{uninstallexe}"
Name: "{autodesktop}\PiiBlur"; Filename: "{app}\PiiBlur.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PiiBlur.exe"; Description: "Launch PiiBlur"; Flags: nowait postinstall skipifsilent
