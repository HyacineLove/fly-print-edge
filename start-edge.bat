@echo off
set PYTHONUNBUFFERED=1
"%~dp0flyprint-edge.exe" > "%~dp0logs\edge.log" 2>&1
