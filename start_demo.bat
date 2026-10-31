@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Виртуальное окружение .venv не найдено.
    echo Сначала запустите install_demo.bat и дождитесь окончания установки.
    pause
    exit /b 1
)

echo Запуск локального сервера MicroMarket Control...
echo Адрес: http://127.0.0.1:8000/
echo Браузер откроется автоматически через 3 секунды.
echo Для остановки сервера нажмите Ctrl+C в этом окне.
echo Закрытие окна браузера сервер не останавливает.
echo.

start "MicroMarket - открытие браузера" /min cmd /c "timeout /t 3 /nobreak >nul & start "" http://127.0.0.1:8000/"

.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000

echo.
echo Сервер остановлен.
pause
endlocal
exit /b 0
