param([switch]$Lan, [switch]$NoBrowser, [int]$Port = 8766)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
$venvRoot = Join-Path $PSScriptRoot '.venv'
$venvPython = Join-Path $venvRoot 'Scripts\python.exe'
$pythonExe = $venvPython
$configPath = Join-Path $venvRoot 'pyvenv.cfg'
# A copied venv may still point to its old folder. Run its recorded base interpreter
# with the existing site-packages rather than installing packages unnecessarily.
if (Test-Path -LiteralPath $configPath) {
  $homeLine = Get-Content -LiteralPath $configPath | Where-Object { $_ -match '^home\s*=' } | Select-Object -First 1
  if ($homeLine) {
    $baseHome = ($homeLine -split '=', 2)[1].Trim()
    $basePython = Join-Path $baseHome 'python.exe'
    if (Test-Path -LiteralPath $basePython) { $pythonExe = $basePython; $env:PYTHONPATH = Join-Path $venvRoot 'Lib\site-packages' }
  }
}
if (!(Test-Path -LiteralPath $pythonExe)) { throw 'Missing backend Python environment. See backend/README.md.' }
$env:PYTHONDONTWRITEBYTECODE = '1'
$listenAddress = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }
$previewUrl = "http://127.0.0.1:$Port/preview"
Write-Host "Preview: $previewUrl"
try {
    $existing = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
    if ($existing.status -eq 'healthy' -and $existing.storage -eq 'sqlite' -and $existing.hardwareRequired -eq $false) {
      if (!$Lan) {
        Write-Host 'Local demo server is already running.'
        if (!$NoBrowser) { Start-Process $previewUrl }
        return
      }
      $lanListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalAddress -in @('0.0.0.0', '::') }
      if ($lanListener) {
        Write-Host 'LAN demo server is already running.'
        if (!$NoBrowser) { Start-Process $previewUrl }
        return
      }
      Write-Host 'A local-only server is already running. Stop that server, then restart this LAN launcher.'
      return
    }
} catch {}
if ($Lan) {
  Write-Host 'LAN mode: use this computer LAN IP in the mini-program and device settings.'
  foreach ($adapter in [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()) {
    if ($adapter.OperationalStatus -ne 'Up') { continue }
    $properties = $adapter.GetIPProperties()
    if ($properties.GatewayAddresses.Count -eq 0) { continue }
    foreach ($address in $properties.UnicastAddresses) {
      if ($address.Address.AddressFamily -eq 'InterNetwork' -and !$address.Address.ToString().StartsWith('169.254.')) {
        Write-Host "Phone backend: http://$($address.Address):$Port"
      }
    }
  }
}
if (!$NoBrowser) {
  $browserScript = "Start-Sleep -Seconds 3; Start-Process '$previewUrl'"
  $windowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
  Start-Process $windowsPowerShell -WindowStyle Hidden -ArgumentList @('-NoProfile', '-Command', $browserScript)
}
& $pythonExe -m uvicorn backend.main:app --host $listenAddress --port $Port
if ($LASTEXITCODE -ne 0) { throw 'Server exited. Check whether this port is already in use.' }
