@echo off
rem Desplegables: doble clic per obrir l'app.
rem El primer cop crea un entorn de Python a .venv i hi instal.la les dependencies;
rem despres nomes ho torna a fer si requirements.txt ha canviat.
setlocal
cd /d "%~dp0"
set "VENV=.venv"
set "PY=%VENV%\Scripts\python.exe"

if exist "%PY%" goto deps

echo Creant l'entorn de Python (nomes el primer cop)...
set "BASE="
for %%V in (3.12 3.11 3.13 3.10) do (
    if not defined BASE (
        py -%%V -c "import sys" >nul 2>nul && set "BASE=py -%%V"
    )
)
if not defined BASE (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "BASE=python"
)
if not defined BASE (
    echo.
    echo No s'ha trobat Python 3.10 o mes nou.
    echo Instal.la'l des de https://www.python.org/downloads/ ^(marca "Add python.exe to PATH"^)
    echo i torna a obrir aquest fitxer.
    pause
    exit /b 1
)
%BASE% -m venv "%VENV%"
if errorlevel 1 (
    echo No s'ha pogut crear l'entorn de Python.
    pause
    exit /b 1
)

:deps
fc /b requirements.txt "%VENV%\requirements.instal.lat" >nul 2>nul
if not errorlevel 1 goto run
echo Instal.lant les dependencies (pot trigar uns minuts)...
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Error instal.lant les dependencies. Revisa la connexio a internet i torna-ho a provar.
    pause
    exit /b 1
)
copy /y requirements.txt "%VENV%\requirements.instal.lat" >nul

:run
rem Sense aixo, el primer cop Streamlit demana un correu a la finestra i espera.
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
    > "%USERPROFILE%\.streamlit\credentials.toml" echo [general]
    >> "%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)
echo Obrint l'app al navegador... ^(tanca aquesta finestra per aturar-la^)
"%PY%" -m streamlit run app.py
pause
