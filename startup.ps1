<#!
.SYNOPSIS
Launch the local GoKaatru workflow app without Docker.

.DESCRIPTION
Starts the FastAPI web API and the Vite frontend in separate PowerShell windows.
Optionally starts the MCP SSE server for local debugging or external clients.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$IncludeMcp,
    [switch]$OpenBrowser,
    [switch]$InstallFrontendDeps
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSCommandPath
Set-Location $repoRoot

function Resolve-PythonExecutable {
    param(
        [string]$RootPath
    )

    $candidates = @(
        "C:\Users\NathishSeenivasagam\.conda\envs\gokaatru\python.exe",
        (Join-Path $env:USERPROFILE ".conda\envs\gokaatru\python.exe"),
        (Join-Path $RootPath ".venv\Scripts\python.exe")
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }

    throw "Could not find a Python interpreter for GoKaatru. Expected the conda env 'gokaatru' or .venv under the repo root."
}

function Resolve-NpmCommand {
    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($null -ne $npmCommand) {
        return $npmCommand.Source
    }

    throw "Could not find npm.cmd on PATH. Install Node.js 20+ and ensure npm.cmd is available."
}

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
    param(
        [string]$Title,
        [string]$CommandText
    )

    if (-not $PSCmdlet.ShouldProcess($Title, "Launch PowerShell window")) {
        return
    }

    $windowCommand = New-WindowCommand -Title $Title -WorkingDirectory $repoRoot -CommandText $CommandText
    Start-Process -FilePath "powershell.exe" -WorkingDirectory $repoRoot -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        $windowCommand
    ) | Out-Null
}

$pythonExe = Resolve-PythonExecutable -RootPath $repoRoot
$npmCmd = Resolve-NpmCommand
$frontendNodeModules = Join-Path $repoRoot "frontend\node_modules"

if ($InstallFrontendDeps -or -not (Test-Path $frontendNodeModules)) {
    if ($PSCmdlet.ShouldProcess("frontend dependencies", "Run npm install")) {
        & $npmCmd --prefix frontend install
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed with exit code $LASTEXITCODE"
        }
    }
}

$apiCommand = "& '$pythonExe' -m uvicorn server.api.main:app --reload --port 8000"
$frontendCommand = "& '$npmCmd' --prefix frontend run dev"
$mcpCommand = "& '$pythonExe' -m server.main --transport sse --host 0.0.0.0 --port 8080"

Start-GoKaatruWindow -Title "GoKaatru API" -CommandText $apiCommand
Start-GoKaatruWindow -Title "GoKaatru Frontend" -CommandText $frontendCommand

if ($IncludeMcp) {
    Start-GoKaatruWindow -Title "GoKaatru MCP SSE" -CommandText $mcpCommand
}

if ($OpenBrowser -and $PSCmdlet.ShouldProcess("browser", "Open workflow UI")) {
    Start-Process "http://127.0.0.1:5173" | Out-Null
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