@echo off
rem  Doble clic aqui y ya esta: la interfaz, la guardia nocturna y el bot.
rem
rem  La primera vez crea un entorno propio e instala lo que hace falta; las
rem  siguientes arranca directo. Si algo falla, la ventana NO se cierra: el
rem  error se queda ahi para poder leerlo, que es la mitad del trabajo.
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo.
    echo   x No encuentro Python en este ordenador.
    echo     Instalalo desde python.org ^(marca "Add Python to PATH"^) y vuelve.
    echo.
    pause
    exit /b 1
  )
  set "PY=python"
) else (
  set "PY=py -3"
)

if not exist ".venv\Scripts\python.exe" (
  echo   Primera vez: preparando el entorno. Esto tarda un minuto.
  %PY% -m venv .venv || goto :fallo
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip || goto :fallo
  ".venv\Scripts\python.exe" -m pip install --quiet -e ".[curl]" || goto :fallo
  echo   Listo.
)

".venv\Scripts\python.exe" -m cancha arrancar %*
if errorlevel 1 goto :fallo
exit /b 0

:fallo
echo.
echo   x Algo ha fallado. El error esta justo arriba.
echo     Si no se entiende, copialo entero: dice mas de lo que parece.
echo.
pause
exit /b 1
