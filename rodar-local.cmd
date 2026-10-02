@echo off
rem Sobe o dashboard localmente para visualizar: Postgres local, API e dashboard.
rem O worker NAO sobe: com o .env atual ele publicaria pelo numero real do WhatsApp.
setlocal
cd /d "%~dp0"

set "PG=C:\Users\SnyX\pgsql"

rem A Evolution do .env e a de producao. Aqui ela fica desligada, para que nenhum
rem botao do dashboard local (entrar em grupo por convite, sincronizar grupos)
rem use o numero real. Variavel de ambiente tem prioridade sobre o .env.
set "EVOLUTION_API_URL=http://127.0.0.1:9"

echo [1/4] Postgres local...
"%PG%\bin\pg_ctl.exe" status -D "%PG%\data" >nul 2>&1
if errorlevel 1 (
  "%PG%\bin\pg_ctl.exe" start -D "%PG%\data" -l "%PG%\pg.log" -w >nul
  if errorlevel 1 (
    echo Nao consegui iniciar o Postgres. Veja %PG%\pg.log
    pause
    exit /b 1
  )
)

echo [2/4] Migrations no banco local...
venv\Scripts\python.exe -m alembic upgrade head
if errorlevel 1 (
  echo As migrations falharam. Veja a mensagem acima.
  pause
  exit /b 1
)

echo [3/4] API em http://localhost:8000 ...
start "nina-api (local)" cmd /k venv\Scripts\python.exe -m api.serve

echo [4/4] Dashboard em http://localhost:5173 ...
if not exist dashboard\node_modules (
  pushd dashboard
  call npm install
  popd
)
start "nina-dashboard (local)" cmd /k "cd /d dashboard && npm run dev"

rem Espera a API responder antes de abrir o navegador.
powershell -NoProfile -Command "for ($i = 0; $i -lt 30; $i++) { try { Invoke-WebRequest -UseBasicParsing http://localhost:8000/api/health -TimeoutSec 2 | Out-Null; exit 0 } catch { Start-Sleep -Seconds 1 } }; exit 1"
if errorlevel 1 echo A API ainda nao respondeu; confira a janela "nina-api (local)".

start "" http://localhost:5173
echo.
echo Pronto. Login: ADMIN_EMAIL e ADMIN_PASSWORD do arquivo .env.
echo Para parar, feche as janelas "nina-api (local)" e "nina-dashboard (local)".
endlocal
