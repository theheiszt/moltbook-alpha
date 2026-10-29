@echo off
REM Moltbook Alpha — 1-Click Local CI Pre-Flight Runner
python scripts\run_checks.py
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Pre-flight CI checks failed.
    exit /b %ERRORLEVEL%
)
echo [SUCCESS] All pre-flight CI checks passed cleanly.
