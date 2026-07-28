<#!
.SYNOPSIS
Launch the local GoKaatru stack (backend API + frontend) without Docker.

.DESCRIPTION
Starts three things in separate PowerShell windows:
  - FastAPI web API on http://127.0.0.1:8000  (the frontend talks to this)
  - Vite frontend dev server on http://127.0.0.1:5173  (proxies /api -> :8000)
  - (optional) MCP SSE server on http://127.0.0.1:8080  (for external MCP clients)

Python and Node are resolved from PATH first, then from common fallback
locations (.venv, conda env "gokaatru"). No hardcoded user paths.

.PARAMETER IncludeMcp
Also start the MCP SSE server (not needed for the browser app).

.PARAMETER InstallFrontendDeps
Run `npm install` in frontend/ before starting the dev server if node_modules
is missing.

.EXAMPLE
.\startup.ps1                  # API + frontend
.\startup.ps1 -IncludeMcp      # API + frontend + MCP SSE
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$IncludeMcp,
    [switch]$InstallFrontendDeps
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSCommandPath
Set-Location $repoRoot

# ---------------------------------------------------------------------------
# Tool resolution — PATH first, then fallbacks. No hardcoded usernames.
# ---------------------------------------------------------------------------

function Resolve-PythonExecutable {
    param([string]$RootPath)

    # 1. Active virtualenv (.venv) in the repo.
    $venvPython = Join-Path $RootPath ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) { return $venvPython }

    # 2. A named conda env "gokaatru" under the user profile (portable path).
    $condaPython = Join-Path $env:USERPROFILE ".conda\envs\gokaatru\python.exe"
    if (Test-Path $condaPython) { return $condaPython }

    # 3. Whatever `python` resolves to on PATH.
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $cmd) { return $cmd.Source }

    # 4. Common Windows Python launcher location.
    $launcherPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"
    if (Test-Path $launcherPython) { return $launcherPython }

    throw "Could not find a Python interpreter. Activate a venv/conda env or add python to PATH."
}

function Resolve-NpmCommand {
    # Prefer npm.cmd (Windows shim); fall back to npm.
    $cmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($null -ne $cmd) { return $cmd.Source }
    $cmd = Get-Command npm -ErrorAction SilentlyContinue
    if ($null -ne $cmd) { return $cmd.Source }
    throw "Could not find npm. Install Node.js 20+ and ensure npm is on PATH."
}

# ---------------------------------------------------------------------------
# Window helpers
# ---------------------------------------------------------------------------

function New-WindowCommand {
    param(
        [string]$Title,
        [string]$WorkingDirectory,
        [string]$CommandText
    )
    $escapedTitle = $Title.Replace("'", "''")
    $escapedWorkingDirectory = $WorkingDirectory.Replace("'", "''")
    return "$Host.UI.RawUI.WindowTitle = '$escapedTitle'; Set-Location '$escapedWorkingDirectory'; $CommandText"
}

function Start-GoKaatruWindow {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [string]$Title,
        [string]$CommandText
    )
    if (-not $PSCmdlet.ShouldProcess($Title, "Launch PowerShell window")) { return }
    $windowCommand = New-WindowCommand -Title $Title -WorkingDirectory $repoRoot -CommandText $CommandText
    Start-Process -FilePath "powershell.exe" -WorkingDirectory $repoRoot -ArgumentList @(
        "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $windowCommand
    ) | Out-Null
}

# ---------------------------------------------------------------------------
# Resolve tools
# ---------------------------------------------------------------------------

$pythonExe = Resolve-PythonExecutable -RootPath $repoRoot
$npmCmd = Resolve-NpmCommand
$frontendNodeModules = Join-Path $repoRoot "frontend\node_modules"

# Optionally install frontend deps if missing (or on explicit request).
if (($InstallFrontendDeps -or -not (Test-Path $frontendNodeModules)) -and $PSCmdlet.ShouldProcess("frontend dependencies", "Run npm install")) {
    Write-Host "Installing frontend dependencies..." -ForegroundColor Cyan
    & $npmCmd --prefix frontend install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed with exit code $LASTEXITCODE" }
}

# ---------------------------------------------------------------------------
# Build the commands and launch
# ---------------------------------------------------------------------------

$apiCommand = "& '$pythonExe' -m uvicorn server.api.main:app --reload --port 8000"
$frontendCommand = "& '$npmCmd' --prefix frontend run dev"
$mcpCommand = "& '$pythonExe' -m server.main --transport sse --host 0.0.0.0 --port 8080"

Start-GoKaatruWindow -Title "GoKaatru API" -CommandText $apiCommand
Start-GoKaatruWindow -Title "GoKaatru Frontend" -CommandText $frontendCommand
if ($IncludeMcp) {
    Start-GoKaatruWindow -Title "GoKaatru MCP SSE" -CommandText $mcpCommand
}

Write-Host "Launched GoKaatru local development windows." -ForegroundColor Green
Write-Host "Workflow UI:  http://127.0.0.1:5173"
Write-Host "Web API:      http://127.0.0.1:8000/api"
if ($IncludeMcp) {
    Write-Host "MCP SSE:      http://127.0.0.1:8080/sse"
}
else {
    Write-Host "MCP SSE:      not started (use -IncludeMcp to enable it)"
}
