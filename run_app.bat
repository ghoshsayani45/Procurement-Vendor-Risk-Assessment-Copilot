@echo off
REM Double-click to start the reviewer UI on http://localhost:8501 . Arguments are passed on, e.g.  run_app.bat -Mode both
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_app.ps1" %*
