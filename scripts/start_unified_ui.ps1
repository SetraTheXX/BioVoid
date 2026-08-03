param(
    [string]$BindHost = "127.0.0.1",
    [int]$BindPort = 8000,
    [switch]$OpenBrowser,
    [switch]$AllowRemote
)

$ErrorActionPreference = "Stop"

if ($BindHost -notin @("127.0.0.1", "localhost", "::1") -and -not $AllowRemote) {
    throw "Refusing non-loopback bind. Re-run with -AllowRemote only behind an authenticated network boundary."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$apiScript = Join-Path $PSScriptRoot "run_phase6_api.py"

if (!(Test-Path $apiScript)) {
    throw "run_phase6_api.py not found: $apiScript"
}

$remoteArg = if ($AllowRemote) { " --allow-remote" } else { "" }
$cmdArgs = "scripts/run_phase6_api.py --host $BindHost --port $BindPort$remoteArg"
$process = Start-Process -FilePath python -ArgumentList $cmdArgs -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru

Start-Sleep -Seconds 2

$url = "http://$BindHost`:$BindPort/"
Write-Host "BioVoid canonical React interface started."
Write-Host "URL: $url"
Write-Host "PID: $($process.Id)"
Write-Host "Stop: Stop-Process -Id $($process.Id) -Force"

if ($OpenBrowser) {
    Start-Process $url | Out-Null
}
