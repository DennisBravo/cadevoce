#requires -Version 5.1
<#
.SYNOPSIS
    Monta payload.zip (agent.ps1, scripts de tarefa, GeoHelper\publish) para o instalador .exe.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$AgentDir,
    [Parameter(Mandatory = $true)]
    [string]$OutZip
)

$ErrorActionPreference = 'Stop'

$geoExe = Join-Path $AgentDir 'GeoHelper\publish\GeoHelper.exe'
if (-not (Test-Path -LiteralPath $geoExe)) {
    throw "GeoHelper.exe nao encontrado em: $geoExe`nExecute: dotnet publish agent\GeoHelper\GeoHelper.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -o agent\GeoHelper\publish"
}

$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("cadevouce-payload-" + [guid]::NewGuid().ToString('n'))
New-Item -ItemType Directory -Path $stage -Force | Out-Null
try {
    Copy-Item -LiteralPath (Join-Path $AgentDir 'agent.ps1') -Destination $stage -Force
    Copy-Item -LiteralPath (Join-Path $AgentDir 'install-task.ps1') -Destination $stage -Force
    Copy-Item -LiteralPath (Join-Path $AgentDir 'uninstall-task.ps1') -Destination $stage -Force

    $ghOut = Join-Path $stage 'GeoHelper\publish'
    New-Item -ItemType Directory -Path $ghOut -Force | Out-Null
    $ghSrc = Join-Path $AgentDir 'GeoHelper\publish'
    Copy-Item -Path (Join-Path $ghSrc '*') -Destination $ghOut -Recurse -Force

    if (Test-Path -LiteralPath $OutZip) {
        Remove-Item -LiteralPath $OutZip -Force
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($stage, $OutZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
}
finally {
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "payload.zip -> $OutZip"
