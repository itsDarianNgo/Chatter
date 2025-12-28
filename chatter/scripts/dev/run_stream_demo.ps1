$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repoRoot

if ($args -contains "--help" -or $args -contains "-h") {
  Write-Host "Usage: powershell -ExecutionPolicy Bypass -File scripts/dev/run_stream_demo.ps1 [--llm]"
  Write-Host "Starts the compose stack, publishers, and observation tailer."
  Write-Host "  --llm  Enable LiteLLM-backed persona/perceptor (requires .env.local or env vars)."
  exit 0
}

$useLlm = $false
if ($args -contains "--llm") {
  $useLlm = $true
}
if ($env:DEV_LLM -eq "1") {
  $useLlm = $true
}

function Require-Command {
  param([string]$Name, [string]$Hint)
  $cmd = Get-Command $Name -ErrorAction SilentlyContinue
  if (-not $cmd) {
    Write-Host "FAIL: missing dependency '$Name' on PATH."
    if ($Hint) {
      Write-Host $Hint
    }
    return $false
  }
  return $true
}

if (-not (Require-Command -Name "docker" -Hint "Install Docker Desktop and ensure 'docker' is available.")) {
  exit 2
}

$pythonBin = "python"
if (-not (Get-Command $pythonBin -ErrorAction SilentlyContinue)) {
  if (Get-Command "python3" -ErrorAction SilentlyContinue) {
    $pythonBin = "python3"
  } else {
    Write-Host "FAIL: missing dependency 'python' on PATH."
    exit 2
  }
}

if (-not (Require-Command -Name "node" -Hint "Install Node.js to run the observation tailer.")) {
  exit 2
}

if ($env:REDIS_URL_HOST) {
  $redisUrl = $env:REDIS_URL_HOST
} elseif ($env:REDIS_URL) {
  $redisUrl = $env:REDIS_URL
  $env:REDIS_URL_HOST = $redisUrl
} else {
  $redisUrl = "redis://127.0.0.1:6379/0"
  $env:REDIS_URL_HOST = $redisUrl
}

Write-Host "Using Redis URL: $redisUrl"
if ($useLlm) {
  $envPath = Join-Path $repoRoot ".env.local"
  if (Test-Path $envPath) {
    Get-Content $envPath | ForEach-Object {
      $line = $_.Trim()
      if (-not $line -or $line.StartsWith("#")) { return }
      $parts = $line -split "=", 2
      if ($parts.Length -ne 2) { return }
      $name = $parts[0].Trim()
      $value = $parts[1].Trim().Trim('"').Trim("'")
      if ($name) {
        $env:$name = $value
      }
    }
  }

  if (-not $env:LITELLM_BASE_URL -and -not $env:LLM_BASE_URL) {
    Write-Host "FAIL: missing LITELLM_BASE_URL (or LLM_BASE_URL) for --llm."
    exit 2
  }
  if (-not $env:LITELLM_API_KEY -and -not $env:OPENAI_API_KEY -and -not $env:LLM_API_KEY) {
    Write-Host "FAIL: missing LITELLM_API_KEY (or OPENAI_API_KEY/LLM_API_KEY) for --llm."
    exit 2
  }
  if (-not $env:PERSONA_LLM_MODEL -and -not $env:LLM_MODEL) {
    Write-Host "FAIL: missing PERSONA_LLM_MODEL (or LLM_MODEL) for --llm."
    exit 2
  }
  if (-not $env:PERCEPTOR_VISION_MODEL -and -not $env:PERCEPTOR_LLM_MODEL) {
    Write-Host "WARN: PERCEPTOR_VISION_MODEL not set; stream_perceptor will reuse the persona model."
  }
}
Write-Host "Starting compose stack..."
$composeArgs = @("-f", "docker-compose.yml", "-f", "docker-compose.test.yml")
if ($useLlm) {
  $composeArgs += @("-f", "docker-compose.local.yml")
}
& docker compose @composeArgs up -d --build
if ($LASTEXITCODE -ne 0) {
  Write-Host "FAIL: docker compose up failed."
  exit $LASTEXITCODE
}

