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
; wizard page says so up front. Uses Inno Setup's own built-in
; DownloadTemporaryFile (6.1+) -- ONE continuous HTTPS connection for the
; whole payload, with a progress callback that fires continuously as bytes
; arrive (same as a browser's own download bar), not the old hand-rolled
; curl.exe-in-15s-bursts design this replaced: that one had to re-open a
; fresh HTTPS connection (full TLS handshake + GitHub's redirect) every
; single burst, AND only updated the on-screen number once per burst, so it
; looked frozen between updates even on a perfectly fine connection. If a
; download fails partway, the whole call is retried (DownloadTemporaryFile
; has no public resume-across-retries API, unlike curl's -C -), up to
; several times before asking the user whether to keep trying.
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

// Drives a PLAIN output-progress page (not TDownloadWizardPage) so we have
// full control of the displayed text -- TDownloadWizardPage.Download() was
// tried first and rejected: it overwrites whatever the OnDownloadProgress
// callback sets with its own "Downloading file: <the raw URL>" status line
// right after the callback returns, so there was no way to actually hide the
// URL while using it. Calling the global DownloadTemporaryFile() function
// directly instead means we own the page's text completely.
function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  if ProgressMax > 0 then
  begin
    DownloadPage.SetProgress(Progress, ProgressMax);
    DownloadPage.SetText('Downloading PiiBlur…',
      IntToStr(Progress div (1024 * 1024)) + ' MB of ' +
      IntToStr(ProgressMax div (1024 * 1024)) + ' MB');
  end
  else
    DownloadPage.SetText('Downloading PiiBlur…',
      IntToStr(Progress div (1024 * 1024)) + ' MB');
  Result := True;  // continue the download
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

// ---- Step 2: one continuous download via Inno Setup's own DownloadTemporaryFile,
// not curl -- a single HTTPS connection for the whole payload, with the page's
// built-in progress bar updating live as bytes stream in (like a browser's own
// download bar), instead of the old curl-in-15s-bursts design that both
// re-opened the connection every burst AND only showed a new number once per
// burst. RequiredSHA256OfFile verifies the download itself (raises if it
// doesn't match), so no separate manual hash-check step is needed afterward.
function DoDownload(): Boolean;
var
  Attempt: Integer;
begin
  Result := False;
  Attempt := 0;
  DownloadPage.SetText('Connecting…', 'Starting the download — this can take a few seconds.');
  DownloadPage.Show;
  try
    while True do
    begin
      Attempt := Attempt + 1;
      try
        DownloadTemporaryFile('{#PayloadUrl}', 'PiiBlur_payload.zip',
          '{#PayloadSha256}', @OnDownloadProgress);
        Result := True;
        Exit;
      except
        // DownloadTemporaryFile has no public resume-across-retries API (unlike
        // curl's -C -), so a retry here restarts the whole payload -- still
        // far better than failing the install outright on one network blip.
        if Attempt >= 3 then
        if MsgBox('The download failed (' + GetExceptionMessage + ').' +
                  Chr(13) + Chr(10) + Chr(13) + Chr(10) + 'Try again?',
                  mbError, MB_YESNO) = IDNO then
          Exit;  // Result stays False
      end;
    end;
  finally
    DownloadPage.Hide;
  end;
end;

// A previous install's PiiBlur.exe can still be running in the tray when the
// user re-runs setup. CloseApplications=yes in [Setup] does NOT catch this --
// that mechanism only checks files listed in a [Files] section, and this
// installer has none (the app is extracted via tar.exe in code, not Inno's
// own file-copy engine), so Inno never even knows PiiBlur.exe will be
// touched and never offers to close it. The running process then holds its
// own .exe open, so tar.exe fails to overwrite it -- consistently, not a
// one-off lock, which is why retrying the extraction alone never helped.
// Confirmed on a real affected machine: Get-Process showed PiiBlur.exe
// running from an earlier install/test, and the error stopped as soon as it
// was closed. taskkill here is a best-effort close (exit code ignored --
// "not running" is not a failure); the short Sleep lets Windows actually
// release the file handle after the process exits before tar touches it.
procedure CloseRunningApp();
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM PiiBlur.exe /T', '',
       SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(500);
end;

// ---- Step 3: extract --------------------------------------------------------
function ExtractPayload(const ZipFile, DestDir: String): Boolean;
var
  ResultCode, Attempt: Integer;
begin
  Result := False;
  CloseRunningApp();
  ForceDirectories(DestDir);
  // tar.exe (bundled since Windows 10 1803) can extract .zip directly — no
  // extra unzip dependency needed.
  //
  // Real bug from a user's machine: the download itself completed and its
  // SHA-256 verified fine, but the VERY NEXT tar.exe call on that same file
  // still failed with error 1 -- yet manually re-downloading the identical
  // file (same bytes, verified by hand with tar separately) and extracting
  // it worked without any changes. Classic signature of something else
  // (most likely real-time antivirus) transiently locking a just-downloaded
  // archive containing executables for a moment right after it lands on
  // disk -- not a corrupt download, not a tar/path/disk-space problem (all
  // individually ruled out on the affected machine). A short retry loop is
  // the standard way installers ride out exactly this kind of transient
  // lock, the same resilience shape DoDownload already uses for the network
  // call.
  for Attempt := 1 to 3 do
  begin
    if Exec(ExpandConstant('{sys}\tar.exe'), '-xf "' + ZipFile + '" -C "' + DestDir + '"',
            '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
    begin
      Result := True;
      Exit;
    end;
    if Attempt < 3 then
      Sleep(1500);
  end;
  MsgBox('Could not extract the downloaded files (error ' +
         IntToStr(ResultCode) + ').', mbError, MB_OK);
end;

// ---- Wire it into the install sequence -------------------------------------
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpReady then
  begin
    DownloadOK := DoDownload();
    if DownloadOK then
      DownloadOK := ExtractPayload(ExpandConstant('{tmp}\PiiBlur_payload.zip'),
                                    ExpandConstant('{app}'));
    if not DownloadOK then
      Result := False;  // stay on the Ready page so the user can retry/cancel
  end;
end;
