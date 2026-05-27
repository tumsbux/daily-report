@echo off
:: ============================================================
::  Daily Dashboard Update
::  [1] fetch_missing_facts.py  - pull factXX.txt from MySQL
::  [2] rebuild_fraud_analysis.py - rebuild fraud_data.json
::  [3] update_dashboard.py    - update sales dashboard + push
::  [4] inject_fraud_only.py   - inject fraud data + push
::
::  Setup: Add this to Windows Task Scheduler
::    Action: Start a program
::    Program: F:\co work dashboard\run_daily_update.bat
::    Start in: F:\co work dashboard
::    Schedule: Daily at 08:00
:: ============================================================

cd /d "F:\co work dashboard"

echo [%date% %time%] Starting daily dashboard update...

:: Check Python is available (try py launcher first, then python, then python3)
where py >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON=py
) else (
    where python >nul 2>&1
    if %errorlevel% equ 0 (
        set PYTHON=python
    ) else (
        where python3 >nul 2>&1
        if %errorlevel% equ 0 (
            set PYTHON=python3
        ) else (
            echo ERROR: Python not found. Install from python.org
            pause
            exit /b 1
        )
    )
)

:: Install required packages if missing
%PYTHON% -c "import mysql.connector" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing mysql-connector-python...
    %PYTHON% -m pip install mysql-connector-python python-dateutil --quiet
)
%PYTHON% -c "import pandas" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing pandas...
    %PYTHON% -m pip install pandas openpyxl --quiet
)

:: [1] Fetch missing factXX.txt files from MySQL (sales data)
echo [%time%] Fetching missing fact files from MySQL...
%PYTHON% fetch_missing_facts.py
if %errorlevel% neq 0 (
    echo WARNING: fetch_missing_facts.py failed - continuing anyway
)

:: [2] Rebuild fraud data from MySQL → fraud_data.json
echo [%time%] Rebuilding fraud data from MySQL...
%PYTHON% rebuild_fraud_analysis.py --no-push
if %errorlevel% neq 0 (
    echo ERROR: rebuild_fraud