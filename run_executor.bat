@echo off
cd /d "%~dp0"
title RemoteLab Executor (Worker)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_cluster_executor.ps1"
pause
