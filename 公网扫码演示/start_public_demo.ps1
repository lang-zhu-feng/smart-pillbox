param([int]$Port = 18766)
$ErrorActionPreference = 'Stop'
$demoRoot = $PSScriptRoot
$logRoot = Join-Path $demoRoot 'logs'
$toolsRoot = Join-Path $demoRoot 'tools'
$pythonExe = 'C:\Users\liuzhanfei\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$qrPython = 'C:\Users\liuzhanfei\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$cloudExe = Join-Path $toolsRoot 'cloudflared.exe'
New-Item -ItemType Directory -Path $logRoot,$toolsRoot -Force | Out-Null
$env:PYTHONPATH = 'E:\学校课程\智慧城市\backend\.venv\Lib\site-packages'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:MEDGUARD_DB = Join-Path $demoRoot 'backend\data\public-demo.sqlite3'
& $pythonExe -c 'import fastapi,uvicorn; print("Backend runtime ready")'
if ($LASTEXITCODE -ne 0) { throw 'Cannot load the project backend runtime.' }

$healthy = $false
try { $healthy = (Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2).status -eq 'healthy' } catch {}
if (!$healthy) {
    $server = Start-Process -FilePath $pythonExe -ArgumentList @('-m','uvicorn','backend.main:app','--host','127.0.0.1','--port',"$Port",'--no-access-log') -WorkingDirectory $demoRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot 'server.out.log') -RedirectStandardError (Join-Path $logRoot 'server.err.log')
    @{serverPid=$server.Id;port=$Port} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $demoRoot 'processes.json') -Encoding UTF8
    for ($i=0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        try { $healthy = (Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2).status -eq 'healthy' } catch {}
        if ($healthy) { break }
    }
}
if (!$healthy) { throw ('Backend did not start. See ' + (Join-Path $logRoot 'server.err.log')) }
Write-Output 'Isolated backend is healthy.'

if (!(Test-Path -LiteralPath $cloudExe)) {
    Write-Output 'Downloading the official Cloudflare Tunnel client...'
    Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile $cloudExe -TimeoutSec 180 -UseBasicParsing
}
& $cloudExe --version
if ($LASTEXITCODE -ne 0) { throw 'Cloudflare Tunnel executable failed.' }
$tunnelLog = Join-Path $logRoot 'tunnel.err.log'
$publicUrl = $null
$linkPath = Join-Path $demoRoot 'public-link.json'
if (Test-Path -LiteralPath $linkPath) {
    $existingLink = Get-Content -LiteralPath $linkPath -Raw | ConvertFrom-Json
    $savedProcesses = Get-Content -LiteralPath (Join-Path $demoRoot 'processes.json') -Raw | ConvertFrom-Json
    if ($savedProcesses.tunnelPid -and (Get-Process -Id $savedProcesses.tunnelPid -ErrorAction SilentlyContinue)) { $publicUrl = $existingLink.origin }
    try {
        if ((Invoke-RestMethod -Uri ($existingLink.origin + '/health') -TimeoutSec 8).status -eq 'healthy') { $publicUrl = $existingLink.origin }
    } catch {}
}
if (!$publicUrl) {
    $tunnel = Start-Process -FilePath $cloudExe -ArgumentList @('--no-autoupdate','tunnel','--url',"http://127.0.0.1:$Port",'--protocol','http2','--edge-ip-version','4') -WorkingDirectory $demoRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot 'tunnel.out.log') -RedirectStandardError $tunnelLog
    $processes = Get-Content -LiteralPath (Join-Path $demoRoot 'processes.json') -Raw | ConvertFrom-Json
    $processes | Add-Member -NotePropertyName tunnelPid -NotePropertyValue $tunnel.Id -Force
    $processes | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $demoRoot 'processes.json') -Encoding UTF8
    for ($i=0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Path -LiteralPath $tunnelLog) {
            $match = [regex]::Match((Get-Content -LiteralPath $tunnelLog -Raw), 'https://[a-z0-9-]+\.trycloudflare\.com')
            if ($match.Success) { $publicUrl = $match.Value; break }
        }
        if ($tunnel.HasExited) { throw ('Public connection client exited. See ' + $tunnelLog) }
    }
}
if (!$publicUrl) { throw ('No public URL was returned. See ' + $tunnelLog) }
@{origin=$publicUrl;url=($publicUrl+'/preview');createdAt=(Get-Date).ToString('o');temporary=$true} | ConvertTo-Json | Set-Content -LiteralPath $linkPath -Encoding UTF8
Write-Output ('Public URL assigned: ' + $publicUrl + '/preview')

$publicHealthy = $false
for ($i=0; $i -lt 12; $i++) {
    try { $publicHealthy = (Invoke-RestMethod -Uri ($publicUrl + '/health') -TimeoutSec 8).status -eq 'healthy' } catch { if ($i -eq 0 -or $i -eq 11) { Write-Output ('Public check failed: ' + $_.Exception.Message) } }
    if ($publicHealthy) { break }
    Start-Sleep -Seconds 2
}
if (!$publicHealthy) { throw 'A URL was assigned, but the public health check has not passed. Do not distribute a QR code yet.' }
$preview = Invoke-WebRequest -Uri ($publicUrl + '/preview') -TimeoutSec 15 -UseBasicParsing
if ($preview.Content -notmatch 'demo-login') { throw 'The public URL does not show the intended preview page.' }
$session = Invoke-RestMethod -Uri ($publicUrl + '/api/auth/demo') -Method Post -ContentType 'application/json' -TimeoutSec 15
$state = Invoke-RestMethod -Uri ($publicUrl + '/api/state') -Headers @{Authorization=('Bearer ' + $session.token)} -TimeoutSec 15
if ($state.tasks.Count -ne 21) { throw 'The demo state did not contain 21 pillbox compartments.' }
Write-Output 'Public preview, guest login and 21-compartment state verified.'

# The QR renderer uses the bundled artifact runtime; project packages are not needed.
$env:PYTHONPATH = ''
& $qrPython (Join-Path $demoRoot 'make_qr.py')
if ($LASTEXITCODE -ne 0) { throw 'QR image generation failed.' }
& 'C:\Users\liuzhanfei\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' (Join-Path $demoRoot 'verify_public_demo.cjs')
if ($LASTEXITCODE -ne 0) { throw 'Mobile browser verification failed. Check the public-demo logs.' }
Write-Output 'Ready. Keep the computer online and awake while the QR code is in use.'
