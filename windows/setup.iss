#define AppVersion "0.1.2"
[Setup]
AppId={{3C5BA2DC-ABCB-4C84-98E1-79235E302D69}
AppName=Codex Quota Guard
AppVersion={#AppVersion}
AppPublisher=Codex Quota Guard community project
DefaultDirName={localappdata}\Programs\CodexQuotaGuard
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=codex-quota-guard-{#AppVersion}-setup
Compression=zip
SolidCompression=no
WizardStyle=modern
UninstallDisplayIcon={app}\CodexQuotaGuard.exe
CloseApplications=yes
RestartApplications=no
InfoBeforeFile=NOTICE.txt
[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
[Files]
Source: "..\build\payload\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{userdesktop}\Codex 额度守护"; Filename: "{app}\CodexQuotaGuard.exe"
Name: "{userprograms}\Codex Quota Guard\Status"; Filename: "{app}\CodexQuotaGuard.exe"
[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Codex Quota Guard"; ValueData: """{app}\CodexQuotaGuard.exe"" --background"; Flags: uninsdeletevalue
[Run]
Filename: "{app}\CodexQuotaGuard.exe"; Parameters: "--background"; Flags: nowait runascurrentuser; Check: ShouldStartGuard
[Code]
function ShouldStartGuard(): Boolean;
var I: Integer;
begin
  Result := True;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/NOSTART') = 0 then Result := False;
end;

function InitializeUninstall(): Boolean;
var Code: Integer;
begin
  Result := Exec(ExpandConstant('{app}\CodexQuotaGuard.exe'), '--uninstall', '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
  if not Result then MsgBox('Configuration restore failed. Program files were preserved. Close Codex Quota Guard and retry.', mbError, MB_OK);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Code: Integer;
begin
  Result := '';
  if FileExists(ExpandConstant('{app}\CodexQuotaGuard.exe')) then
    if not Exec(ExpandConstant('{app}\CodexQuotaGuard.exe'), '--stop', '', SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
      Result := 'Please close Codex Quota Guard before updating.';
end;
