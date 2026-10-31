@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
    echo Виртуальное окружение .venv не найдено.
    echo Сначала запустите install_demo.bat.
    pause
    exit /b 1
)

echo Сборка статических файлов...
.venv\Scripts\python.exe manage.py collectstatic --noinput
if not %errorlevel%==0 (
    echo [ОШИБКА] collectstatic завершился с ошибкой.
    pause
    exit /b 1
)

echo [OK] Статические файлы собраны в staticfiles\.
pause
exit /b 0
