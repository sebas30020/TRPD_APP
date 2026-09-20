@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%TRPD_PYTHON%"
if "%PYTHON%"=="" set "PYTHON=%~dp0.venv\Scripts\python.exe"

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
echo   Iniciando Visor TRPD en http://127.0.0.1:8050 ...
echo   Interprete: "%PYTHON%"
echo =======================================================================
echo.
"%PYTHON%" -u app.py
if errorlevel 1 (
    echo.
    echo [AVISO] El servidor se cerro con error o fue interrumpido.
    pause
)
