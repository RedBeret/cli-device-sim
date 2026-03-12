[CmdletBinding()]
param(
    [int]$TimeoutSeconds = 60
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Wait-ForSimulatorHealth {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds
    )

    $attempt = 0
    $delaySeconds = 1
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    while ((Get-Date) -lt $deadline) {
        $attempt++
        try {
            $response = Invoke-RestMethod -Method Get -Uri $Uri -TimeoutSec 3
            if ($response.status -eq "ok") {
                return
            }
        }
        catch {
        }

        Start-Sleep -Seconds $delaySeconds
        $delaySeconds = [Math]::Min($delaySeconds * 2, 10)
    }

    throw "Simulator health check failed for $Uri after $attempt attempts."
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Required command 'docker' was not found in PATH."
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
    Wait-ForSimulatorHealth -Uri "http://127.0.0.1:8080/healthz" -TimeoutSeconds $TimeoutSeconds
    docker compose exec -T sim python -m cli_device_sim demo-client --probe-only --ssh-host 127.0.0.1 --ssh-port 2222 --api-url http://127.0.0.1:8080 | Out-Host
}
finally {
    Pop-Location
}
