param([switch]$VerifyOnly)
$ErrorActionPreference='Stop'
if(-not [Environment]::Is64BitOperatingSystem){throw 'Windows x64 is required.'}
if(-not $VerifyOnly -and -not (Get-Command codex -ErrorAction SilentlyContinue)){throw 'Install and sign in to the Windows Codex CLI first, then retry.'}
[Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$version='0.2.1'
$expectedHash='0bbc33dcd83236986bf7dc4fd975662cb9fee9d9a8ab1e878948fea33b3c3cb9'
$url='https://github.com/2428575943/codex-usage-dashboard/releases/download/quota-guard-v'+$version+'/codex-quota-guard-'+$version+'-setup.exe'
$downloadPath=Join-Path ([IO.Path]::GetTempPath()) ('codex-quota-guard-'+[Guid]::NewGuid().ToString('N')+'.exe')
try {
    Write-Host 'Downloading Codex Quota Guard (includes Python runtime)...'
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $downloadPath
    if((Get-FileHash -LiteralPath $downloadPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash){throw 'Installer SHA-256 mismatch. Nothing was installed.'}
    if($VerifyOnly){Write-Host 'Download and SHA-256 verified. VerifyOnly: nothing installed.';return}
    $installer=Start-Process -FilePath $downloadPath -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOSTART') -PassThru -WindowStyle Hidden
    $installer.WaitForExit()
    if($installer.ExitCode -ne 0){throw ('Installer failed: '+$installer.ExitCode)}
    $appRoot=Join-Path $env:LOCALAPPDATA 'Programs\CodexQuotaGuard'
    $pythonExe=Join-Path $appRoot 'python\python.exe'
    $codexHomePath=if($env:CODEX_HOME){$env:CODEX_HOME}else{Join-Path $env:USERPROFILE '.codex'}
    $statePath=Join-Path $env:LOCALAPPDATA 'CodexQuotaGuard'
    # Register independently of any desktop model cache. Never write a trust approval.
    $registerCode='import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import hook_manager;hook_manager.install(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]))'
    & $pythonExe -X utf8 -c $registerCode $appRoot $codexHomePath $statePath
    if($LASTEXITCODE -ne 0){throw 'Hook registration failed.'}
    Start-Process -FilePath (Join-Path $appRoot 'CodexQuotaGuard.exe') -ArgumentList '--background' -WindowStyle Hidden | Out-Null
    Write-Host 'Installed. In Codex CLI, enter /hooks and review the quota/model check once.'
    Write-Host 'Checks apply before submissions, including existing chats. Internal requests in an active turn are outside this check.'
} finally {
    if(Test-Path -LiteralPath $downloadPath){Remove-Item -LiteralPath $downloadPath}
}
