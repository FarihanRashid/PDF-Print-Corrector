@echo off
setlocal

echo ============================================
echo  PDF Print Corrector - Build Script
echo ============================================

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found on PATH. Install Python 3.10-3.13 from python.org and try again.
    exit /b 1
)

python --version
echo If pip fails below with "no matching distribution", your Python
echo version is likely too new or too old for a dependency. Python
echo 3.10 - 3.13 (64-bit) is the safest range.

if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo Installing dependencies...
pip install --upgrade pip >nul
pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed.
    exit /b 1
)

echo Cleaning previous build...
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

echo Building portable executable...
pyinstaller PDFPrintCorrector.spec --noconfirm
if errorlevel 1 (
    echo Build failed.
    exit /b 1
)

echo.
echo ============================================
echo  Build complete.
echo  Portable exe: dist\PDFPrintCorrector.exe
echo  Copy that single file anywhere - no installer needed.
echo ============================================

endlocal
