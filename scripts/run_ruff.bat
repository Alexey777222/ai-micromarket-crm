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

echo Проверка стиля кода ruff...
.venv\Scripts\python.exe -m ruff check .
if not %errorlevel%==0 (
    echo [ОШИБКА] Ruff обнаружил проблемы.
    pause
    exit /b 1
)

echo [OK] Проблем стиля не найдено.
pause
exit /b 0
