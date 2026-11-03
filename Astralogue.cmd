@echo off
setlocal
set "PYTHONUTF8=1"
if defined ASTRALOGUE_HOME (
  set "ASTRALOGUE_ROOT=%ASTRALOGUE_HOME%"
) else (
  set "ASTRALOGUE_ROOT=G:\Python\Python\Py_project\Astralogue"
)
if not exist "%ASTRALOGUE_ROOT%\.venv\Scripts\python.exe" (
  echo Astralogue Python environment not found. Set ASTRALOGUE_HOME to the project directory. 1>&2
  exit /b 1
)
"%ASTRALOGUE_ROOT%\.venv\Scripts\python.exe" -u "%ASTRALOGUE_ROOT%\tools\launch.py" %*
exit /b %errorlevel%
