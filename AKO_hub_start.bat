@echo off
chcp 65001 >nul
title AKO_hub Launcher
PowerShell -NoProfile -ExecutionPolicy Bypass -File "%~dp0AKO_hub_start.ps1"
