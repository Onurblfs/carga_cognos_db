@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
title Carga Cognos - DWH Oracle
cd /d "%~dp0"

echo.
echo ========================================================================
echo   CARGA COGNOS ^> DWH ORACLE
echo   Baixa as bases do Planning Analytics e grava nas tabelas BI_FT_*
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

REM ----- Prepara o .env na primeira execucao -----
if not exist ".env" (
  if exist ".env.example" (
    copy /y ".env.example" ".env" >nul
    echo ------------------------------------------------------------------------
    echo   PRIMEIRA EXECUCAO: o arquivo .env foi criado a partir do modelo.
    echo   Confira/ajuste os valores ^(pasta do att_cognos_pbi, DSN, schema,
    echo   caminho do DB_acess.xlsx^) no Bloco de Notas que vai abrir agora.
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

REM ----- Verifica se as bibliotecas ja existem -----
REM Em maquinas onde o Scrip_carga_banco ja roda, tudo ja esta instalado
REM (pandas, PyYAML e openpyxl vem com o Anaconda; cx_Oracle/oracledb idem).
echo Verificando bibliotecas ^(pandas, PyYAML, openpyxl, driver Oracle^)...
set "LIBS_OK="
"%PYTHON%" -c "import importlib.util as u, sys; sys.exit(0 if all(u.find_spec(m) for m in ['pandas','yaml','openpyxl']) and (u.find_spec('oracledb') or u.find_spec('cx_Oracle')) else 1)" >nul 2>&1 && set "LIBS_OK=1"

if defined LIBS_OK (
  echo Bibliotecas OK ^(ja instaladas^).
  goto :libs_prontas
)

echo Instalando as bibliotecas que faltam...
"%PYTHON%" -m pip install -r requirements.txt --disable-pip-version-check -q
if not errorlevel 1 goto :libs_instaladas

echo Tentando instalar apenas para o usuario atual ^(--user^)...
"%PYTHON%" -m pip install -r requirements.txt --user --disable-pip-version-check -q
if not errorlevel 1 goto :libs_instaladas

echo.
echo [ERRO] Nao foi possivel instalar as bibliotecas automaticamente
echo        ^(a rede da empresa bloqueia o acesso direto ao pypi.org^).
echo.
echo Como o Scrip_carga_banco ja roda nesta maquina, provavelmente so falta
echo o driver Oracle. Abra o "Anaconda Prompt" pelo Menu Iniciar e rode:
echo.
echo    pip install --proxy http://PROXY:PORTA oracledb
echo.
echo ^(troque PROXY:PORTA pelo proxy da Claro^) ou, se preferir:
echo    conda install -c conda-forge oracledb
echo.
echo Depois rode este PLAY ME de novo.
pause
exit /b 1

:libs_instaladas
echo Bibliotecas instaladas com sucesso.

:libs_prontas
echo.

echo O que deseja fazer?
echo.
echo   1^) Fluxo completo  = baixa do Cognos e grava no DWH
echo   2^) So gravar       = usa os Excel ja baixados ^(nao abre o navegador^)
echo   3^) Baixar sem rede = baixa e grava, sem copiar para \\10.29.2.2
echo   0^) Sair
echo.
set /p "ESCOPO=Opcao: "

set "ARGS="
set "DESC="
if "%ESCOPO%"=="1" (
  set "ARGS="
  set "DESC=Fluxo completo: download + carga no DWH"
) else if "%ESCOPO%"=="2" (
  set "ARGS=--sem-baixar"
  set "DESC=Somente carga no DWH (arquivos ja baixados)"
) else if "%ESCOPO%"=="3" (
  set "ARGS=--sem-mover"
  set "DESC=Download local + carga no DWH (sem copiar para a rede)"
) else if "%ESCOPO%"=="0" (
  exit /b 0
) else (
  echo Opcao invalida. Use 0, 1, 2 ou 3.
  pause
  exit /b 1
)

echo.
echo ------------------------------------------------------------------------
echo   Executar: %DESC%
echo   Comando:  python -m src.main %ARGS%
echo ------------------------------------------------------------------------
echo.
set /p "CONF=Confirmar e iniciar? [S/N]: "
if /i not "%CONF%"=="S" if /i not "%CONF%"=="SIM" (
  echo Cancelado.
  pause
  exit /b 0
)

echo.
echo Executando...
echo ------------------------------------------------------------------------
"%PYTHON%" -u -m src.main %ARGS%
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
