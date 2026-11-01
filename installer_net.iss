; Inno Setup script for PiiBlur — the THIN "net installer".
;
; This installer is tiny (a few MB — just the Inno Setup engine + this script).
; On run, it downloads the real application (Python runtime + OCR + the name
; model, ~250-350 MB) from a GitHub Release and extracts it. This is a common
; pattern (Chrome, Steam, many games use it): small download for everyone,
; nothing lost — all the code ships; only the one-time payload fetch is
; deferred to install time instead of being baked into the installer file.
;
; It needs an internet connection DURING SETUP (not just first launch) — a
; wizard page says so up front. The download is resumable (curl -C -) and
; retries indefinitely on failure rather than giving up, so a flaky connection
; eventually finishes instead of failing the install outright.
;
; A separate installer.iss (the "offline"/full installer) stays available for
; anyone whose connection can't tolerate a mid-setup download — ship both, let
; the user pick, same as how antivirus vendors (ESET, AVG) offer both.
;
;   build:  ISCC /DAppVer=0.1.0 /DPayloadUrl=https://... /DPayloadSha256=... installer_net.iss

#ifndef AppVer
  #define AppVer "0.1.0"
#endif
#ifndef PayloadUrl
  #define PayloadUrl "https://github.com/Saidalo1/PiiBlur/releases/download/v" + AppVer + "/PiiBlur_payload.zip"
#endif
#ifndef PayloadSha256
  #define PayloadSha256 ""
#endif
#ifndef PayloadSizeBytes
  #define PayloadSizeBytes 0
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
OutputBaseFilename=PiiBlur_Setup_Net
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

; No [Files] section for the app itself — it's downloaded in [Code] below.

[Icons]
Name: "{group}\PiiBlur"; Filename: "{app}\PiiBlur.exe"
Name: "{group}\Uninstall PiiBlur"; Filename: "{uninstallexe}"
Name: "{autodesktop}\PiiBlur"; Filename: "{app}\PiiBlur.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PiiBlur.exe"; Description: "Launch PiiBlur"; Flags: nowait postinstall skipifsilent

[Code]
var
  DownloadPage: TOutputProgressWizardPage;
  PayloadZip: String;
  DownloadOK: Boolean;
  LangPage: TWizardPage;
  LangRadios: array[0..2] of TNewRadioButton;

// ---- Step 0: pick PiiBlur's OWN interface language (Uzbek/English/Russian) -
// Separate from [Languages] above, which is only the INSTALLER WIZARD's own
// text (Inno Setup has no Uzbek translation of its own UI) — this picks what
// pii_blur.i18n the app itself starts in. Defaults to Uzbek (the app's own
// default, pii_blur.i18n.DEFAULT_LANGUAGE) since that's most of the userbase;
// changeable later from the app's own Settings window either way.
procedure CreateLanguageChoicePage(AfterPageID: Integer);
var
  Lbl: TNewStaticText;
  i: Integer;
  Captions: array[0..2] of String;
