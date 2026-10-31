@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

set "VERSION=0.2.0"
set "NO_PAUSE=0"
if /I "%~1"=="--no-pause" set "NO_PAUSE=1"

echo ============================================================
echo  Установка MicroMarket Control v%VERSION%
echo ============================================================
echo.

rem --------------------------------------------------------
rem 1. Проверка наличия Python
rem --------------------------------------------------------
where py >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON_CMD=py -3"
    goto :python_found
)
where python >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON_CMD=python"
    goto :python_found
)

echo [ОШИБКА] Этап 1: Python не найден.
echo Установите Python 3.12 или новее с https://www.python.org/downloads/
echo и повторите запуск.
goto :fail

:python_found
echo [OK] Этап 1: Python найден. Версия:
%PYTHON_CMD% --version
if not %errorlevel%==0 (
    echo [ОШИБКА] Этап 1: не удалось выполнить Python --version.
    goto :fail
)
echo.

rem --------------------------------------------------------
rem 2. Создание .venv, если окружения ещё нет
rem --------------------------------------------------------
if exist ".venv\Scripts\python.exe" goto :venv_ready

echo [.] Этап 2: создаю виртуальное окружение .venv...
%PYTHON_CMD% -m venv .venv
if not %errorlevel%==0 (
    echo [ОШИБКА] Этап 2: не удалось создать виртуальное окружение .venv.
    goto :fail
)

:venv_ready
if not exist ".venv\Scripts\python.exe" (
    echo [ОШИБКА] Этап 2: .venv\Scripts\python.exe отсутствует после создания.
    goto :fail
)
echo [OK] Этап 2: виртуальное окружение .venv готово.
echo.

rem --------------------------------------------------------
rem 3. Обновление pip, setuptools, wheel
rem --------------------------------------------------------
echo [.] Этап 3: обновляю pip, setuptools, wheel...
.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
if not %errorlevel%==0 (
    echo [ОШИБКА] Этап 3: не удалось обновить pip, setuptools или wheel.
    goto :fail
)
echo [OK] Этап 3: pip, setuptools, wheel обновлены.
echo.

rem --------------------------------------------------------
rem 4. Установка веб-зависимостей
rem --------------------------------------------------------
echo [.] Этап 4: устанавливаю веб-зависимости из requirements-web.txt...
.venv\Scripts\python.exe -m pip install -r requirements-web.txt
if not %errorlevel%==0 (
    echo [ОШИБКА] Этап 4: не удалось установить requirements-web.txt.
    goto :fail
)
echo [OK] Этап 4: веб-зависимости установлены.
echo.

rem --------------------------------------------------------
rem 5. Миграции
rem --------------------------------------------------------
echo [.] Этап 5: применяю миграции базы данных...
.venv\Scripts\python.exe manage.py migrate --noinput
if not %errorlevel%==0 (
    echo [ОШИБКА] Этап 5: миграции завершились с ошибкой.
    goto :fail
)
echo [OK] Этап 5: миграции применены.
echo.

rem --------------------------------------------------------
rem 6. Сборка статических файлов
rem --------------------------------------------------------
echo [.] Этап 6: собираю статические файлы...
.venv\Scripts\python.exe manage.py collectstatic --noinput
if not %errorlevel%==0 (
    echo [ОШИБКА] Этап 6: collectstatic завершился с ошибкой.
    goto :fail
)
echo [OK] Этап 6: статические файлы собраны.
echo.

rem --------------------------------------------------------
rem 7. Создание расширенной демонстрационной базы
rem --------------------------------------------------------
echo [.] Этап 7: создаю расширенную демонстрационную базу данных...
.venv\Scripts\python.exe manage.py seed_business_demo
if not %errorlevel%==0 (
    echo [ОШИБКА] Этап 7: seed_business_demo завершился с ошибкой.
    goto :fail
)
echo [OK] Этап 7: демонстрационная база создана.
echo.

rem --------------------------------------------------------
rem 8. Проверка проекта
rem --------------------------------------------------------
echo [.] Этап 8: выполняю manage.py check...
.venv\Scripts\python.exe manage.py check
if not %errorlevel%==0 (
    echo [ОШИБКА] Этап 8: manage.py check обнаружил ошибки.
    goto :fail
)
echo [OK] Этап 8: проверка проекта пройдена.
echo.

echo ============================================================
echo  Установка MicroMarket Control v%VERSION% завершена.
echo.
echo  Создана демонстрационная база:
echo    - 7 холодильников;
echo    - 10 товаров;
echo    - 4100 продаж за 60 дней;
echo    - партии, остатки и списания;
echo    - рекомендации по пополнению.
echo.
echo  Для запуска используйте start_demo.bat
echo.
echo  Адрес: http://127.0.0.1:8000/
echo  Логин: demo
echo  Пароль: demo12345
echo.
echo  Все данные являются демонстрационными.
echo ============================================================

if "%NO_PAUSE%"=="1" goto :end_ok
pause
:end_ok
endlocal
exit /b 0

:fail
echo.
echo ============================================================
echo  Установка MicroMarket Control v%VERSION% НЕ завершена.
echo  Прокрутите окно выше, чтобы увидеть этап с ошибкой.
echo ============================================================
if "%NO_PAUSE%"=="1" goto :end_fail
pause
:end_fail
endlocal
exit /b 1
