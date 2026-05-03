@echo off
REM =============================================================
REM Sync S&P500_filtered.xlsx from the Bloomberg masters.
REM
REM Run this when you've refreshed:
REM   C:\Users\westl\PycharmProjects\pythonProject\S&P500.xlsx
REM   C:\Users\westl\PycharmProjects\pythonProject\Index.xlsx
REM
REM What it does:
REM   1) reads both master files
REM   2) filters every wide panel to Universe.Ticker only (port/Self_Port.xlsx)
REM   3) merges any Universe ticker missing from S&P500.xlsx using Index.xlsx
REM   4) for PX_LAST, fills any still-missing ticker from Yahoo Finance
REM   5) writes port/data/S&P500_filtered.xlsx (timestamped backup is kept)
REM
REM Typical cadence: weekly or whenever you re-download Bloomberg dumps.
REM =============================================================
setlocal
chcp 65001 >nul

set "VENV_PY=C:\Users\westl\PycharmProjects\pythonProject\venv_vf_new\Scripts\python.exe"
set "PROJ_DIR=%~dp0"

cd /d "%PROJ_DIR%"

echo.
echo ============================================================
echo  Rebuilding port\data\S^&P500_filtered.xlsx from masters
echo ============================================================
echo.

"%VENV_PY%" "_workspace\sync_filtered_from_masters.py"
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo  Done. The Streamlit app will pick up the new file automatically.
) else (
    echo  Sync failed with exit code %RC%.
    echo  Old filtered file is preserved (look for sync-backup-*.xlsx in data\).
)
echo.
pause
endlocal
