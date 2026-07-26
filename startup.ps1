<#!
.SYNOPSIS
Launch the local GoKaatru backend services without Docker.

.DESCRIPTION
Starts the FastAPI web API in a separate PowerShell window.
Optionally starts the MCP SSE server for local debugging or external clients.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$IncludeMcp
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
        (Join-Path $RootPath ".venv\Scripts\python.exe"),
        (Join-Path $env:LOCALAPPDATA "python\bin\python.exe")
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }

    throw "Could not find a Python interpreter for GoKaatru. Expected the conda env 'gokaatru' or .venv under the repo root."
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
    [CmdletBinding(SupportsShouldProcess = $true)]
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

$apiCommand = "& '$pythonExe' -m uvicorn server.api.main:app --reload --port 8000"
$mcpCommand = "& '$pythonExe' -m server.main --transport sse --host 0.0.0.0 --port 8080"

Start-GoKaatruWindow -Title "GoKaatru API" -CommandText $apiCommand

if ($IncludeMcp) {
    Start-GoKaatruWindow -Title "GoKaatru MCP SSE" -CommandText $mcpCommand
}

Write-Host "Launched GoKaatru local development windows." -ForegroundColor Green
Write-Host "Web API:      http://127.0.0.1:8000/api"

if ($IncludeMcp) {
    Write-Host "MCP SSE:      http://127.0.0.1:8080/sse"
}
else {
    Write-Host "MCP SSE:      not started (use -IncludeMcp to enable it)"
}