@echo off
chcp 65001 >nul
setlocal

set "PROJ_DIR=%~dp0"
set "PYTHON=%PROJ_DIR%.venv312\Scripts\python.exe"
set "TEXTFORGE_RUNTIME=windows"

"%PYTHON%" "%PROJ_DIR%start_web.py"
