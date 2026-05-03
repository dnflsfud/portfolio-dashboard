@echo off
REM =============================================================
REM Self_Port  daily-run launcher  (Windows)
REM
REM Sequence:
REM   1) Sync Self_Port.xlsx from parent (your editing copy) into the repo
REM   2) If masters newer than filtered  -> full sync_filtered_from_masters.py
REM      else                            -> update_px_last.py (yfinance)
REM   3) git add / commit / push    (Streamlit Cloud will auto-redeploy)
REM   4) Open browser
REM   5) Launch local Streamlit on http://localhost:8501
REM
REM Set NO_PUSH=1 to skip git push (e.g. while debugging).
REM =============================================================
setlocal EnableDelayedExpansion
chcp 65001 >nul

set "VENV_PY=C:\Users\westl\PycharmProjects\pythonProject\venv_vf_new\Scripts\python.exe"
set "PROJ_DIR=%~dp0"
cd /d "%PROJ_DIR%"

set "PARENT_SELF_PORT=C:\Users\westl\PycharmProjects\pythonProject\venv_vf_new\port\Self_Port.xlsx"
set "REPO_SELF_PORT=%PROJ_DIR%Self_Port.xlsx"
set "MASTER_SP500=C:\Users\westl\PycharmProjects\pythonProject\S&P500.xlsx"
set "MASTER_INDEX=C:\Users\westl\PycharmProjects\pythonProject\Index.xlsx"
set "FILTERED=%PROJ_DIR%data\S&P500_filtered.xlsx"

REM ---- Step 0 — sync Self_Port.xlsx from parent into the repo ----
echo.
echo ============================================================
echo  [0/5] Sync Self_Port.xlsx from parent into the repo
echo ============================================================
if exist "%PARENT_SELF_PORT%" (
    copy /Y "%PARENT_SELF_PORT%" "%REPO_SELF_PORT%" >nul
    echo  copied parent -^> repo: Self_Port.xlsx
) else (
    echo  ! parent Self_Port.xlsx not found, using repo copy as-is
)

REM ---- Step 1 — decide refresh strategy --------------------------
set "NEED_SYNC=0"
if not exist "%FILTERED%" (
    set "NEED_SYNC=1"
) else (
    for /f "delims=" %%t in ('powershell -NoProfile -Command "if ((Test-Path '%MASTER_SP500%') -and ((Get-Item '%MASTER_SP500%').LastWriteTime -gt (Get-Item '%FILTERED%').LastWriteTime)) { 'newer' }"') do set "SP_NEWER=%%t"
    for /f "delims=" %%t in ('powershell -NoProfile -Command "if ((Test-Path '%MASTER_INDEX%') -and ((Get-Item '%MASTER_INDEX%').LastWriteTime -gt (Get-Item '%FILTERED%').LastWriteTime)) { 'newer' }"') do set "IX_NEWER=%%t"
    if "!SP_NEWER!"=="newer" set "NEED_SYNC=1"
    if "!IX_NEWER!"=="newer" set "NEED_SYNC=1"
)

echo.
echo ============================================================
if "%NEED_SYNC%"=="1" (
    echo  [1/5] Master Bloomberg dumps are newer ^> full sync rebuild
    echo ============================================================
    "%VENV_PY%" "_workspace\sync_filtered_from_masters.py"
    if errorlevel 1 (
        echo.
        echo  ! Full sync failed. Trying lightweight PX_LAST refresh instead...
        "%VENV_PY%" "_workspace\update_px_last.py"
    )
) else (
    echo  [1/5] Filtered file is up-to-date with masters
    echo        ^> running lightweight PX_LAST refresh ^(yfinance^)
    echo ============================================================
    "%VENV_PY%" "_workspace\update_px_last.py"
    if errorlevel 1 (
        echo.
        echo  ! PX_LAST refresh failed - continuing with old data anyway.
    )
)

REM ---- Step 2 — git add / commit / push (Streamlit Cloud autodeploys) ----
echo.
echo ============================================================
echo  [2/5] Pushing data updates to GitHub
echo ============================================================
if defined NO_PUSH (
    echo  NO_PUSH set ^> skipping git push
) else (
    git add "Self_Port.xlsx" "data/S&P500_filtered.xlsx" 2>nul
    REM Only commit if there's a staged change.
    git diff --cached --quiet
    if errorlevel 1 (
        for /f "tokens=* delims=" %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH:mm"') do set "STAMP=%%d"
        git commit -m "data: refresh !STAMP!"
        if errorlevel 1 (
            echo  ! commit failed
        ) else (
            for /f "delims=" %%b in ('git branch --show-current') do set "BRANCH=%%b"
            echo  pushing !BRANCH! to origin ...
            git push origin "!BRANCH!"
            if errorlevel 1 (
                echo  ! push failed - Streamlit Cloud will not pick up the latest data.
                echo    ^(check 'git pull' or auth status^)
            ) else (
                echo  pushed - Streamlit Cloud should redeploy in ~2 minutes.
            )
        )
    ) else (
        echo  no data changes to commit
    )
)

REM ---- Step 3 — Open the browser ----------------------------------
echo.
echo ============================================================
echo  [3/5] Opening browser ^> http://localhost:8501
echo ============================================================
start "" "http://localhost:8501"

REM ---- Step 4 — Run local Streamlit -------------------------------
echo.
echo ============================================================
echo  [4/5] Starting local Streamlit ^(Ctrl+C in this window to stop^)
echo ============================================================
"%VENV_PY%" -m streamlit run "Self_port_cloud.py" ^
    --server.headless true ^
    --server.port 8501 ^
    --server.runOnSave true ^
    --browser.gatherUsageStats false

endlocal
