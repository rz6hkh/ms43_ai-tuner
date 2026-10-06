@echo off
rem ---------------------------------------------------------------------------
rem  Connect the ms43diff MCP server to Claude Desktop.
rem
rem  How to use:
rem    * drag your .xdf and .bin files onto this file, or
rem    * double-click it and pick the files in the dialogs.
rem
rem  Keep this file next to ms43-ai-tuner-mcp.exe. Nothing personal is stored here:
rem  the paths you choose go into Claude Desktop's own config file
rem  (classic or Microsoft Store install is detected, a .bak copy is kept).
rem  Run it with Claude Desktop fully closed (tray icon -> Quit).
rem  To force the answer language add --lang en or --lang ru after --install.
rem ---------------------------------------------------------------------------
setlocal
chcp 65001 >nul 2>&1
set "HERE=%~dp0"
if exist "%HERE%ms43-ai-tuner-mcp.exe" goto exe
if exist "%HERE%mcp_main.py" goto py
echo ms43-ai-tuner-mcp.exe not found next to this file: "%HERE%"
goto end

:exe
"%HERE%ms43-ai-tuner-mcp.exe" --install %*
goto end

:py
python "%HERE%mcp_main.py" --install %*

:end
echo.
pause
