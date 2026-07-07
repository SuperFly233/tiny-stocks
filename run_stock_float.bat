@echo off
cd /d "%~dp0"
wscript.exe //B "%~dp0run_stock_float_silent.vbs"
exit /b
