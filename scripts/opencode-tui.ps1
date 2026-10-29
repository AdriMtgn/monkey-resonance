# Script pour lancer OpenCode TUI depuis Windows/WSL
# Solution recommandée : utiliser la TUI directement dans le terminal WSL

Write-Host "=== OpenCode TUI - Monkey Resonance ===" -ForegroundColor Cyan

# Vérifier si le container est en cours d'exécution
Write-Host "`n[Vérification] Container Docker..." -ForegroundColor Yellow
$container = docker ps --filter "name=monkey-resonance-mkr-1" --format "{{.Status}}"
if ($container -notmatch "Up") {
    Write-Host "[Démarrage] Le container n'est pas en cours d'exécution..." -ForegroundColor Yellow
    docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d mkr
    Start-Sleep -Seconds 10
}

# Vérifier si le serveur OpenCode est démarré
Write-Host "`n[Vérification] Serveur OpenCode..." -ForegroundColor Yellow
$passFile = (Get-Location).Path + "\.devcontainer\tmp\opencode-password"
if (-Not (Test-Path $passFile)) {
    Write-Host "[Démarrage] Démarrage du serveur OpenCode..." -ForegroundColor Yellow
    docker compose -f docker-compose.yml -f docker-compose.dev.yml exec mkr bash .devcontainer/scripts/agent-server.sh
}

Write-Host "`n=== OPTIONS D'ACCÈS ===" -ForegroundColor Cyan

# Option 1 : TUI dans le terminal (recommandée)
Write-Host "`n[Option 1 - RECOMMANDÉE] TUI interactive dans le terminal WSL :" -ForegroundColor Green
Write-Host "  make agent-host" -ForegroundColor White
Write-Host "  OU" -ForegroundColor White
Write-Host "  docker exec -it monkey-resonance-mkr-1 opencode --standalone" -ForegroundColor White

# Option 2 : Lancer un message immédiat
Write-Host "`n[Option 2] Message immédiat dans le terminal WSL :" -ForegroundColor Green
Write-Host "  docker exec monkey-resonance-mkr-1 opencode run 'Bonjour' /base_app --model litellm/qwen38-35b" -ForegroundColor White

# Option 3 : Interface web via host.docker.internal (peut ne pas fonctionner selon Docker Desktop)
Write-Host "`n[Option 3] Interface web :" -ForegroundColor Yellow
Write-Host "  http://host.docker.internal:4096" -ForegroundColor White
Write-Host "  OU" -ForegroundColor White
Write-Host "  http://localhost:4096" -ForegroundColor White

Write-Host "`n[Note] Docker Desktop WSL peut bloquer l'accès à l'interface web." -ForegroundColor Yellow
Write-Host "L'option 1 (TUI dans le terminal) fonctionne toujours." -ForegroundColor Yellow

Write-Host "`nPress enter pour continuer..." -ForegroundColor Cyan
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

Write-Host "`n=== TUI DANS LE TERMINAL ===" -ForegroundColor Cyan
Write-Host "Ouvrez PowerShell/WSL et exécutez :" -ForegroundColor White
Write-Host "  make agent-host" -ForegroundColor White
Write-Host "`nOu utilisez un message direct :" -ForegroundColor White
Write-Host "  docker exec monkey-resonance-mkr-1 opencode run 'Votre message' /base_app --model litellm/qwen38-35b" -ForegroundColor White

Write-Host "`nPress enter pour ouvrir le navigateur..." -ForegroundColor Cyan
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

# Tenter d'ouvrir l'interface web
try {
    Write-Host "`n[Tentative] Ouverture du navigateur..." -ForegroundColor Yellow
    Start-Process "http://localhost:4096"
    Write-Host "Interface web tentée : http://localhost:4096" -ForegroundColor Cyan
} catch {
    Write-Host "Impossible d'ouvrir le navigateur automatiquement" -ForegroundColor Red
}
