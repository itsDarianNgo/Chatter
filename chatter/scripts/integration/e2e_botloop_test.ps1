$wsl = Get-Command wsl -ErrorAction SilentlyContinue
if (-not $wsl) {
    Write-Host "WSL is required to run this test from PowerShell. Install WSL or run the .sh via Git Bash." -ForegroundColor Yellow
    exit 2
}

$envList = @("REDIS_CONTAINER", "WS_URL", "PERSONA_HTTP", "INGEST_STREAM", "FIREHOSE_STREAM", "ROOM_ID")
$envExport = ""
foreach ($name in $envList) {
    $value = [System.Environment]::GetEnvironmentVariable($name)
    if ($value) {
        $envExport += "$name=$value "
    }
}

$command = "$envExport bash scripts/integration/e2e_botloop_test.sh"
wsl $command
exit $LASTEXITCODE
