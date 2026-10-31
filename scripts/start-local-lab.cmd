@echo off
setlocal
rem Start the synthetic Novera Lab on 127.0.0.1 only.
rem Never checks out branches, modifies Git state, or uses real provider keys.
cd /d "%~dp0.."

where uv >nul 2>nul
if errorlevel 1 (
  echo [Novera] uv nao encontrado. Instale uv e tente novamente.
  exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo [Novera] npm nao encontrado. Instale Node.js 22 ou superior.
  exit /b 1
)

echo [Novera] Instalando dependencias Python pelo uv.lock...
call uv sync --locked --group dev
if errorlevel 1 exit /b 1

echo [Novera] Conferindo dados ficticios com Python...
call uv run --offline --locked python frontend/scripts/materialize_demo.py --check
if errorlevel 1 (
  echo [Novera] Fixtures diferentes. Revise a origem Python antes de compilar.
  exit /b 1
)

echo [Novera] Instalando dependencias JS pelo package-lock.json...
pushd frontend
call npm ci --ignore-scripts --no-fund
if errorlevel 1 (
  popd
  exit /b 1
)
call npm run build
if errorlevel 1 (
  popd
  exit /b 1
)
popd

echo.
echo [Novera] Laboratorio local: http://127.0.0.1:8765/
echo [Novera] Ctrl+C interrompe o servidor. Sem provedores reais.
echo.
call uv run --offline --locked python -m novera.local_lab
exit /b %ERRORLEVEL%
