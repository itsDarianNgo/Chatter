Param()

if (Get-Command wsl -ErrorAction SilentlyContinue) {
    wsl bash scripts/integration/e2e_firehose_ws_test.sh
} else {
    Write-Host "WSL not detected. Please run scripts/integration/e2e_firehose_ws_test.sh from a bash shell." -ForegroundColor Yellow
    exit 1
}
