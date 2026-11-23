@echo off
cd /d "%~dp0"
title RemoteLab Scheduler (Master)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_cluster_scheduler.ps1"
pause
