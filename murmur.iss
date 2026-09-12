; ============================================================
;  Murmur — Inno Setup Installer Script
;  https://github.com/R3PC0N/murmur
; ============================================================

#define AppName      "Murmur"
#define AppVersion   "1.2.1"
#define AppPublisher "R3PC0N"

[Setup]
AppId={{C7F8A2B1-3D4E-5F6A-7B8C-9D0E1F2A3B4C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/R3PC0N/murmur
DefaultDirName={localappdata}\{#AppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=Murmur-Setup-v{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UninstallDisplayName={#AppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "main.py";             DestDir: "{app}"; Flags: ignoreversion
Source: "config.py";           DestDir: "{app}"; Flags: ignoreversion
Source: "recorder.py";         DestDir: "{app}"; Flags: ignoreversion
Source: "transcriber.py";      DestDir: "{app}"; Flags: ignoreversion
Source: "cleaner.py";          DestDir: "{app}"; Flags: ignoreversion
Source: "paster.py";           DestDir: "{app}"; Flags: ignoreversion
Source: "overlay.py";          DestDir: "{app}"; Flags: ignoreversion
Source: "settings_window.py";  DestDir: "{app}"; Flags: ignoreversion
Source: "autostart.py";        DestDir: "{app}"; Flags: ignoreversion
Source: "splash.py";           DestDir: "{app}"; Flags: ignoreversion
Source: "logger.py";           DestDir: "{app}"; Flags: ignoreversion
Source: "log_window.py";       DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt";    DestDir: "{app}"; Flags: ignoreversion
Source: ".env.example"; DestDir: "{app}"; DestName: ".env.example"; Flags: ignoreversion
Source: "murmur.ico";                    DestDir: "{app}"; Flags: ignoreversion
Source: "server_manager_window.py";      DestDir: "{app}"; Flags: ignoreversion
Source: "theme_utils.py";               DestDir: "{app}"; Flags: ignoreversion
Source: "ui\settings.html";             DestDir: "{app}\ui"; Flags: ignoreversion
Source: "ui\log.html";                  DestDir: "{app}\ui"; Flags: ignoreversion
Source: "ui\server.html";               DestDir: "{app}\ui"; Flags: ignoreversion
Source: "ui\splash.html";               DestDir: "{app}\ui"; Flags: ignoreversion
Source: "server\faster_whisper_server.py"; DestDir: "{app}\server"; Flags: ignoreversion
Source: "server\requirements.txt";      DestDir: "{app}\server"; Flags: ignoreversion
Source: "server\.env.example";          DestDir: "{app}\server"; DestName: ".env.example"; Flags: ignoreversion
Source: "themes\omarchy_palettes.json"; DestDir: "{app}\themes"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\venv\Scripts\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\murmur.ico"; Comment: "Voice dictation with AI cleanup"
Name: "{autodesktop}\{#AppName}";  Filename: "{app}\venv\Scripts\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\murmur.ico"; Tasks: desktopicon; Comment: "Voice dictation with AI cleanup"

[Run]
Filename: "python.exe"; Parameters: "-m venv ""{app}\venv"""; StatusMsg: "Creating virtual environment..."; Flags: runhidden waituntilterminated
Filename: "{app}\venv\Scripts\python.exe"; Parameters: "-m pip install --upgrade pip --quiet"; StatusMsg: "Upgrading pip..."; Flags: runhidden waituntilterminated
Filename: "{app}\venv\Scripts\pip.exe"; Parameters: "install -r ""{app}\requirements.txt"" --quiet"; StatusMsg: "Installing dependencies — this takes a few minutes, please wait..."; Flags: runhidden waituntilterminated
Filename: "{app}\venv\Scripts\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; Description: "Launch {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\venv"
Type: filesandordirs; Name: "{app}\server\venv"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files;          Name: "{app}\settings.json"

[InstallDelete]
Type: filesandordirs; Name: "{app}\server\venv"

[Code]

// ── Helpers ───────────────────────────────────────────────────────────────────

function PythonFound(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('python.exe', '--version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
            and (ResultCode = 0);
end;

function Cuda12Found(): Boolean;
var
  I: Integer;
  Versions: array[0..8] of String;
begin
  Result := False;
  Versions[0] := 'v12.0'; Versions[1] := 'v12.1'; Versions[2] := 'v12.2';
  Versions[3] := 'v12.3'; Versions[4] := 'v12.4'; Versions[5] := 'v12.5';
  Versions[6] := 'v12.6'; Versions[7] := 'v12.7'; Versions[8] := 'v12.8';
  for I := 0 to 8 do
  begin
    if FileExists('C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\' + Versions[I] + '\bin\cublas64_12.dll') then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function PythonVersionCompatible(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('python.exe',
    '-c ' + #34 + 'import sys; v=sys.version_info; sys.exit(0 if v.major==3 and 10<=v.minor<=13 else 1)' + #34,
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function PythonVersionTooNew(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('python.exe',
    '-c ' + #34 + 'import sys; v=sys.version_info; sys.exit(0 if v.major==3 and v.minor>=14 else 1)' + #34,
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

// ── Pre-install checks ────────────────────────────────────────────────────────

function InitializeSetup(): Boolean;
begin
  Result := True;

  if not PythonFound() then
  begin
    MsgBox(
      'Python 3.10 or newer is required but was not found in PATH.' + #13#10#13#10 +
      'Please install Python from:' + #13#10 +
      'https://www.python.org/downloads/' + #13#10#13#10 +
      'Important: tick "Add Python to PATH" during installation,' + #13#10 +
      'then re-run this installer.',
      mbCriticalError, MB_OK
    );
    Result := False;
    Exit;
  end;

  if not PythonVersionCompatible() then
  begin
    if PythonVersionTooNew() then
      MsgBox(
        'Python 3.14 or newer is not yet compatible with Murmur.' + #13#10#13#10 +
        'Please install Python 3.11 or 3.13 from:' + #13#10 +
        'https://www.python.org/downloads/' + #13#10#13#10 +
        'Important: tick "Add Python to PATH" during installation,' + #13#10 +
        'then re-run this installer.',
        mbCriticalError, MB_OK
      )
    else
      MsgBox(
        'Python 3.10 or newer is required but an older version was detected.' + #13#10#13#10 +
        'Please install Python 3.11 or 3.13 from:' + #13#10 +
        'https://www.python.org/downloads/' + #13#10#13#10 +
        'Important: tick "Add Python to PATH" during installation,' + #13#10 +
        'then re-run this installer.',
        mbCriticalError, MB_OK
      );
    Result := False;
    Exit;
  end;

  if not Cuda12Found() then
  begin
    MsgBox(
      'CUDA Toolkit 12.x was not detected on this machine.' + #13#10#13#10 +
      'Murmur will be installed and will work using your CPU.' + #13#10 +
      'For much faster transcription with an NVIDIA GPU, install' + #13#10 +
      'CUDA Toolkit 12.x from:' + #13#10 +
      'https://developer.nvidia.com/cuda-toolkit-archive' + #13#10#13#10 +
      'Afterwards, open Murmur Settings and set Device to "cuda".',
      mbInformation, MB_OK
    );
  end;
end;

// ── Post-install: create .env and show first-run instructions ─────────────────

procedure CurStepChanged(CurStep: TSetupStep);
var
  EnvFile, SettingsFile: String;
begin
  if CurStep = ssDone then
  begin
    EnvFile := ExpandConstant('{app}\.env');
    if not FileExists(EnvFile) then
      CopyFile(ExpandConstant('{app}\.env.example'), EnvFile, False);

    // Write CPU-safe defaults when CUDA is not available
    SettingsFile := ExpandConstant('{app}\settings.json');
    if not FileExists(SettingsFile) and not Cuda12Found() then
      SaveStringToFile(SettingsFile,
        '{' + #13#10 +
        '  "WHISPER_MODEL": "medium",' + #13#10 +
        '  "WHISPER_DEVICE": "cpu",' + #13#10 +
        '  "WHISPER_COMPUTE_TYPE": "int8"' + #13#10 +
        '}', False);

    MsgBox(
      'Murmur is installed!' + #13#10#13#10 +
      'Before you start, two things to know:' + #13#10#13#10 +
      '1) API key for AI cleanup:' + #13#10 +
      '   Open ' + EnvFile + #13#10 +
      '   and replace  sk-ant-...  with your key from console.anthropic.com' + #13#10#13#10 +
      '2) First launch downloads the Whisper speech model (~300 MB).' + #13#10 +
      '   A loading screen will appear — just wait until it disappears.' + #13#10#13#10 +
      'After that, hold F9 anywhere to start dictating.',
      mbInformation, MB_OK
    );
  end;
end;
