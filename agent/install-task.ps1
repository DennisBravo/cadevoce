#requires -Version 5.1
<#
.SYNOPSIS
    Registra a tarefa agendada "CadeVoce-Agent" (check-in a cada 10 min, ao logon).

.DESCRIPTION
    Cria uma Scheduled Task para o usuário atual: executa agent.ps1 com PowerShell oculto,
    apenas com sessão interativa (não roda sem login).

.PARAMETER ApiUrl
    Valor de CADEVOCE_API_URL (padrão: http://127.0.0.1:8000).

.PARAMETER ApiKey
    Valor de CADEVOCE_API_KEY (padrão: changeme).

.PARAMETER GpsCom
    Porta do GPS USB NMEA (ex.: COM3). Opcional; se vazio, só Windows Location + IP.

.PARAMETER GpsBaud
    Baud rate serial (ex.: 9600, 115200). 0 = não define (agente usa 9600).
#>
param(
    [string]$ApiUrl = 'http://127.0.0.1:8000',
    [string]$ApiKey = 'changeme',
    [string]$GpsCom = '',
    [int]$GpsBaud = 0
)

$ErrorActionPreference = 'Stop'

# Nome e metadados da tarefa
$TaskName = 'CadeVoce-Agent'
$Description = 'Agente de rastreamento Cadê Você — check-in a cada 10 min'

# Caminho do script do agente (mesma pasta deste instalador)
$ScriptPath = Join-Path $PSScriptRoot 'agent.ps1'
if (-not (Test-Path -LiteralPath $ScriptPath)) {
    Write-Host "Erro: não foi encontrado agent.ps1 em: $PSScriptRoot" -ForegroundColor Red
    exit 1
}

# Conta atual no formato esperado pelo Agendador (ex.: DOMINIO\user ou COMPUTADOR\user)
$UserId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

# Escapa aspas simples para uso dentro de uma string PowerShell entre aspas simples
function Escape-SingleQuote {
    param([string]$Text)
    $Text -replace "'", "''"
}

$escUrl = Escape-SingleQuote $ApiUrl
$escKey = Escape-SingleQuote $ApiKey
$escScript = Escape-SingleQuote $ScriptPath

# Define variáveis de ambiente e executa o script; WindowStyle Hidden = janela invisível
$psCommand = "`$env:CADEVOCE_API_URL='$escUrl'; `$env:CADEVOCE_API_KEY='$escKey'"
if ($GpsCom -and $GpsCom.Trim()) {
    $escCom = Escape-SingleQuote $GpsCom.Trim()
    $psCommand += "; `$env:CADEVOCE_GPS_COM='$escCom'"
}
if ($GpsBaud -gt 0) {
    $psCommand += "; `$env:CADEVOCE_GPS_BAUD='$GpsBaud'"
}
$psCommand += "; & '$escScript'"

# -EncodedCommand (Base64 UTF-16LE): evita problemas de escape na linha de comando da tarefa
$bytes = [System.Text.Encoding]::Unicode.GetBytes($psCommand)
$encoded = [Convert]::ToBase64String($bytes)
$action = New-ScheduledTaskAction `
    -Execute (Join-Path $PSHOME 'powershell.exe') `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -EncodedCommand $encoded" `
    -WorkingDirectory $PSScriptRoot

# Gatilho: ao fazer login + repetição a cada 10 minutos (duração longa; o Agendador limita o valor máximo de “indefinido” na API)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
$repeatTemplate = New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
    -RepetitionInterval (New-TimeSpan -Minutes 10) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$trigger.Repetition = $repeatTemplate.Repetition

# Só quando o usuário estiver logado (sessão interativa)
$principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited

# Não exige privilégios elevados; ignora nova instância se a anterior ainda estiver em execução
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

try {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description $Description | Out-Null

    Write-Host "Sucesso: tarefa '$TaskName' registrada para o usuário $UserId." -ForegroundColor Green
    Write-Host "  CADEVOCE_API_URL=$ApiUrl"
    if ($GpsCom -and $GpsCom.Trim()) {
        Write-Host "  CADEVOCE_GPS_COM=$($GpsCom.Trim())"
        if ($GpsBaud -gt 0) { Write-Host "  CADEVOCE_GPS_BAUD=$GpsBaud" }
    }
    Write-Host "  Script: $ScriptPath"
}
catch {
    Write-Host "Erro ao registrar a tarefa: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
