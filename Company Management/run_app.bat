@echo off
cd /d "%~dp0"
title Company Management
echo ==========================================
echo   Company Management - local run
echo   Keep this window open while you work.
echo   Open in browser:  http://localhost:8501
echo ==========================================
echo.
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"
where py >nul 2>nul
if %errorlevel%==0 goto usepy
where python >nul 2>nul
if %errorlevel%==0 goto usepython
echo Python was not found. Install Python 3 and tick Add to PATH.
pause
exit /b 1
:usepy
py -3 -m streamlit run app.py
goto done
:usepython
python -m streamlit run app.py
:done
echo.
echo The program stopped. If there was an error above, run:
echo   py -3 -m pip install -r requirements.txt
pause
