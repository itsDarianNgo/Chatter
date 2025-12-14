$wsl = Get-Command wsl -ErrorAction SilentlyContinue
if ($null -ne $wsl) {
  wsl bash scripts/integration/e2e_memory_test.sh
  exit $LASTEXITCODE
}
Write-Host "WSL not found. Please run scripts/integration/e2e_memory_test.sh via Git Bash or WSL."
exit 2
