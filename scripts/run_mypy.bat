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

.venv\Scripts\python.exe -c "import mypy" 2>nul
if not %errorlevel%==0 (
    echo mypy не установлен. Установите его командой:
    echo   .venv\Scripts\python.exe -m pip install mypy
    pause
    exit /b 1
)

echo Проверка типов mypy...
.venv\Scripts\python.exe -m mypy core config
if not %errorlevel%==0 (
    echo [ОШИБКА] Mypy обнаружил проблемы типов.
    pause
    exit /b 1
)

echo [OK] Проблем типов не найдено.
pause
exit /b 0
