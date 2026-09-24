@echo off
rem  Doble clic aqui y ya esta: la interfaz, la guardia nocturna y el bot.
rem
rem  Tambien vale para cualquier otro comando, sin saber donde esta el entorno:
rem      cancha.bat doctor
rem      cancha.bat ajustes ligas=grandes
rem      cancha.bat guardia --una-vez
rem  Sin argumentos (o con opciones sueltas) hace lo de siempre: arrancar.
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

rem  Lo que tiene que haber dentro del entorno. Si cambia, se completa solo:
rem  el que ya tuviera el entorno hecho de antes no se queda sin lo nuevo.
set "SELLO=curl+tls"
set "MARCA=.venv\.cancha-extras"

if not exist ".venv\Scripts\python.exe" (
  echo   Primera vez: preparando el entorno. Esto tarda un minuto.
  %PY% -m venv .venv || goto :fallo
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip || goto :fallo
)

set "PUESTO="
if exist "%MARCA%" set /p PUESTO=<"%MARCA%"
if not "%PUESTO%"=="%SELLO%" (
  echo   Completando el entorno. Un momento.
  ".venv\Scripts\python.exe" -m pip install --quiet -e ".[curl,tls]" || goto :fallo
  > "%MARCA%" echo %SELLO%
  echo   Listo.
)

rem  OJO con instalar cosas a mano: `pip install algo` desde PowerShell va al
rem  Python del sistema, no a este entorno, y entonces cancha no lo ve. Aqui
rem  dentro se hace asi:
rem      .venv\Scripts\python.exe -m pip install algo

rem  Si el primer argumento es un comando (no empieza por guion) se pasa tal
rem  cual; si no, se supone que quieres arrancarlo todo. Cada linea por
rem  separado y sin expansion retardada: dentro de un bloque con parentesis
rem  esto es una fuente de sorpresas.
set "COMANDO=arrancar"
set "PRIMERO=%~1"
if not defined PRIMERO goto :lanzar
if "%PRIMERO:~0,1%"=="-" goto :lanzar
set "COMANDO="

:lanzar
".venv\Scripts\python.exe" -m cancha %COMANDO% %*
if errorlevel 1 goto :fallo
exit /b 0

:fallo
echo.
echo   x Algo ha fallado. El error esta justo arriba.
echo     Si no se entiende, copialo entero: dice mas de lo que parece.
echo.
pause
exit /b 1
