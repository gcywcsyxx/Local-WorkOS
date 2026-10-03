param(
 [Parameter(Mandatory=$true)][string]$Python,
 [string]$CommitMessage='',
 [switch]$Publish,
 [switch]$Push
)
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
function Run-Checked([string]$Executable,[string[]]$Arguments){
 & $Executable @Arguments
 if($LASTEXITCODE -ne 0){throw ('Command failed: '+$Executable+' '+($Arguments -join ' '))}
}
if($Push -and -not $Publish){throw '-Push requires -Publish and successful deployment checks.'}
$resolved=Get-Command $Python -CommandType Application -ErrorAction Stop
$Python=$resolved.Source
$env:PYTHONPATH=Join-Path $repo 'vendor'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:WORKOS_TEST_PYTHON=$Python
Run-Checked $Python @('-m','unittest','discover','-s','tests')
Run-Checked 'node' @('tests/test_markdown.cjs')
Run-Checked 'node' @('tests/browser_auth_client.cjs')
Run-Checked 'node' @('tests/browser_research_cdp.cjs')
if($CommitMessage){Run-Checked 'git' @('add','-A')}
Run-Checked $Python @('tools/check_public_privacy.py','--history')
if($CommitMessage){
 & git diff --cached --quiet
 if($LASTEXITCODE -eq 1){Run-Checked 'git' @('commit','-m',$CommitMessage)}
 elseif($LASTEXITCODE -ne 0){throw 'Cannot inspect staged changes.'}
}
if(-not $Publish){Write-Output 'Validation passed. Use -Publish for an authorized deployment.';return}
$dirty=@(& git status --porcelain)
if($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0){throw 'Commit the reviewed source before publishing.'}
$revision=([string](& git rev-parse HEAD)).Trim()
$version=([string](& $Python -c 'from workos import __version__; print(__version__)')).Trim()
if($LASTEXITCODE -ne 0){throw 'Cannot read application version.'}
if($Push){
 $branch=([string](& git branch --show-current)).Trim()
 if($branch -ne 'main'){throw 'This publication SOP pushes main only. Review other branch releases separately.'}
 Run-Checked 'git' @('fetch','origin','main')
 Run-Checked 'git' @('merge-base','--is-ancestor','origin/main','HEAD')
}
# Online SQLite backup includes WAL transactions; authentication and originals stay in place.
Run-Checked $Python @('tools/release_backup.py')
Run-Checked $Python @('launch.py','--stop')
$deadline=[DateTime]::UtcNow.AddSeconds(15)
do{
 try{Invoke-RestMethod 'http://127.0.0.1:18866/api/health' -TimeoutSec 2|Out-Null;Start-Sleep -Milliseconds 200}
 catch{break}
 if([DateTime]::UtcNow -ge $deadline){throw 'The existing app did not stop. No installation was attempted.'}
}while($true)
$installation=& (Join-Path $PSScriptRoot 'install.ps1') -Python $Python | ConvertFrom-Json
$installed=$installation.Installed
if(-not $installed -or -not (Test-Path -LiteralPath (Join-Path $installed 'launch.py'))){throw 'Installation did not return a usable build directory.'}
# The starter loads the already configured dedicated tunnel and reuses its existing process.
$publicMode=[Environment]::GetEnvironmentVariable('WORKOS_PUBLIC_AUTH_MODE','User')
$publicOrigin=[Environment]::GetEnvironmentVariable('WORKOS_PUBLIC_ORIGIN','User')
if($env:WORKOS_PUBLIC_AUTH_MODE){$publicMode=$env:WORKOS_PUBLIC_AUTH_MODE}
if($env:WORKOS_PUBLIC_ORIGIN){$publicOrigin=$env:WORKOS_PUBLIC_ORIGIN}
if($publicMode -eq 'password' -and $publicOrigin){
 Run-Checked $Python @((Join-Path $installed 'tools/start_public.py'))
}else{Run-Checked $Python @((Join-Path $installed 'launch.py'),'--no-browser')}
$health=Invoke-RestMethod 'http://127.0.0.1:18866/api/health' -TimeoutSec 10
if($health.version -ne $version -or $health.source_revision -ne $revision){throw 'The running service does not match the published commit.'}
$sync=Invoke-RestMethod 'http://127.0.0.1:18866/api/sync/status' -TimeoutSec 10
if($sync.enabled -and $sync.error){throw 'Mirror synchronization reported an error.'}
Run-Checked $Python @('tools/release_verify.py')
Run-Checked $Python @('tools/release_mirror_source.py')
if($Push){
 Run-Checked 'git' @('push','origin','main')
 $remote=([string](& git ls-remote origin refs/heads/main)).Split("`t")[0].Trim()
 if($LASTEXITCODE -ne 0 -or $remote -ne $revision){throw 'Remote main did not match the deployed revision.'}
}
Write-Output ('Released '+$version+' at '+$revision+'; local and configured public entry verified.')
