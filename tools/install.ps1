param([string]$Python='')
$ErrorActionPreference='Stop'
$source=Split-Path -Parent $PSScriptRoot
if(-not $env:LOCALAPPDATA -or -not $env:APPDATA){throw 'Windows standard application-data locations are required.'}
$destination=Join-Path $env:LOCALAPPDATA 'Programs\LocalWorkOS\1.3.0'

# Use the user's existing Python. Never install packages or touch other apps.
$candidates=@()
if($Python){
 if(Test-Path -LiteralPath $Python -PathType Leaf){$candidates+= (Resolve-Path -LiteralPath $Python).Path}
 else{
  $command=Get-Command $Python -CommandType Application -ErrorAction SilentlyContinue
  if($command){$candidates+=$command.Source}
 }
 if(-not $candidates){throw 'The specified Python executable does not exist.'}
}else{
 $command=Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue
 if($command){$candidates+=$command.Source}
 $launcher=Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue
 if($launcher){
  $resolved=& $launcher.Source -3 -c 'import sys; print(sys.executable)' 2>$null
  if($LASTEXITCODE -eq 0 -and $resolved){$candidates+=([string]($resolved|Select-Object -Last 1)).Trim()}
 }
 # PEP 514 registrations include ordinary per-user/system and custom locations.
 foreach($registry in @('HKCU:\Software\Python\PythonCore','HKLM:\Software\Python\PythonCore','HKLM:\Software\WOW6432Node\Python\PythonCore')){
  if(Test-Path -LiteralPath $registry){
   foreach($version in Get-ChildItem -LiteralPath $registry){
    $key=Join-Path $version.PSPath 'InstallPath'
    if(Test-Path -LiteralPath $key){
     $properties=Get-ItemProperty -LiteralPath $key
     if($properties.ExecutablePath){$candidates+=$properties.ExecutablePath}
     if($properties.'(default)'){$candidates+=Join-Path $properties.'(default)' 'python.exe'}
    }
   }
  }
 }
}
$selected=''
foreach($candidate in ($candidates|Select-Object -Unique)){
 $probe=$candidate
 if((Split-Path -Leaf $probe) -ieq 'pythonw.exe'){$probe=Join-Path (Split-Path -Parent $probe) 'python.exe'}
 if(-not (Test-Path -LiteralPath $probe -PathType Leaf)){continue}
 try{
  $resolved=& $probe -c 'import sys; assert sys.version_info >= (3,11); print(sys.executable)' 2>$null
  if($LASTEXITCODE -eq 0 -and $resolved){$selected=([string]($resolved|Select-Object -Last 1)).Trim();break}
 }catch{continue}
}
if(-not $selected){throw 'Python 3.11+ not found. Install Python or pass -Python with an existing executable path.'}
$Python=$selected
$windowless=Join-Path (Split-Path -Parent $Python) 'pythonw.exe'
if(Test-Path -LiteralPath $windowless -PathType Leaf){$Python=$windowless}
New-Item -ItemType Directory -Force -Path $destination|Out-Null
Get-ChildItem -LiteralPath $source -Recurse -File|ForEach-Object{
 $relative=$_.FullName.Substring($source.Length+1)
 if($relative -match '(^|\\)(\.[^\\]*|__pycache__|node_modules|venv|archive|archives|credentials|secrets)(\\|$)' -or $_.Extension -in @('.pyc','.sqlite3','.db','.log') -or ($_.Attributes -band [IO.FileAttributes]::ReparsePoint)){return}
 $target=Join-Path $destination $relative
 if($_.FullName -eq $target){return}
 New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target)|Out-Null
 Copy-Item -LiteralPath $_.FullName -Destination $target -Force
}
$menu=Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
New-Item -ItemType Directory -Force -Path $menu|Out-Null
$shell=New-Object -ComObject WScript.Shell
$linkPath=Join-Path $menu 'Local WorkOS.lnk'
$link=$shell.CreateShortcut($linkPath)
$link.TargetPath=$Python
$link.Arguments='"'+(Join-Path $destination 'launch.py')+'"'
$link.WorkingDirectory=$destination
# Neutral Windows application icon, independent of bundled legacy artwork.
$link.IconLocation=(Join-Path $env:SystemRoot 'System32\shell32.dll')+',0'
$link.Description='Local WorkOS local research workspace'
$link.WindowStyle=7
$link.Save()
$stop=$shell.CreateShortcut((Join-Path $menu 'Local WorkOS Stop.lnk'))
$stop.TargetPath=$Python
$stop.Arguments='"'+(Join-Path $destination 'launch.py')+'" --stop'
$stop.WorkingDirectory=$destination
$stop.IconLocation=$link.IconLocation
$stop.Save()
[pscustomobject]@{Installed=$destination;Shortcut=$linkPath;Target=$link.TargetPath;Arguments=$link.Arguments;Pinning='Pin manually using the Windows Start menu if desired.'}|ConvertTo-Json -Depth 4
