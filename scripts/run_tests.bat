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

echo Запуск тестов pytest...
.venv\Scripts\python.exe -m pytest -q
if not %errorlevel%==0 (
    echo [ОШИБКА] Тесты завершились с ошибкой.
    pause
    exit /b 1
)

echo [OK] Все тесты пройдены.
pause
exit /b 0
