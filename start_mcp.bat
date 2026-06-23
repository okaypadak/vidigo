@echo off
chcp 65001 >nul
set "PROJ_DIR=%~dp0"
set "PYTHON=%PROJ_DIR%.venv312\Scripts\python.exe"
set "MCP_SCRIPT=%PROJ_DIR%mcp_server.py"

"%PYTHON%" "%MCP_SCRIPT%"
