; Instalador do Abonário (Inno Setup 6/7).
; Gere com:  python build\make_installer.py
; Parâmetros do compilador: /DSourceDir=<pasta com Abonario.exe, _internal e abonario.db>  /DAppVersion=x.y

#ifndef AppVersion
  #define AppVersion "1.2"
#endif
#ifndef SourceDir
  #define SourceDir GetEnv("LOCALAPPDATA") + "\Programs\Abonario"
#endif

[Setup]
AppId={{37A65813-1BD9-4365-8CBE-C6D8D01A9290}
AppName=Abonário
AppVersion={#AppVersion}
AppVerName=Abonário {#AppVersion}
AppPublisher=Abonário
AppPublisherURL=https://github.com/k-claudio/abonario
AppSupportURL=https://github.com/k-claudio/abonario
AppUpdatesURL=https://github.com/k-claudio/abonario/releases
AppComments=Dicionário da língua portuguesa com abonações (offline)
; instalação por usuário, sem senha de administrador: {autopf} = %LOCALAPPDATA%\Programs
PrivilegesRequired=lowest
DefaultDirName={autopf}\Abonario
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
SetupIconFile=..\app\ui\abonario.ico
UninstallDisplayIcon={app}\Abonario.exe
UninstallDisplayName=Abonário
CloseApplications=yes
OutputDir=..
OutputBaseFilename=Instalar-Abonario
VersionInfoVersion={#AppVersion}
VersionInfoDescription=Instalador do Abonário
VersionInfoProductName=Abonário

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; remove as bibliotecas de uma versão anterior antes de copiar as novas
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\Abonario.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceDir}\abonario.db"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "LEIA-ME.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Abonário"; Filename: "{app}\Abonario.exe"; Comment: "Dicionário da língua portuguesa com abonações"; Check: WantShortcuts
Name: "{autodesktop}\Abonário"; Filename: "{app}\Abonario.exe"; Tasks: desktopicon; Check: WantShortcuts

[Run]
Filename: "{app}\Abonario.exe"; Description: "{cm:LaunchProgram,Abonário}"; Flags: nowait postinstall skipifsilent

[Code]
{ /NOSHORTCUTS=1 (uso em testes) instala sem criar atalhos }
function WantShortcuts: Boolean;
begin
  Result := ExpandConstant('{param:NOSHORTCUTS|0}') <> '1';
end;
