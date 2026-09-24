# Varredura local de segredos no historico Git (rodar manualmente apos clonar).
# Requer: https://github.com/gitleaks/gitleaks
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "=== git: .env no historico? ==="
git log --all --oneline -- .env

Write-Host "`n=== gitleaks (se instalado) ==="
if (Get-Command gitleaks -ErrorAction SilentlyContinue) {
    gitleaks detect --source $Root --verbose
} else {
    Write-Host "gitleaks nao encontrado. Instale ou use: winget install gitleaks"
}
