@echo off
rem Builds PDF Redactor into a standalone Windows program (no Python/Tesseract needed on the target PC).
rem Usage: put launcher.py next to this file and double-click. Result: dist\PDFRedactor.zip
rem Optional: set TESSERACT_DIR=C:\path\to\Tesseract-OCR before running, if Tesseract is not found automatically.
setlocal
cd /d "%~dp0"
title PDF Redactor - build
echo === PDF Redactor: building Windows program ===
echo.

rem ---------- 1. project files
if not exist "app\main.py" goto err_noapp
if not exist "launcher.py" goto err_nolauncher
if not exist "tessdata\rus.traineddata" goto err_nomodels
if not exist "tessdata\eng.traineddata" goto err_nomodels

powershell -NoProfile -Command "if ((Get-Location).Path -match '[^\x00-\x7F]') { exit 1 }"
if errorlevel 1 (
  echo WARNING: the project path contains non-Latin characters.
  echo          Building works, but run the finished program from a Latin-only path, e.g. C:\PDFRedactor
  echo.
)

rem ---------- 2. Python 3.11+
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto err_nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto err_oldpython

rem ---------- 3. virtual environment and packages
if exist ".venv\Scripts\python.exe" goto venv_ok
echo [1/5] Creating virtual environment .venv ...
%PY% -m venv .venv
:venv_ok
if not exist ".venv\Scripts\python.exe" goto err_venv
set "VPY=.venv\Scripts\python.exe"
echo [2/5] Installing packages (the first time takes a few minutes) ...
"%VPY%" -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller
if errorlevel 1 goto err_pip

rem ---------- 4. find Tesseract
set "TESS="
if defined TESSERACT_DIR set "TESS=%TESSERACT_DIR%\tesseract.exe"
if not defined TESS if exist ".env" for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b /c:"TESSERACT_CMD=" ".env"`) do set "TESS=%%B"
if not defined TESS if exist "%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe" set "TESS=%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"
if not defined TESS if exist "%ProgramFiles%\Tesseract-OCR\tesseract.exe" set "TESS=%ProgramFiles%\Tesseract-OCR\tesseract.exe"
if not defined TESS if exist "%ProgramFiles(x86)%\Tesseract-OCR\tesseract.exe" set "TESS=%ProgramFiles(x86)%\Tesseract-OCR\tesseract.exe"
if not defined TESS for /f "delims=" %%P in ('where tesseract 2^>nul') do if not defined TESS set "TESS=%%P"
if not defined TESS goto err_notess
if not exist "%TESS%" goto err_notess
for %%D in ("%TESS%") do set "TESS_DIR=%%~dpD"
set "TESS_DIR=%TESS_DIR:~0,-1%"
rem a real Tesseract folder contains its DLLs (a winget link folder does not)
if not exist "%TESS_DIR%\*.dll" goto err_tessdir
echo       Tesseract: %TESS_DIR%

rem ---------- 5. build
echo [3/5] Building the program (1-3 minutes) ...
if exist "dist\PDFRedactor" rmdir /s /q "dist\PDFRedactor"
"%VPY%" -m PyInstaller --noconfirm --clean --log-level WARN --onedir --name PDFRedactor --console ^
  --add-data "app\static;app\static" --add-data "tessdata;tessdata" ^
  --collect-submodules uvicorn --collect-all pymupdf --hidden-import python_multipart ^
  launcher.py
if errorlevel 1 goto err_build
if not exist "dist\PDFRedactor\PDFRedactor.exe" goto err_build

rem ---------- 6. embed Tesseract
echo [4/5] Embedding Tesseract ...
robocopy "%TESS_DIR%" "dist\PDFRedactor\tesseract" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto err_copy
if not exist "dist\PDFRedactor\tesseract\tesseract.exe" goto err_copy

rem ---------- 7. zip
echo [5/5] Packing dist\PDFRedactor.zip ...
if exist "dist\PDFRedactor.zip" del /q "dist\PDFRedactor.zip"
tar -a -c -f "dist\PDFRedactor.zip" -C dist PDFRedactor >nul 2>nul
if errorlevel 1 powershell -NoProfile -Command "Compress-Archive -Path 'dist\PDFRedactor' -DestinationPath 'dist\PDFRedactor.zip' -Force"
if not exist "dist\PDFRedactor.zip" goto err_zip

echo.
echo === Done ===
echo Program: dist\PDFRedactor\PDFRedactor.exe
echo Archive: dist\PDFRedactor.zip
echo On another PC: unpack the archive to a Latin-only path (e.g. C:\PDFRedactor) and run PDFRedactor.exe
goto end

:err_noapp
echo ERROR: app\main.py not found. Put this file into the project folder (next to the "app" folder).
goto end
:err_nolauncher
echo ERROR: launcher.py not found. Put launcher.py next to this file.
goto end
:err_nomodels
echo ERROR: tessdata\rus.traineddata or tessdata\eng.traineddata not found.
echo        Use redactor_with_models.zip or download the models (see docs\setup.md).
goto end
:err_nopython
echo ERROR: Python not found. Install Python 3.11+ from python.org with "Add python.exe to PATH".
goto end
:err_oldpython
echo ERROR: Python 3.11 or newer is required (found: %PY%).
goto end
:err_venv
echo ERROR: could not create the virtual environment .venv
goto end
:err_pip
echo ERROR: package installation failed. Most likely no access to pypi.org (proxy or certificate).
echo        Send the error text above.
goto end
:err_notess
echo ERROR: Tesseract not found. Install it, or run:  set TESSERACT_DIR=C:\path\to\Tesseract-OCR
echo        and then start build_windows.bat from the same window.
goto end
:err_tessdir
echo ERROR: %TESS_DIR% does not look like a Tesseract folder (no DLL files).
echo        Find the real folder and run:  set TESSERACT_DIR=C:\path\to\Tesseract-OCR
goto end
:err_build
echo ERROR: PyInstaller build failed. Send the error text above.
goto end
:err_copy
echo ERROR: could not copy Tesseract into dist\PDFRedactor\tesseract
goto end
:err_zip
echo ERROR: could not create dist\PDFRedactor.zip (the program itself is ready in dist\PDFRedactor).
goto end

:end
echo.
pause
endlocal
