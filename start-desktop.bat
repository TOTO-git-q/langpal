@echo off
rem LangPal desktop app launcher (ASCII only, no CJK in this file)
cd /d "%~dp0desktop"
if not exist node_modules (
  call npm install
)
call npx electron .
