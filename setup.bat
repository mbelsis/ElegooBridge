@echo off
rem ElegooBridge setup for Windows. Double-click this file, or run it from a command prompt.
rem It runs scripts\setup.ps1 with PowerShell, which is built into Windows.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1"
