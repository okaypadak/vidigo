@echo off
setlocal

set "IMAGE_NAME=textforge:latest"
set "CONTAINER_NAME=textforge"
set "HOST_MEDIA_DIR=%USERPROFILE%\textforge"
set "HOST_COOKIE_DIR=%USERPROFILE%\cookie"

echo.
echo [1/4] Docker denetleniyor...
docker info >nul 2>&1
if errorlevel 1 (
    echo [HATA] Docker calismiyor. Docker Desktop'i baslatip tekrar deneyin.
    pause
    exit /b 1
)

echo [2/4] Mevcut TextForge container'i temizleniyor...
docker container inspect "%CONTAINER_NAME%" >nul 2>&1
if not errorlevel 1 (
    docker stop "%CONTAINER_NAME%" >nul 2>&1
    docker rm "%CONTAINER_NAME%" >nul 2>&1
)

echo [3/4] TextForge image olusturuluyor...
docker build -t "%IMAGE_NAME%" .
if errorlevel 1 (
    echo [HATA] Docker image olusturulamadi.
    pause
    exit /b 1
)

echo [4/4] TextForge GPU ile arka planda baslatiliyor...
if not exist "%HOST_MEDIA_DIR%" mkdir "%HOST_MEDIA_DIR%"
if not exist "%HOST_COOKIE_DIR%" mkdir "%HOST_COOKIE_DIR%"
docker run -d --name "%CONTAINER_NAME%" --gpus all -p 5000:5000 -p 8000:8000 -v "%HOST_MEDIA_DIR%:/data/textforge" -v "%HOST_COOKIE_DIR%:/data/cookie:ro" "%IMAGE_NAME%"
if errorlevel 1 (
    echo [HATA] TextForge baslatilamadi.
    pause
    exit /b 1
)

echo.
echo TextForge hazir:
echo   Web: http://127.0.0.1:5000
echo   Indirmeler: %HOST_MEDIA_DIR%
echo   Cookieler (salt-okunur): %HOST_COOKIE_DIR%
echo   GPU kontrolu: docker exec %CONTAINER_NAME% python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
echo   Loglar: docker logs -f %CONTAINER_NAME%
echo.

endlocal
