param(
    [string]$BindHost = "127.0.0.1",
    [int]$BindPort = 8000,
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$apiScript = Join-Path $PSScriptRoot "run_phase6_api.py"

if (!(Test-Path $apiScript)) {
    throw "run_phase6_api.py not found: $apiScript"
}

$cmdArgs = "scripts/run_phase6_api.py --host $BindHost --port $BindPort"
$process = Start-Process -FilePath python -ArgumentList $cmdArgs -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru

Start-Sleep -Seconds 2

$url = "http://$BindHost`:$BindPort/portal"
Write-Host "BioVoid unified portal started."
Write-Host "URL: $url"
Write-Host "PID: $($process.Id)"
Write-Host "Stop: Stop-Process -Id $($process.Id) -Force"

if ($OpenBrowser) {
    Start-Process $url | Out-Null
}
