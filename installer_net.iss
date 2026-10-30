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
end;

// ---- Step 2: resumable, never-give-up download via curl.exe ---------------
// curl.exe ships with Windows 10 (1803+) / Windows 11 by default — no extra
// install needed. -C - resumes a partial download instead of restarting; the
// outer loop re-invokes curl (still with -C -) if IT gives up, so a flaky
// connection is retried indefinitely rather than failing the whole install.
function RunCurl(const Url, DestFile: String): Boolean;
var
  ResultCode: Integer;
  Attempt: Integer;
  Params: String;
begin
  Result := False;
  Attempt := 0;
  Params := '-L -C - --retry 20 --retry-delay 5 --retry-all-errors '
    + '-o "' + DestFile + '" "' + Url + '"';
  while not Result do
  begin
    Attempt := Attempt + 1;
    DownloadPage.SetText('Downloading PiiBlur components (attempt ' +
      IntToStr(Attempt) + ')…', 'This can take a while on a slow connection.');
    if Exec(ExpandConstant('{sys}\curl.exe'), Params, '', SW_SHOWNORMAL,
            ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
      Result := True
    else if MsgBox('The download was interrupted. PiiBlur will try again ' +
                    '(it resumes from where it stopped, nothing is lost).' +
                    Chr(13) + Chr(10) + Chr(13) + Chr(10) + 'Keep trying?',
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
