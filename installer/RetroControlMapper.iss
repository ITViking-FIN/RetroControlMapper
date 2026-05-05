; ============================================================================
; RetroControlMapper installer script - Inno Setup 6+
; ============================================================================
; Build:    iscc.exe RetroControlMapper.iss
; Output:   output\RetroControlMapper_0.1.0_setup.exe
;
; This script wraps the PyInstaller --onefile binary produced by Stream PI's
; build pipeline (..\dist\RetroControlMapper.exe). It implements the locked
; spec from DECISIONS.md ("Windows installer (Inno Setup)" + "Installer
; maintenance mode (Repair / Uninstall)").
;
; Wizard pages (locked):
;   1. License (LICENSE — GPL-3.0)
;   2. Install location (DefaultDirName)
;   3. Tasks page (autostart, update-check consent, desktop shortcut, backup
;      RetroBat first)
;   4. Maintenance page (only when an existing install is detected — Repair
;      vs Uninstall radios)
;
; Post-install hooks invoke the application binary with CLI flags for
; configuration handoff. Those CLI flags do NOT yet exist in the source —
; see installer\README.md "Required-but-not-yet-implemented CLI flags".
; ============================================================================

#define AppName        "RetroControlMapper"
#define AppVersion     "0.1.2"
#define AppPublisher   "ITViking-FIN"
#define AppURL         "https://github.com/ITViking-FIN/RetroControlMapper"
#define AppExeName     "RetroControlMapper.exe"
#define AppRegKey      "Software\RetroControlMapper"
#define AppDataFolder  "RB-Controller_fix"

[Setup]
; AppId is a stable UUID — DO NOT change between versions. The same AppId
; across releases is what enables in-place upgrades + maintenance-mode
; detection. Generated 2026-05 for v0.1.0; reuse for all future versions.
AppId={{8E3A9F2C-7B41-4D6E-9F58-2C1A0B5D8E47}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=auto
LicenseFile=..\LICENSE
InfoBeforeFile=
; Note: README.md is shipped as a doc file (see [Files] isreadme flag) and
; opened in the user's default browser via the postinstall [Run] line —
; not as InfoAfterFile, because Inno's InfoAfterFile expects RTF/TXT.
OutputDir=output
OutputBaseFilename=RetroControlMapper_{#AppVersion}_setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; SetupIconFile expects a .ico file; we generate it from the 256 PNG via
; ImageMagick (see installer\README.md step 2). If RetroControlMapper.ico
; is absent, comment this line out and Inno will fall back to its default.
SetupIconFile=RetroControlMapper.ico
UninstallDisplayIcon={app}\{#AppExeName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; ArchitecturesAllowed left blank → all archs accepted (the .exe is a
; PyInstaller --onefile bundle, architecture-specific is set by Stream PI).
ArchitecturesInstallIn64BitMode=x64compatible
ShowLanguageDialog=auto
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; The PyInstaller --onefile binary produced by Stream PI.
Source: "..\dist\{#AppExeName}";  DestDir: "{app}";  Flags: ignoreversion
Source: "..\LICENSE";              DestDir: "{app}";  Flags: ignoreversion
Source: "..\README.md";            DestDir: "{app}";  Flags: ignoreversion isreadme
Source: "..\INSTRUCTIONS.md";      DestDir: "{app}";  Flags: ignoreversion
; Icon assets shipped alongside the .exe so the README/INSTRUCTIONS markdown
; files can reference relative img paths if desired. The .exe itself bundles
; gui/ assets internally (PyInstaller --onefile) so this is documentation
; surfacing only.
Source: "..\gui\img\icon\RetroControlMapper_256.png";  DestDir: "{app}\icon";  Flags: ignoreversion
Source: "..\gui\img\icon\RetroControlMapper_512.png";  DestDir: "{app}\icon";  Flags: ignoreversion skipifsourcedoesntexist
Source: "..\gui\img\icon\RetroControlMapper_1024.png"; DestDir: "{app}\icon";  Flags: ignoreversion skipifsourcedoesntexist
Source: "..\gui\img\icon\RetroControlMapper.svg";      DestDir: "{app}\icon";  Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#AppName}";              Filename: "{app}\{#AppExeName}";  IconFilename: "{app}\{#AppExeName}"
Name: "{group}\Instructions";            Filename: "{app}\INSTRUCTIONS.md"
Name: "{group}\README";                  Filename: "{app}\README.md"
Name: "{group}\Visit GitHub";            Filename: "{#AppURL}"
Name: "{group}\Uninstall {#AppName}";    Filename: "{uninstallexe}"
; {autodesktop} routes to the *user* Desktop when PrivilegesRequired=lowest
; (no admin needed). Using {commondesktop} here would crash with
; "IPersistFile::Save failed; 0x80070005 Access is denied" on a non-elevated
; install since the public Desktop folder requires admin to write.
Name: "{autodesktop}\{#AppName}";        Filename: "{app}\{#AppExeName}";  Tasks: desktopicon

[Tasks]
Name: "desktopicon";        Description: "Create a desktop shortcut";                                    GroupDescription: "Additional shortcuts:"
Name: "autostart";          Description: "Run {#AppName} at Windows startup (recommended)";              GroupDescription: "Startup:";        Flags: checkedonce
Name: "backupretrobat";     Description: "Back up current RetroBat settings now (recommended)";          GroupDescription: "Pre-install:"
Name: "enableupdatecheck";  Description: "Check for updates on startup";                                 GroupDescription: "Network:"

[Registry]
; Autostart Run key — written conditionally by the autostart task. Removed
; on uninstall via uninsdeletevalue.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExeName}"""; \
    Tasks: autostart; Flags: uninsdeletevalue

; App's own settings root — InstallPath is read by the application to locate
; bundled assets. uninsdeletekey wipes the whole subtree on uninstall.
Root: HKCU; Subkey: "{#AppRegKey}"; \
    ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; \
    Flags: uninsdeletekey
Root: HKCU; Subkey: "{#AppRegKey}"; \
    ValueType: string; ValueName: "Version"; ValueData: "{#AppVersion}"; \
    Flags: uninsdeletekey

[Run]
; Post-install: launch the application. The application's first-run logic
; (Stream PI) handles profile-copy-to-APPDATA + initial GUI launch.
Filename: "{app}\{#AppExeName}";  Description: "Launch {#AppName}"; \
    Flags: nowait postinstall skipifsilent

; Open README in the user's default browser/markdown viewer per the
; locked spec ("After install: launches the README/INSTRUCTIONS in the
; user's default browser").
Filename: "{app}\README.md";  Description: "View the README"; \
    Flags: shellexec postinstall skipifsilent unchecked

[UninstallRun]
; Stop the tray app gracefully before removing files. taskkill is
; best-effort — the process may not be running. /F + 2>NUL keeps it silent
; on failure. RunOnceId prevents multiple invocations.
Filename: "{cmd}"; Parameters: "/C taskkill /IM {#AppExeName} /F 2>NUL"; \
    RunOnceId: "StopTray"; Flags: runhidden

; --------------------------------------------------------------------------
; Pascal Code Section
; --------------------------------------------------------------------------
; Implements:
;   - Maintenance-mode detection + Repair/Uninstall radio page (locked spec
;     in DECISIONS.md "Installer maintenance mode (Repair / Uninstall)")
;   - Post-install CLI handoff to the .exe for: factory snapshot capture,
;     update-check consent, autostart, watcher mode
;   - Uninstall-time prompt: "also delete user data?"
; --------------------------------------------------------------------------

[Code]

const
  // Uninstall registry path (Inno Setup convention: <AppId>_is1).
  UninstallRegPath = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{8E3A9F2C-7B41-4D6E-9F58-2C1A0B5D8E47}_is1';

var
  MaintenancePage:    TWizardPage;
  RepairRadio:        TNewRadioButton;
  UninstallRadio:     TNewRadioButton;
  IsMaintenanceMode:  Boolean;

{ ----------------- helper: detect existing install ----------------- }

function ExistingInstallDetected(): Boolean;
var
  uninstallStr: String;
begin
  Result := False;
  if RegQueryStringValue(HKCU, UninstallRegPath, 'UninstallString', uninstallStr) then
    Result := (Length(uninstallStr) > 0);
  if (not Result) and RegQueryStringValue(HKLM, UninstallRegPath, 'UninstallString', uninstallStr) then
    Result := (Length(uninstallStr) > 0);
end;

{ ----------------- InitializeSetup: pre-wizard probe ----------------- }

function InitializeSetup(): Boolean;
begin
  Result := True;
  IsMaintenanceMode := ExistingInstallDetected();
end;

{ ----------------- InitializeWizard: build the maintenance page ----------------- }

procedure InitializeWizard();
begin
  if IsMaintenanceMode then begin
    MaintenancePage := CreateCustomPage(
      wpWelcome,
      'Existing installation detected',
      'A previous install of ' + '{#AppName}' + ' was found. What would you like to do?');

    RepairRadio := TNewRadioButton.Create(MaintenancePage);
    RepairRadio.Parent := MaintenancePage.Surface;
    RepairRadio.Caption := 'Repair: re-extract files (preserves your data and settings)';
    RepairRadio.Top := ScaleY(24);
    RepairRadio.Left := 0;
    RepairRadio.Width := MaintenancePage.SurfaceWidth;
    RepairRadio.Height := ScaleY(20);
    RepairRadio.Checked := True;

    UninstallRadio := TNewRadioButton.Create(MaintenancePage);
    UninstallRadio.Parent := MaintenancePage.Surface;
    UninstallRadio.Caption := 'Uninstall: remove the application (you will be asked about user data)';
    UninstallRadio.Top := RepairRadio.Top + RepairRadio.Height + ScaleY(8);
    UninstallRadio.Left := 0;
    UninstallRadio.Width := MaintenancePage.SurfaceWidth;
    UninstallRadio.Height := ScaleY(20);
  end;
end;

{ ----------------- run the existing uninstaller silently ----------------- }

procedure RunExistingUninstaller();
var
  uninstallStr: String;
  resultCode:   Integer;
begin
  if not RegQueryStringValue(HKCU, UninstallRegPath, 'UninstallString', uninstallStr) then
    if not RegQueryStringValue(HKLM, UninstallRegPath, 'UninstallString', uninstallStr) then
      Exit;
  uninstallStr := RemoveQuotes(uninstallStr);
  if FileExists(uninstallStr) then
    Exec(uninstallStr, '/SILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_SHOW,
         ewWaitUntilTerminated, resultCode);
end;

{ ----------------- NextButtonClick: handle Uninstall branch ----------------- }

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if IsMaintenanceMode and Assigned(MaintenancePage)
     and (CurPageID = MaintenancePage.ID) then begin
    if UninstallRadio.Checked then begin
      // Uninstall branch: invoke the previous installer's uninstaller and
      // exit setup. The user can re-run setup afterwards for a clean install.
      RunExistingUninstaller();
      WizardForm.Close;
      Result := False;
      Exit;
    end;
    // Repair branch: continue normally — Inno re-extracts via [Files].
  end;
end;

{ ----------------- ShouldSkipPage: optional UX polish ----------------- }

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  // No pages are conditionally skipped right now. Wired for future use.
  Result := False;
end;

{ ----------------- post-install: hand off settings to the .exe ----------------- }

procedure CurStepChanged(CurStep: TSetupStep);
var
  exePath:    String;
  resultCode: Integer;
begin
  if CurStep = ssPostInstall then begin
    exePath := ExpandConstant('{app}\{#AppExeName}');

    if not FileExists(exePath) then
      Exit;  // Repair-from-broken case: nothing to invoke.

    // 1. Factory snapshot: opt-in via the backupretrobat task.
    //    DECISIONS.md #5 tier-1 "pre-install snapshot, never overwritten".
    //    backups.snapshot('factory', ...) is one-shot — re-running this
    //    on a Repair install is a no-op (snapshot() refuses re-capture).
    if WizardIsTaskSelected('backupretrobat') then begin
      Exec(exePath, '--capture-factory-snapshot', '', SW_HIDE,
           ewWaitUntilTerminated, resultCode);
    end;

    // 2. Update-check consent: opt-in via the enableupdatecheck task.
    //    Writes the consent flag the GUI's update_check.py reads.
    if WizardIsTaskSelected('enableupdatecheck') then begin
      Exec(exePath, '--set-update-check-consent on', '', SW_HIDE,
           ewWaitUntilTerminated, resultCode);
    end else begin
      Exec(exePath, '--set-update-check-consent off', '', SW_HIDE,
           ewWaitUntilTerminated, resultCode);
    end;

    // 3. Autostart: synced with the autostart task. Even though the
    //    Run-key registry write happens via [Registry], we also call the
    //    .exe so the application can record its own state (e.g. for the
    //    settings UI to reflect the right toggle position on first launch).
    if WizardIsTaskSelected('autostart') then begin
      Exec(exePath, '--set-autostart on', '', SW_HIDE,
           ewWaitUntilTerminated, resultCode);
    end else begin
      Exec(exePath, '--set-autostart off', '', SW_HIDE,
           ewWaitUntilTerminated, resultCode);
    end;

    // 4. Watcher mode: default 'detect' (per guid_watcher.DEFAULT_MODE).
    //    No wizard task currently exposes this — we simply assert the
    //    default. A future installer revision could surface a tasks-page
    //    radio for off / detect / auto-fold.
    Exec(exePath, '--set-watcher-mode detect', '', SW_HIDE,
         ewWaitUntilTerminated, resultCode);
  end;
end;

{ ----------------- uninstall: prompt about user-data removal ----------------- }

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  msg:           String;
  appdataDir:    String;
  removeAppData: Integer;
begin
  if CurUninstallStep = usPostUninstall then begin
    appdataDir := ExpandConstant('{userappdata}\{#AppDataFolder}');

    if not DirExists(appdataDir) then
      Exit;  // Nothing to ask about.

    msg := 'Also delete user data (profiles, backups, factory snapshot, settings) at' + #13#10 +
           appdataDir + ' ?' + #13#10 + #13#10 +
           'Choose No to keep your data so a future reinstall can restore it.' + #13#10 +
           '(Default: No.)';

    removeAppData := MsgBox(msg, mbConfirmation, MB_YESNO or MB_DEFBUTTON2);
    if removeAppData = IDYES then begin
      DelTree(appdataDir, True, True, True);
    end;
  end;
end;
