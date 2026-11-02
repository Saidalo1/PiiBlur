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
OutputBaseFilename=PiiBlur_Setup_Offline
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

[Code]
var
  LangPage: TWizardPage;
  LangRadios: array[0..2] of TNewRadioButton;

// Picks PiiBlur's OWN interface language (Uzbek/English/Russian) -- separate
// from [Languages] above, which is only the INSTALLER WIZARD's own text
// (Inno Setup has no Uzbek translation of its own UI). Defaults to Uzbek
// (pii_blur.i18n.DEFAULT_LANGUAGE) since that's most of the userbase;
// changeable later from the app's own Settings window either way. Mirrors
// installer_net.iss's own copy of this logic (the two scripts don't share a
// common [Code] include, so this stays duplicated between them).
procedure InitializeWizard;
var
  Lbl: TNewStaticText;
  i: Integer;
  Captions: array[0..2] of String;
begin
  LangPage := CreateCustomPage(wpWelcome,
    'Choose your language', 'Select PiiBlur''s interface language.');
  Lbl := TNewStaticText.Create(LangPage);
  Lbl.Parent := LangPage.Surface;
  Lbl.AutoSize := False;
  Lbl.WordWrap := True;
  Lbl.Width := LangPage.SurfaceWidth;
  Lbl.Caption := 'You can change this later from PiiBlur''s own Settings window.';
  Captions[0] := 'O''zbekcha';
  Captions[1] := 'English';
  Captions[2] := 'Русский';
  for i := 0 to 2 do
  begin
    LangRadios[i] := TNewRadioButton.Create(LangPage);
    LangRadios[i].Parent := LangPage.Surface;
    LangRadios[i].Width := LangPage.SurfaceWidth;
    LangRadios[i].Top := Lbl.Top + Lbl.Height + 12 + i * 24;
    LangRadios[i].Caption := Captions[i];
  end;
  LangRadios[0].Checked := True;  // Uzbek default, matches the app's own default
end;

function ChosenLanguageCode(): String;
begin
  if LangRadios[1].Checked then Result := 'en'
  else if LangRadios[2].Checked then Result := 'ru'
  else Result := 'uz';
end;

// Writes the chosen language to the SAME config.json pii_blur.settings_store
// reads, so the very first launch already starts in it. Never overwrites an
// EXISTING config.json (a reinstall/upgrade over a configured install must
// never silently reset the user's own language/settings back to a default).
procedure WriteLanguageChoice();
var
  ConfigDir, ConfigFile: String;
begin
  ConfigDir := ExpandConstant('{userappdata}\PiiBlur');
  ConfigFile := ConfigDir + '\config.json';
  if FileExists(ConfigFile) then
    Exit;
  ForceDirectories(ConfigDir);
  SaveStringToFile(ConfigFile, '{"language": "' + ChosenLanguageCode() + '"}', False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    WriteLanguageChoice();
end;
