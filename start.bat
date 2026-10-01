@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" main.py
) else (
  echo Run install.ps1 first, or install requirements.txt in your own Python environment.
  pause
)
