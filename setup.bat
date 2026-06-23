@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

set "PROJ_DIR=%~dp0"
set "PYTHON=%PROJ_DIR%.venv312\Scripts\python.exe"
set "PIP=%PROJ_DIR%.venv312\Scripts\pip.exe"
set "MCP_SCRIPT=%PROJ_DIR%mcp_server.py"

echo.
echo =========================================
echo   Vidigo MCP Setup
echo =========================================
echo.

:: Python kontrolu
if not exist "%PYTHON%" (
    echo [HATA] .venv312 bulunamadi: %PYTHON%
    echo Lutfen once: python -m venv .venv312
    pause & exit /b 1
)
echo [OK] Python: %PYTHON%

:: Bagimliliklar
echo.
echo [1/2] Bagimliliklar yukleniyor...
"%PIP%" install -r "%PROJ_DIR%requirements.txt" --quiet
echo [OK] Bagimliliklar hazir.

:: Import testi
echo.
echo [2/2] MCP server test ediliyor...
"%PYTHON%" -c "import sys; sys.path.insert(0, r'%PROJ_DIR%'); from mcp_server import mcp; print('[OK] Araclar:', ', '.join(t.name for t in mcp._tool_manager.list_tools()))"
if errorlevel 1 (
    echo [HATA] MCP server yuklenemedi.
    pause & exit /b 1
)

echo.
echo =========================================
echo   Kurulum tamamlandi!
echo.
echo   MCP client config:
echo.
"%PYTHON%" -c "import json; cfg={'mcpServers': {'vidigo': {'command': r'%PYTHON%', 'args': [r'%MCP_SCRIPT%']}}}; print(json.dumps(cfg, indent=2))"
echo =========================================
echo.
pause
