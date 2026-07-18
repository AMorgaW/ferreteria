; Instalador profesional de FERREPRO (Inno Setup 6)
; Compilar con:  iscc installer.iss   (requiere Inno Setup, https://jrsoftware.org/isdl.php)
; El ejecutable se distribuye en modo onedir (no requiere Python). Los datos (BD, config, logs,
; respaldos, certificados) se crean en %PROGRAMDATA%\FERREPRO (escribible),
; por lo que el programa puede instalarse en Program Files sin problemas.

#define MyAppName "FERREPRO"
#define MyAppVersion "4.0.0"
#define MyAppPublisher "FERREPRO"
#define MyAppExeName "Ferreteria.exe"

[Setup]
AppId={{8F2A9C44-3B7E-4D21-9A6C-FERREPRO0001}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=dist_installer
OutputBaseFilename=FERREPRO-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyAppName} {#MyAppVersion}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "dist\Ferreteria\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Abrir el firewall para que las cajas (Equipo B) alcancen el servidor (Equipo A)
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""FERREPRO Servidor Local"" dir=in action=allow program=""{app}\{#MyAppExeName}"" enable=yes profile=any"; Flags: runhidden
; Ofrecer iniciar la app al terminar
Filename: "{app}\{#MyAppExeName}"; Description: "Iniciar {#MyAppName} ahora"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""FERREPRO Servidor Local"""; Flags: runhidden

; NOTA: la desinstalación NO elimina %PROGRAMDATA%\FERREPRO (base de datos,
; respaldos y configuración del negocio se conservan a propósito).
