@echo off
cd /d "%~dp0"
python -m server.app.main --headless
