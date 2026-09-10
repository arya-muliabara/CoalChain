param([switch]$Demo, [int]$ApiPort = 8000, [int]$WebPort = 5173)
$ErrorActionPreference = 'Stop'
if ($ApiPort -ne 8000) { throw 'Frontend proxy uses port 8000. Use the default ApiPort or update vite.config.ts.' }
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runtimeRoot = Join-Path $env:LOCALAPPDATA 'MOne-CoalChain/dev'
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
$pythonPath = Join-Path $runtimeRoot 'venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    & py -m venv (Join-Path $runtimeRoot 'venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment setup failed.' }
}
& $pythonPath -m pip install -r (Join-Path $repoRoot 'backend/requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
foreach ($name in @('src','public')) {
    Copy-Item -LiteralPath (Join-Path $repoRoot $name) -Destination $runtimeRoot -Recurse -Force
}
foreach ($name in @('package.json','package-lock.json','tsconfig.json','vite.config.ts','index.html')) {
    Copy-Item -LiteralPath (Join-Path $repoRoot $name) -Destination $runtimeRoot -Force
}
Push-Location $runtimeRoot
try {
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    $env:DATABASE_URL = 'sqlite:///' + ((Join-Path $runtimeRoot 'local.db').Replace('\','/'))
    $env:MCMS_STORAGE = Join-Path $runtimeRoot 'storage'
    $env:PYTHONPATH = Join-Path $repoRoot 'backend'
    $env:MCMS_SECURE_COOKIE = 'false'
    $env:MCMS_DEMO = if ($Demo) { 'true' } else { 'false' }
    if ($Demo) {
        $env:MCMS_ADMIN_PASSWORD = 'CoalChain-Local-2026!'
        $env:MCMS_DEMO_PASSWORD = 'CoalChain-Local-2026!'
    } elseif (-not $env:MCMS_ADMIN_PASSWORD) {
        $securePassword = Read-Host 'Admin password (minimum 12 characters)' -AsSecureString
        $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
        try { $env:MCMS_ADMIN_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer) }
    }
    if ($env:MCMS_ADMIN_PASSWORD.Length -lt 12) { throw 'Admin password must contain at least 12 characters.' }
    $apiLog = Join-Path $runtimeRoot 'api.log'
    $apiError = Join-Path $runtimeRoot 'api-error.log'
    $apiProcess = Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port',"$ApiPort") -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $apiLog -RedirectStandardError $apiError -PassThru
    try {
        $ready = $false
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            if ($apiProcess.HasExited) { throw "API stopped. Read $apiError" }
            try { Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/health" | Out-Null; $ready = $true; break }
            catch { Start-Sleep -Seconds 1 }
        }
        if (-not $ready) { throw "API did not become ready. Read $apiError" }
        Write-Host "Open http://127.0.0.1:$WebPort"
        Write-Host 'Admin email: admin@coalchain.local'
        if ($Demo) { Write-Host 'Local demo password: CoalChain-Local-2026!' }
        Write-Host 'Press Ctrl+C to stop. Rerun this script after changing frontend source files.'
        & npm.cmd run dev -- --port $WebPort --strictPort
    } finally {
        if ($apiProcess -and -not $apiProcess.HasExited) {
            # This process and its Python child belong to this launcher.
            Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $apiProcess.Id -and $_.Name -eq 'python.exe' } | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
            Stop-Process -Id $apiProcess.Id -ErrorAction SilentlyContinue
        }
    }
} finally { Pop-Location }

