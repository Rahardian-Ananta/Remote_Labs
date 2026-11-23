@echo off
cd /d "%~dp0"
title RemoteLab Local Cluster
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_local.ps1"
pause
