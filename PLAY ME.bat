@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
title Carga Cognos - DWH Oracle
cd /d "%~dp0"

echo.
echo ========================================================================
echo   CARGA COGNOS ^> DWH ORACLE
echo   1. Baixa as bases do Planning Analytics ^(Cognos^)
echo   2. Grava nas tabelas BI_FT_* do DWH
echo ========================================================================
echo.

REM ----- Localiza Python (Anaconda corporativo primeiro) -----
set "PYTHON="
set "CONDA_ACT="
if exist "C:\ProgramData\anaconda3\python.exe" (
  set "PYTHON=C:\ProgramData\anaconda3\python.exe"
  set "CONDA_ACT=C:\ProgramData\anaconda3\Scripts\activate.bat"
)
if not defined PYTHON if exist "%USERPROFILE%\anaconda3\python.exe" (
  set "PYTHON=%USERPROFILE%\anaconda3\python.exe"
  set "CONDA_ACT=%USERPROFILE%\anaconda3\Scripts\activate.bat"
)
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
where python >nul 2>&1 && if not defined PYTHON for /f "delims=" %%P in ('where python') do (
  set "PYTHON=%%P"
  goto :py_ok
)
:py_ok
if not defined PYTHON (
  echo [ERRO] Python nao encontrado. Instale Anaconda/Python ou ajuste este BAT.
  pause
  exit /b 1
)

REM ----- Ativa o Anaconda (evita erro "SSL module is not available" no pip) -----
if defined CONDA_ACT if exist "%CONDA_ACT%" (
  echo Ativando ambiente Anaconda...
  call "%CONDA_ACT%"
)

echo Python: %PYTHON%
echo Pasta:  %CD%
echo.

REM Selenium empacotado neste projeto (sem pip / sem pypi.org)
set "PYTHONPATH=%CD%\vendor;%PYTHONPATH%"

REM ----- Prepara o .env na primeira execucao -----
if not exist ".env" (
  if exist ".env.example" (
    copy /y ".env.example" ".env" >nul
    echo ------------------------------------------------------------------------
    echo   PRIMEIRA EXECUCAO: o arquivo .env foi criado a partir do modelo.
    echo   Confira/ajuste DSN, schema e o caminho do DB_acess.xlsx
    echo   no Bloco de Notas que vai abrir agora.
    echo   Depois salve, feche e rode o PLAY ME de novo.
    echo ------------------------------------------------------------------------
    start /wait notepad ".env"
    pause
    exit /b 0
  ) else (
    echo [ERRO] .env e .env.example nao encontrados nesta pasta.
    pause
    exit /b 1
  )
)

REM ----- Verifica bibliotecas (NAO instala: a rede da Claro bloqueia o pypi.org) -----
echo Verificando bibliotecas...
"%PYTHON%" -c "import importlib.util as u, sys; core=['pandas','yaml','openpyxl']; miss=[m for m in core if not u.find_spec(m)]; miss += [] if (u.find_spec('oracledb') or u.find_spec('cx_Oracle')) else ['oracledb']; sel=bool(u.find_spec('selenium')); print('FALTANDO: '+', '.join(miss) if miss else 'CORE_OK'); print('SELENIUM='+('OK' if sel else 'AUSENTE')); sys.exit(2 if miss else 0)"
set "CHK=%ERRORLEVEL%"
if not "%CHK%"=="0" (
  echo.
  echo [ERRO] Faltam bibliotecas essenciais no Anaconda.
  echo Como o pip nao funciona nesta rede, use o Anaconda Prompt:
  echo    conda install pandas pyyaml openpyxl
  pause
  exit /b 1
)
echo Bibliotecas OK. Seguindo sem pip ^(rede corporativa bloqueia pypi.org^).

:libs_prontas
echo.
echo ------------------------------------------------------------------------
echo   Iniciando: download do Cognos + carga no DWH
echo   ^(os Excel ficam na pasta downloads\ deste projeto^)
echo ------------------------------------------------------------------------
echo.

"%PYTHON%" -u -m src.main
set "RC=%ERRORLEVEL%"

echo.
echo ------------------------------------------------------------------------
if "%RC%"=="0" (
  echo Carga finalizada com sucesso.
) else (
  echo Carga finalizada com erros ^(codigo %RC%^). Veja as mensagens acima.
)
echo.
pause
exit /b %RC%
