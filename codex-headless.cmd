@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0codex-headless.ps1" %*
exit /b %ERRORLEVEL%

