# Painel ao vivo das exportacoes Cognos (le painel_status.json).
$ErrorActionPreference = "SilentlyContinue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$StatusFile = Join-Path $Root "painel_status.json"
$Host.UI.RawUI.WindowTitle = "Painel Cognos PBI"

function Show-Panel {
    param($Data)
    Clear-Host
    Write-Host ""
    Write-Host "========================================================================" -ForegroundColor Cyan
    Write-Host "  COGNOS / Power BI — Painel de Exportacoes" -ForegroundColor Cyan
    Write-Host ("  Inicio: {0}   |   Decorrido: {1}   |   ETA restante: ~{2}" -f $Data.inicio, $Data.decorrido, $Data.eta) -ForegroundColor Yellow
    Write-Host ("  Fase: {0}" -f $Data.fase) -ForegroundColor Gray
    Write-Host ("  {0}" -f $Data.mensagem) -ForegroundColor White
    Write-Host "------------------------------------------------------------------------"
    Write-Host ("  {0,-3} {1,-14} {2,-10} {3}" -f "#", "Status", "Tempo", "Exportacao") -ForegroundColor Gray
    Write-Host "------------------------------------------------------------------------"
    $i = 1
    foreach ($j in $Data.jobs) {
        $color = "Gray"
        switch ($j.status) {
            "OK"      { $color = "Green" }
            "OK_REDE" { $color = "Yellow" }
            "ERRO"    { $color = "Red" }
            "RODANDO" { $color = "Cyan" }
            default   { $color = "DarkGray" }
        }
        Write-Host ("  {0,-3} {1,-14} {2,-10} {3}" -f $i, $j.status, $j.tempo, $j.nome) -ForegroundColor $color
        $i++
    }
    Write-Host "========================================================================" -ForegroundColor Cyan
    if ($Data.finalizado) {
        Write-Host ""
        Write-Host "  Processo finalizado. Pode fechar esta janela." -ForegroundColor Green
    } else {
        Write-Host ("  Atualizado: {0}" -f $Data.atualizado_em) -ForegroundColor DarkGray
    }
}

Write-Host "Aguardando inicio do processo..." -ForegroundColor Yellow
while ($true) {
    if (Test-Path $StatusFile) {
        try {
            $raw = Get-Content -Path $StatusFile -Raw -Encoding UTF8
            $data = $raw | ConvertFrom-Json
            Show-Panel $data
            if ($data.finalizado) {
                break
            }
        } catch {
            # JSON incompleto durante escrita — ignora e tenta de novo
        }
    }
    Start-Sleep -Milliseconds 800
}

Write-Host ""
pause
