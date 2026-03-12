[CmdletBinding()]
param(
    [switch]$Demo,
    [switch]$Reset,
    [int]$TimeoutSeconds = 90
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-CommandAvailable {
    param([Parameter(Mandatory = $true)][string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found in PATH."
    }
}

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
        $delaySeconds = [Math]::Min($delaySeconds * 2, 15)
    }

    throw "Simulator health check failed for $Uri after $attempt attempts."
}

Assert-CommandAvailable -Name "docker"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

Push-Location $repoRoot
try {
    docker compose up -d --build sim | Out-Host
    Wait-ForSimulatorHealth -Uri "http://127.0.0.1:8080/healthz" -TimeoutSeconds $TimeoutSeconds

    if ($Reset -or $Demo) {
        Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8080/reset" -TimeoutSec 5 | Out-Null
    }

    if ($Demo) {
        docker compose exec -T sim python -m cli_device_sim demo-client --ssh-host 127.0.0.1 --ssh-port 2222 --api-url http://127.0.0.1:8080 | Out-Host
    }
    else {
        Write-Host "Simulator is healthy."
        Write-Host "SSH endpoint: ssh operator@127.0.0.1 -p 2222"
        Write-Host "REST endpoint: http://127.0.0.1:8080/state"
    }
}
finally {
    Pop-Location
}
