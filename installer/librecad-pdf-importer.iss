; Inno Setup script -- standalone LibreCAD PDF Importer (no Python required)
; 1) Build the app:   python build_standalone.py
; 2) Compile this:    iscc installer\librecad-pdf-importer.iss
;    (Inno Setup 6: https://jrsoftware.org/isinfo.php)
; Produces: installer\Output\LibreCAD-PDF-Importer-Setup_vX.Y.Z.exe

#define AppName "LibreCAD PDF Importer"
#define AppPublisher "BlueCollar Systems"
#define AppExeName "LibreCAD-PDF-Importer.exe"
#ifndef AppVersion
  #define AppVersion "1.0.25"
#endif
#define DistDir "..\dist\LibreCAD-PDF-Importer"

[Setup]
AppId={{A7C3E1B2-5D44-4E9A-9F1C-2B6D7E8F0A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\BlueCollar Systems\LibreCAD PDF Importer
DefaultGroupName=LibreCAD PDF Importer
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=LibreCAD-PDF-Importer-Setup_v{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\THIRD_PARTY_LICENSES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\LibreCAD PDF Importer"; Filename: "{app}\{#AppExeName}"
Name: "{userdesktop}\LibreCAD PDF Importer"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch LibreCAD PDF Importer"; Flags: nowait postinstall skipifsilent
