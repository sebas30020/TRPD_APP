@echo off
setlocal
cd /d "%~dp0"

rem Interprete: TRPD_PYTHON > venv local (fuera de Drive) > .venv legado en Drive
set "VENV_LOCAL=%LOCALAPPDATA%\venvs\trpd_app"
set "PYTHON=%TRPD_PYTHON%"
if "%PYTHON%"=="" if exist "%VENV_LOCAL%\Scripts\python.exe" set "PYTHON=%VENV_LOCAL%\Scripts\python.exe"
if "%PYTHON%"=="" (
    set "PYTHON=%~dp0.venv\Scripts\python.exe"
    echo [AVISO] Usando .venv en Google Drive: el arranque puede tardar minutos.
    echo         Cree el entorno local en "%VENV_LOCAL%" ^(ver archivos_md\DOCUMENTACION.md^).
    echo.
)
rem Los .pyc del proyecto se escriben en disco local, no en Drive
set "PYTHONPYCACHEPREFIX=%VENV_LOCAL%\pycache"

if not exist "%PYTHON%" (
    echo =======================================================================
    echo [ERROR] No se encontro el interprete de Python en:
    echo         "%PYTHON%"
    echo.
    echo El entorno virtual .venv no existe o no esta configurado en esta ruta.
    echo No se debe usar el Python global porque carece de las dependencias requeridas.
    echo Asegurese de que .venv este disponible o configure la variable TRPD_PYTHON.
    echo =======================================================================
    echo.
    pause
    exit /b 1
)

echo =======================================================================
echo   Iniciando Visor TRPD en http://127.0.0.1:8051 ...
echo   Interprete: "%PYTHON%"
echo =======================================================================
echo.
"%PYTHON%" -u app.py
if errorlevel 1 (
    echo.
    echo [AVISO] El servidor se cerro con error o fue interrumpido.
    pause
)
