#requires -Version 5.1
<#
.SYNOPSIS
    Remove a tarefa agendada "CadeVoce-Agent" criada por install-task.ps1.
#>

$ErrorActionPreference = 'Stop'

$TaskName = 'CadeVoce-Agent'

try {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "Nada a fazer: a tarefa '$TaskName' não existe." -ForegroundColor Yellow
        exit 0
    }

    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Sucesso: tarefa '$TaskName' removida." -ForegroundColor Green
}
catch {
    Write-Host "Erro ao remover a tarefa: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
