$ErrorActionPreference = "Stop"

function Has-Command {
    param([string]$Name)
    return Get-Command $Name -ErrorAction SilentlyContinue
}

if (-not (Has-Command "wsl")) {
    Write-Host "WSL is recommended for running bash-based compose tests."
    Write-Host "You can also run the bash script from Git Bash: scripts/integration/compose_test_e2e.sh"
    exit 2
}

wsl bash scripts/integration/compose_test_e2e.sh
exit $LASTEXITCODE
