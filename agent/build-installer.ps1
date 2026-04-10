#requires -Version 5.1
<#
.SYNOPSIS
    Publica GeoHelper, gera payload.zip + InstallSettings.json e compila CadeVoceAgent-Setup.exe.

.DESCRIPTION
    Os valores de API e intervalo ficam embutidos no .exe (InstallSettings.json como recurso).
    Execucao silenciosa: duplo clique no instalador; sem janelas (WinExe + install-task oculto).

.PARAMETER ApiUrl
    URL base da API (ex.: https://api.exemplo.com).

.PARAMETER ApiKey
    Chave de autenticacao.

.PARAMETER IntervalMinutes
    Intervalo do check-in agendado (1-1439). Padrao: 10.

.PARAMETER SkipGeoPublish
    Nao executa dotnet publish no GeoHelper (usa publish existente).

.PARAMETER EstadoPermitido
    UF (ou codigo de regiao) para cadastro automatico do notebook em POST /devices. Padrao: SP.

.EXAMPLE
    .\build-installer.ps1 -ApiUrl 'https://cadevoce.exemplo.com' -ApiKey 'segredo' -IntervalMinutes 15 -EstadoPermitido 'SP'
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$ApiUrl,
    [Parameter(Mandatory = $true)]
    [string]$ApiKey,
    [ValidateRange(1, 1439)]
    [int]$IntervalMinutes = 10,
    [string]$EstadoPermitido = 'SP',
    [switch]$SkipGeoPublish
)

$ErrorActionPreference = 'Stop'
$AgentDir = $PSScriptRoot
$InstallerDir = Join-Path $AgentDir 'Installer'
$OutZip = Join-Path $InstallerDir 'payload.zip'
$SettingsPath = Join-Path $InstallerDir 'InstallSettings.json'

if (-not $SkipGeoPublish) {
    $ghProj = Join-Path $AgentDir 'GeoHelper\GeoHelper.csproj'
    $ghOut = Join-Path $AgentDir 'GeoHelper\publish'
    dotnet publish $ghProj -c Release -r win-x64 --self-contained true `
        -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true `
        -o $ghOut
    if ($LASTEXITCODE -ne 0) { throw "dotnet publish GeoHelper falhou com codigo $LASTEXITCODE" }
}

& (Join-Path $AgentDir 'zip-payload.ps1') -AgentDir $AgentDir -OutZip $OutZip

$settings = [ordered]@{
    apiUrl             = $ApiUrl
    apiKey             = $ApiKey
    intervalMinutes    = $IntervalMinutes
    estadoPermitido    = $EstadoPermitido.Trim()
}
$jsonText = $settings | ConvertTo-Json -Compress
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($SettingsPath, $jsonText, $utf8NoBom)

Push-Location $InstallerDir
try {
    # Limpar saidas para nunca reutilizar .dll/.exe sem os EmbeddedResource atualizados (InstallSettings.json).
    dotnet clean -c Release -v minimal
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue @(
        (Join-Path $InstallerDir 'bin'),
        (Join-Path $InstallerDir 'obj')
    )
    dotnet publish -c Release
    if ($LASTEXITCODE -ne 0) { throw "dotnet publish Installer falhou com codigo $LASTEXITCODE" }
    $publishedExe = Join-Path $InstallerDir 'bin\Release\net8.0\win-x64\publish\CadeVoceAgent-Setup.exe'
    Write-Host ""
    Write-Host "Instalador (single-file) gerado em:" -ForegroundColor Green
    Write-Host "  $publishedExe"
}
finally {
    Pop-Location
}
