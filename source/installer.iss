#ifndef BundleDir
  #error BundleDir must point to the tested portable folder
#endif
[Setup]
AppId={{DE2D67BD-6A6F-4D9F-8860-E2EB6BE79943}
AppName=AI Voice Changer (Experimental)
AppVersion=0.2.0
AppPublisher=Local Voice Changer Project
DefaultDirName={localappdata}\Programs\LocalVoiceChanger
DefaultGroupName=AI Voice Changer
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputBaseFilename=AI-Voice-Changer-Setup-0.2.0
Compression=zip/1
SolidCompression=no
DiskSpanning=yes
DiskSliceSize=2000000000
WizardStyle=modern
UninstallDisplayIcon={app}\VoiceChanger.exe
CloseApplications=yes
RestartApplications=no
DisableProgramGroupPage=yes
LicenseFile=..\LICENSES\LICENSE-APP.txt

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Ярлык на рабочем столе"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\AI Voice Changer"; Filename: "{app}\VoiceChanger.exe"
Name: "{userdesktop}\AI Voice Changer"; Filename: "{app}\VoiceChanger.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\VoiceChanger.exe"; Description: "Открыть AI Voice Changer"; Flags: nowait postinstall skipifsilent unchecked
