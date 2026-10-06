@echo off
rem ---------------------------------------------------------------------------
rem  Disconnect the ms43diff MCP server from Claude Desktop.
rem  Only the "ms43" entry is removed; other servers and settings stay.
rem  Keep this file next to ms43-ai-tuner-mcp.exe.
rem ---------------------------------------------------------------------------
setlocal
chcp 65001 >nul 2>&1
set "HERE=%~dp0"
if exist "%HERE%ms43-ai-tuner-mcp.exe" goto exe
if exist "%HERE%mcp_main.py" goto py
echo ms43-ai-tuner-mcp.exe not found next to this file: "%HERE%"
goto end

:exe
"%HERE%ms43-ai-tuner-mcp.exe" --uninstall
goto end

:py
python "%HERE%mcp_main.py" --uninstall

:end
echo.
pause
