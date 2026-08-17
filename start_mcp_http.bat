@echo off
chcp 65001 >nul
set "PROJ_DIR=%~dp0"
set "PYTHON=%PROJ_DIR%.venv312\Scripts\python.exe"
set "MCP_SCRIPT=%PROJ_DIR%mcp_server.py"
set "TEXTFORGE_MCP_HOST=0.0.0.0"
set "TEXTFORGE_MCP_PORT=8000"

"%PYTHON%" "%MCP_SCRIPT%" serve
