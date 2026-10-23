$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

while ($true) {
    python main.py
    Write-Host "WeVibe exited. Restarting in 5 seconds..."
    Start-Sleep -Seconds 5
}
