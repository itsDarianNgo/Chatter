$wslPath = Get-Command wsl -ErrorAction SilentlyContinue

if (-not $wslPath) {
  Write-Host "WSL is required to run this test from PowerShell." -ForegroundColor Yellow
  Write-Host "Install WSL, or run scripts/integration/e2e_botloop_test.sh via Git Bash." -ForegroundColor Yellow
  exit 2
}

$envVars = @("REDIS_CONTAINER", "WS_URL", "PERSONA_HTTP", "INGEST_STREAM", "FIREHOSE_STREAM", "ROOM_ID")
$envArgs = @()
foreach ($var in $envVars) {
  if ($env:$var) {
    $envArgs += "$var=$($env:$var)"
  }
}

$command = @("wsl")
if ($envArgs.Count -gt 0) {
  $command += "env"
  $command += $envArgs
}
$command += @("bash", "scripts/integration/e2e_botloop_test.sh")

& $command
exit $LASTEXITCODE