begin
  LangPage := CreateCustomPage(AfterPageID,
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

// ---- Step 1: tell the user up front that this needs the internet ----------
procedure InitializeWizard;
var
  InfoPage: TWizardPage;
  Lbl: TNewStaticText;
begin
  InfoPage := CreateCustomPage(wpWelcome,
    'Internet connection needed',
    'PiiBlur downloads its components during setup.');
  Lbl := TNewStaticText.Create(InfoPage);
  Lbl.Parent := InfoPage.Surface;
  Lbl.AutoSize := False;
  Lbl.WordWrap := True;
  Lbl.Width := InfoPage.SurfaceWidth;
  Lbl.Caption :=
    'This installer is small, but PiiBlur itself (the OCR engine, AI name '
    + 'model and app) is about 250-350 MB and is downloaded now, during '
    + 'setup.'#13#10#13#10
    + 'You need an internet connection for this step. If the connection '
    + 'drops, the download resumes automatically from where it left off and '
    + 'keeps retrying — it does not restart from zero and does not give up.'
    + #13#10#13#10
    + 'Nothing is uploaded; this is a one-way download of PiiBlur itself. '
    + 'Once installed, PiiBlur runs 100% offline — no further internet use.';
  DownloadPage := CreateOutputProgressPage('Downloading PiiBlur',
    'Please wait while PiiBlur''s components are downloaded.');
  CreateLanguageChoicePage(InfoPage.ID);
end;

// ---- Step 2: resumable, never-give-up download via curl.exe ---------------
// curl.exe ships with Windows 10 (1803+) / Windows 11 by default — no extra
// install needed. -C - resumes a partial download instead of restarting; the
// outer loop re-invokes curl (still with -C -) if IT gives up, so a flaky
// connection is retried indefinitely rather than failing the whole install.
function FormatMB(const Bytes: Int64): String;
begin
  Result := IntToStr(Bytes div (1024 * 1024));
end;

function CurrentFileSize(const FileName: String): Int64;
var
  FindRec: TFindRec;
begin
  Result := 0;
  if FindFirst(FileName, FindRec) then
  begin
    Result := FindRec.SizeHigh * $100000000 + FindRec.SizeLow;
    FindClose(FindRec);
  end;
end;

function RunCurl(const Url, DestFile: String): Boolean;
var
  ResultCode: Integer;
  Params: String;
  TotalBytes, GotBytes, LastBytes, StallCount: Int64;
begin
  Result := False;
  TotalBytes := {#PayloadSizeBytes};
  // Download in short (15s) bursts rather than one long blocking call, so we
  // can check the partial file's size BETWEEN bursts and show real progress —
  // -C - (resume) means each burst picks up exactly where the last left off,
  // so nothing already downloaded is wasted.
  Params := '-s -L -C - --max-time 15 --retry 2 --retry-delay 3 '
    + '-o "' + DestFile + '" "' + Url + '"';
  LastBytes := -1;
  StallCount := 0;
  // Each burst below only reports progress AFTER curl returns (up to 15s
  // later) -- without this, the page sits completely blank (no text, no bar)
  // for that whole first window while the connection to GitHub is still
  // being established. Show something immediately instead of waiting for
  // the first burst to finish.
  GotBytes := CurrentFileSize(DestFile);
  if TotalBytes > 0 then
    DownloadPage.SetProgress(GotBytes, TotalBytes);
  DownloadPage.SetText('Connecting…', 'Starting the download — this can take a few seconds.');
  while True do
  begin
    // SW_HIDE: no visible console window — a flashing terminal during setup
    // looks alarming (like a virus) to a non-technical user.
    Exec(ExpandConstant('{sys}\curl.exe'), Params, '', SW_HIDE,
         ewWaitUntilTerminated, ResultCode);
    GotBytes := CurrentFileSize(DestFile);
    if TotalBytes > 0 then
    begin
      DownloadPage.SetProgress(GotBytes, TotalBytes);
      DownloadPage.SetText('Downloading PiiBlur…',
        FormatMB(GotBytes) + ' MB of ' + FormatMB(TotalBytes) + ' MB');
    end
    else
      DownloadPage.SetText('Downloading PiiBlur…', FormatMB(GotBytes) + ' MB so far');
    if (TotalBytes > 0) and (GotBytes >= TotalBytes) then
    begin
      Result := True;
      Exit;
    end;
    if GotBytes = LastBytes then
      StallCount := StallCount + 1
    else
      StallCount := 0;
    LastBytes := GotBytes;
    // No progress across several bursts in a row (not just one slow chunk) —
    // likely offline/blocked, not just slow. Ask before continuing to retry
    // forever silently.
    if StallCount >= 4 then
    if MsgBox('The download does not seem to be progressing. PiiBlur will ' +
              'keep trying — it resumes from where it stopped, nothing is ' +
              'lost.' + Chr(13) + Chr(10) + Chr(13) + Chr(10) + 'Keep trying?',
                    mbConfirmation, MB_YESNO) = IDNO then
      Exit;  // Result stays False — user chose to stop
    // else: loop again, curl -C - picks up from the partial file
  end;
end;

// ---- Step 3: verify + extract ----------------------------------------------
function VerifyAndExtract(const ZipFile, DestDir: String): Boolean;
var
  ActualHash: String;
  ResultCode: Integer;
begin
  Result := False;
#if PayloadSha256 != ""
  DownloadPage.SetText('Verifying download…', '');
  ActualHash := GetSHA256OfFile(ZipFile);
  if CompareText(ActualHash, '{#PayloadSha256}') <> 0 then
  begin
    MsgBox('The downloaded file does not match the expected checksum ' +
           '(it may be corrupted or tampered with). Setup cannot continue.' +
           Chr(13) + Chr(10) + Chr(13) + Chr(10) + 'Expected: {#PayloadSha256}' +
           Chr(13) + Chr(10) + 'Got: ' + ActualHash, mbError, MB_OK);
    Exit;
  end;
#endif
  DownloadPage.SetText('Extracting PiiBlur…', 'Almost done.');
  ForceDirectories(DestDir);
  // tar.exe (bundled since Windows 10 1803) can extract .zip directly — no
  // extra unzip dependency needed.
  if not (Exec(ExpandConstant('{sys}\tar.exe'),
               '-xf "' + ZipFile + '" -C "' + DestDir + '"',
               '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and
          (ResultCode = 0)) then
  begin
    MsgBox('Could not extract the downloaded files (error ' +
           IntToStr(ResultCode) + ').', mbError, MB_OK);
    Exit;
  end;
  Result := True;
end;

// ---- Wire it into the install sequence -------------------------------------
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpReady then
  begin
    DownloadPage.Show;
    try
      PayloadZip := ExpandConstant('{tmp}\PiiBlur_payload.zip');
      DownloadOK := RunCurl('{#PayloadUrl}', PayloadZip);
      if DownloadOK then
        DownloadOK := VerifyAndExtract(PayloadZip, ExpandConstant('{app}'));
    finally
      DownloadPage.Hide;
    end;
    if not DownloadOK then
      Result := False;  // stay on the Ready page so the user can retry/cancel
  end;
end;