function Wait-ForHealth {
  param([string]$Url, [string]$Name, [int]$TimeoutS, [int]$SleepMs)
  $start = Get-Date
  while (((Get-Date) - $start).TotalSeconds -lt $TimeoutS) {
    try {
      $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
      if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300) {
        Write-Host "$Name healthy"
        return $true
      }
    } catch {
      Start-Sleep -Milliseconds $SleepMs
      continue
    }
    Start-Sleep -Milliseconds $SleepMs
  }
  Write-Host "FAIL: $Name did not become healthy within ${TimeoutS}s"
  return $false
}

$timeoutS = 45
if ($env:TIMEOUT_S) {
  $parsedTimeout = 0
  if ([int]::TryParse($env:TIMEOUT_S, [ref]$parsedTimeout) -and $parsedTimeout -gt 0) {
    $timeoutS = $parsedTimeout
  }
}

$sleepS = 0.5
if ($env:SLEEP_S) {
  $parsedSleep = 0.0
  if ([double]::TryParse($env:SLEEP_S, [ref]$parsedSleep) -and $parsedSleep -gt 0) {
    $sleepS = $parsedSleep
  }
}
$sleepMs = [int]($sleepS * 1000)

if (-not (Wait-ForHealth -Url "http://localhost:8080/healthz" -Name "gateway" -TimeoutS $timeoutS -SleepMs $sleepMs)) {
  exit 1
}
if (-not (Wait-ForHealth -Url "http://localhost:8090/healthz" -Name "persona_workers" -TimeoutS $timeoutS -SleepMs $sleepMs)) {
  exit 1
}
if (-not (Wait-ForHealth -Url "http://localhost:8100/healthz" -Name "stream_perceptor" -TimeoutS $timeoutS -SleepMs $sleepMs)) {
  exit 1
}

$fixturePath = "fixtures/stream/frame_fixture_1.png"
$frameArgs = @("scripts/capture/publish_frames.py", "--room-id", "room:demo", "--interval-ms", "1500", "--mode", "screen", "--redis-url", $redisUrl)
$hasMss = $false
try {
  & $pythonBin -c "import mss" *> $null
  if ($LASTEXITCODE -eq 0) {
    $hasMss = $true
  }
} catch {
  $hasMss = $false
}

if (-not $hasMss) {
  if (Test-Path $fixturePath) {
    Write-Host "mss not available; using fixture file mode."
    $frameArgs = @(
      "scripts/capture/publish_frames.py",
      "--room-id", "room:demo",
      "--interval-ms", "1500",
      "--mode", "file",
      "--file", $fixturePath,
      "--redis-url", $redisUrl
    )
  } else {
    Write-Host "FAIL: missing mss and fixture image ($fixturePath)."
    Write-Host "HINT: install mss (pip install mss) or add the fixture file."
    exit 2
  }
}

$frameProc = $null
$tailProc = $null

function Stop-Demo {
  Write-Host "Stopping demo..."
  foreach ($proc in @($frameProc, $tailProc)) {
    if ($proc -and -not $proc.HasExited) {
      Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
  }
}

$exitCode = 0
try {
  Write-Host "Starting frame publisher..."
  $frameProc = Start-Process -FilePath $pythonBin -ArgumentList $frameArgs -NoNewWindow -PassThru

  Write-Host "Starting observation tailer..."
  $tailArgs = @("scripts/dev/tail_observations.mjs", "--room-id", "room:demo", "--redis-url", $redisUrl, "--since", "now")
  $tailProc = Start-Process -FilePath "node" -ArgumentList $tailArgs -NoNewWindow -PassThru

  Write-Host "Type transcript lines (Ctrl+C to stop):"
  & $pythonBin scripts/capture/publish_transcripts.py --room-id room:demo --mode stdin --redis-url $redisUrl
  $exitCode = $LASTEXITCODE
} finally {
  Stop-Demo
}

exit $exitCode
