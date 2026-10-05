# Start the isolated acceptance stack; keep it running for inspection afterward.
$ErrorActionPreference = 'Stop'
$verifyProjectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $verifyProjectRoot
try {
    docker info --format '{{.ServerVersion}}'
    if ($LASTEXITCODE -ne 0) { throw 'Docker engine is unavailable; start Docker Desktop first.' }
    docker compose -p testhub-secondary-verify -f docker-compose.verify.yml config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Invalid acceptance Compose configuration.' }
    docker compose -p testhub-secondary-verify -f docker-compose.verify.yml up --build --detach --wait --wait-timeout 240
    if ($LASTEXITCODE -ne 0) { throw 'Acceptance stack did not become ready.' }
    docker compose -p testhub-secondary-verify -f docker-compose.verify.yml exec -T backend python manage.py check
    if ($LASTEXITCODE -ne 0) { throw 'Container Django check failed.' }
    docker compose -p testhub-secondary-verify -f docker-compose.verify.yml exec -T backend python manage.py makemigrations --check --dry-run
    if ($LASTEXITCODE -ne 0) { throw 'Container migration drift detected.' }
    .\.venv\Scripts\python.exe scripts/verify_demo.py --base-url http://127.0.0.1:18080 --password 'TestHubDemo!2026' --output docs/secondary-development/container-verification.json
    if ($LASTEXITCODE -ne 0) { throw 'Real MySQL/Redis HTTP acceptance failed.' }
    .\.venv\Scripts\python.exe scripts/verify_realtime.py --password 'TestHubDemo!2026'
    if ($LASTEXITCODE -ne 0) { throw 'Redis/worker WebSocket acceptance failed.' }
    Write-Host 'Acceptance passed; browser demo: http://127.0.0.1:18080'
} finally {
    docker compose -p testhub-secondary-verify -f docker-compose.verify.yml logs --no-color > docs/secondary-development/container-services.log
    Pop-Location
}
