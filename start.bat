@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM ── 语言检测：仅中文系统区域显示中文，其他情况一律英文 ──────────
set "ZH=0"
set "SYS_LOCALE="
for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-WinSystemLocale).Name" 2^>nul') do set "SYS_LOCALE=%%i"
if not defined SYS_LOCALE (
    for /f "tokens=2 delims==" %%i in ('wmic os get locale /value ^| findstr "="') do set "SYS_LOCALE=%%i"
)
set "SYS_LOCALE=%SYS_LOCALE: =%"
if not defined SYS_LOCALE set "SYS_LOCALE=en-US"
echo %SYS_LOCALE% | findstr /i "^zh" >nul && set "ZH=1"

echo ================================================
call :msg "   Agnes Video Generator - 免费 AI 短视频生成" "   Agnes Video Generator - Free AI Short Video Generator"
call :msg "   (Windows 一键启动)" "   (One-click launch for Windows)"
echo ================================================
echo.

REM ── 环境校验 ────────────────────────────────
REM Python 探测：优先 `python`，未命中回退官方 `py` 启动器（py -3）。
REM 两者都没有才报错。后续 venv 创建 / 版本检查统一走 %PY_CMD% %PY_ARGS%。
set "PY_CMD=python"
set "PY_ARGS="
where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        call :msg "[X] 未找到 python / py，请先安装 Python 3.10+：https://www.python.org/downloads/" "[X] Neither python nor py found. Please install Python 3.10+: https://www.python.org/downloads/"
        pause
        exit /b 1
    )
    set "PY_CMD=py"
    set "PY_ARGS=-3"
)

%PY_CMD% %PY_ARGS% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 (
    %PY_CMD% %PY_ARGS% --version
    call :msg "[X] Python 版本过低，需要 3.10+" "[X] Python version too old. Required: 3.10+"
    pause
    exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
    call :msg "[X] 未找到 ffmpeg，视频处理依赖 ffmpeg" "[X] ffmpeg not found. Video processing requires ffmpeg:"
    call :msg "     安装方式：winget install Gyan.FFmpeg   （安装后请重新打开终端）" "     Install: winget install Gyan.FFmpeg   (restart terminal afterwards)"
    call :msg "     或前往 https://www.gyan.dev/ffmpeg/builds/ 下载并加入 PATH" "     Or download from https://www.gyan.dev/ffmpeg/builds/ and add to PATH"
    pause
    exit /b 1
)

REM 检查端口 8765 是否被占用
netstat -ano | findstr ":8765" >nul 2>nul
if not errorlevel 1 (
    call :msg "[W] 端口 8765 已被占用，请先关闭占用进程后重试" "[W] Port 8765 is already in use. Close the occupying process and retry."
    pause
    exit /b 1
)

call :msg "[OK] 环境检查通过" "[OK] Environment check passed"
echo.

set "VENV_DIR=.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"

if not exist "%VENV_PYTHON%" (
    call :msg "[1/3] 创建虚拟环境..." "[1/3] Creating virtual environment..."
    %PY_CMD% %PY_ARGS% -m venv "%VENV_DIR%"
)

call :msg "[2/3] 安装依赖..." "[2/3] Installing dependencies..."
"%VENV_PIP%" install -q -r requirements.txt
if errorlevel 1 (
    call :msg "[X] 依赖安装失败，请检查网络后重试" "[X] Dependency installation failed. Check your network and retry."
    pause
    exit /b 1
)

call :msg "[3/3] 启动服务..." "[3/3] Starting server..."
echo.
call :msg "   浏览器将自动打开 http://localhost:8765" "   The browser will open http://localhost:8765 automatically"
call :msg "   按 Ctrl+C 停止服务" "   Press Ctrl+C to stop the server"
echo.

REM 服务就绪（http://localhost:8765 可连通）后再开浏览器，避免首次建 venv/装依赖
REM 耗时超 3s 时浏览器打开即"无法访问"。最多等待 60s（120 × 0.5s），超时静默放弃，
REM 用户可手动访问。判定语义与 start.sh 的 wait_ready 一致（可连通即视为就绪）。
start "" /b powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "for ($i=0; $i -lt 120; $i++) { try { $r = Invoke-WebRequest -Uri 'http://localhost:8765/' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { Start-Process 'http://localhost:8765'; break } } catch {} ; Start-Sleep -Milliseconds 500 }"

"%VENV_PYTHON%" server.py

echo.
call :msg "服务已停止。" "Server stopped."
pause
endlocal
goto :EOF

REM ── 双语消息子程序：call :msg "中文" "English" ──────────
:msg
if "%ZH%"=="1" (
    echo %~1
) else (
    echo %~2
)
exit /b
