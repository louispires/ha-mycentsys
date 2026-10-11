<#
.SYNOPSIS
    Copies the MyCentsys app service token from the mcr-cli config into the
    Home Assistant integration folder.

.EXAMPLE
    .\import-service-token.ps1 -Destination \\homeassistant\config\custom_components\mycentsys
#>
[CmdletBinding()]
param(
    [string]$Source = (Join-Path $PSScriptRoot '..\..\mcr-cli\appsettings.local.json'),
    [Parameter(Mandatory)][string]$Destination
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $Source)) {
    throw "Source config not found: $Source"
}
if (-not (Test-Path $Destination)) {
    throw "Destination folder not found: $Destination"
}

$config = Get-Content $Source -Raw | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($config.ServiceLevelJwt)) {
    throw "ServiceLevelJwt is missing from $Source"
}

$target = Join-Path $Destination 'service_token.json'
[ordered]@{ ServiceLevelJwt = $config.ServiceLevelJwt } |
    ConvertTo-Json |
    Set-Content -Path $target -Encoding utf8

Write-Host "Wrote $target"
Write-Host 'Restart Home Assistant, then add the MyCentsys Remote integration.'
