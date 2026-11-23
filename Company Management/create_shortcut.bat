@echo off
cd /d "%~dp0"
set "TARGET=%~dp0run_app.bat"
set "ICON=%~dp0assets\logo.ico"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Company Management.lnk'); $s.TargetPath='%TARGET%'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%ICON%'; $s.Save()"
echo Shortcut created on the Desktop: Company Management
pause
