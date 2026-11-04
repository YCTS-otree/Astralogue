@echo off
setlocal
set "PYTHONUTF8=1"
if defined ASTRALOGUE_HOME (
  set "ASTRALOGUE_ROOT=%ASTRALOGUE_HOME%"
) else (
  set "ASTRALOGUE_ROOT=G:\Python\Python\Py_project\Astralogue"
)
if not exist "%ASTRALOGUE_ROOT%\.venv\Scripts\python.exe" (
  echo Python environment not found. Set ASTRALOGUE_HOME to the project directory.
  pause
  exit /b 1
)
"%ASTRALOGUE_ROOT%\.venv\Scripts\python.exe" -u "%ASTRALOGUE_ROOT%\tools\audit_review_launcher.py" %*
if errorlevel 1 pause
