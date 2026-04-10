#requires -Version 5.1
<#
.SYNOPSIS
    Gera CadeVoceAgent.msi (WiX v3) a partir do CadeVoceAgent-Setup.exe ja compilado.

.DESCRIPTION
    Requer WiX Toolset v3 no PATH (candle.exe e light.exe).
    Se nao tiver WiX, use apenas o .exe gerado por build-installer.ps1 (duplo clique).

.PARAMETER SetupExePath
    Caminho completo para CadeVoceAgent-Setup.exe. Padrao: saida do publish do projeto Installer.

.PARAMETER OutMsi
    Caminho do .msi de saida. Padrao: mesma pasta do .exe com extensao .msi.
#>
param(
    [string]$SetupExePath = '',
    [string]$OutMsi = ''
)

$ErrorActionPreference = 'Stop'
$AgentDir = $PSScriptRoot
if (-not $SetupExePath) {
    $SetupExePath = Join-Path $AgentDir 'Installer\bin\Release\net8.0\win-x64\publish\CadeVoceAgent-Setup.exe'
}
if (-not (Test-Path -LiteralPath $SetupExePath)) {
    throw "Nao encontrado: $SetupExePath`nExecute antes: .\build-installer.ps1 -ApiUrl ... -ApiKey ..."
}

$candle = Get-Command candle.exe -ErrorAction SilentlyContinue
$light = Get-Command light.exe -ErrorAction SilentlyContinue
if (-not $candle -or -not $light) {
    throw "WiX Toolset v3 nao encontrado (candle.exe / light.exe no PATH). Instale de https://wixtoolset.org/docs/wix3/ ou distribua só o .exe."
}

$SourceDir = Split-Path -LiteralPath $SetupExePath -Parent
if (-not $OutMsi) {
    $OutMsi = Join-Path $SourceDir 'CadeVoceAgent.msi'
}

$wixDir = Join-Path $AgentDir 'wix'
$wxs = Join-Path $wixDir 'Product.wxs'
$wixObj = Join-Path $wixDir 'Product.wixobj'

Push-Location $wixDir
try {
    if (Test-Path -LiteralPath $wixObj) { Remove-Item -LiteralPath $wixObj -Force }
    & candle.exe "-dSourceDir=$SourceDir" -out "$wixDir\" Product.wxs
    if ($LASTEXITCODE -ne 0) { throw "candle falhou: $LASTEXITCODE" }
    & light.exe -out $OutMsi $wixObj
    if ($LASTEXITCODE -ne 0) { throw "light falhou: $LASTEXITCODE" }
    Write-Host "MSI gerado: $OutMsi" -ForegroundColor Green
}
finally {
    Pop-Location
}
