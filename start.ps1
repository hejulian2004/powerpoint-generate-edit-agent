#Requires -Version 7.0
<#
.SYNOPSIS
    PPT-Agent-Studio 一键启动脚本 (PowerShell 7+)。

.DESCRIPTION
    使用仓库内 .venv 解释器启动平台，并自动检查 Python 依赖与前端 node_modules：
      * 默认  : 统一生产模式 (FastAPI 托管后端 + 已构建前端 + WebSocket)，http://127.0.0.1:8000
      * -Dev  : 开发热重载模式 (FastAPI:8000 + Vite:5173)
      * -Build: 启动前强制重新构建前端 dist
      * -Check: 仅校验环境后退出 (不安装依赖、不构建前端)

.PARAMETER Dev
    开发模式：启动 Vite 开发服务器 (前端热重载) 并启用后端热重载 (--reload)。

.PARAMETER Build
    启动前执行 npm run build 重新构建前端产物。

.PARAMETER Install
    强制重新安装 Python 依赖。

.PARAMETER NoBrowser
    启动后不自动打开浏览器。

.PARAMETER Check
    只做环境检查，不启动服务，也不安装依赖或构建前端。

.PARAMETER BindHost
    后端监听地址 (默认 127.0.0.1)，别名 -Host。

.PARAMETER Port
    后端端口 (默认 8000)。

.EXAMPLE
    pwsh -ExecutionPolicy Bypass -File .\start.ps1
    pwsh -ExecutionPolicy Bypass -File .\start.ps1 -Dev
    pwsh -ExecutionPolicy Bypass -File .\start.ps1 -Build -NoBrowser
    pwsh -ExecutionPolicy Bypass -File .\start.ps1 -Check
#>
[CmdletBinding()]
param(
    [switch]$Dev,
    [switch]$Build,
    [switch]$Install,
    [switch]$NoBrowser,
    [switch]$Check,

    [Alias("Host", "HostAddress")]
    [string]$BindHost = "127.0.0.1",

    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$MainPy = Join-Path $Root "main.py"
$FrontendDir = Join-Path $Root "frontend"
$Requirements = Join-Path $Root "requirements.txt"
$MinNodeMajor = 24

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message)   { Write-Host "  [OK] $Message" -ForegroundColor Green }
function Write-Note([string]$Message) { Write-Host "  [!]  $Message" -ForegroundColor Yellow }
function Fail([string]$Message)       { Write-Host "  [x]  $Message" -ForegroundColor Red; exit 1 }

# 1. 校验仓库结构
if (-not (Test-Path -LiteralPath $MainPy)) {
    Fail "未找到 main.py，请在仓库根目录运行本脚本。"
}
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Fail "未找到虚拟环境 .venv。请先执行: python -m venv .venv"
}

# 2. 校验 Python 依赖
Write-Step "检查 Python 依赖 (.venv)"
$pythonProbe = @(
    "import lxml, pdfplumber, reportlab, pytest, fastapi, uvicorn, pydantic, multipart"
    "import websockets, httpx, dotenv, PIL, pypdfium2, langgraph, langchain_core, langchain_openai"
) -join "; "
$depsOk = $false
if (-not $Install) {
    try {
        & $VenvPython -c $pythonProbe *> $null
        $depsOk = ($LASTEXITCODE -eq 0)
        if ($depsOk) {
            & $VenvPython -m pip check *> $null
            $depsOk = ($LASTEXITCODE -eq 0)
        }
    } catch {
        $depsOk = $false
    }
}
if ($depsOk) {
    Write-Ok "Python 依赖已就绪。"
} elseif ($Check) {
    Write-Note "Python 依赖缺失或不完整（去掉 -Check 运行会自动安装）。"
} else {
    Write-Note "依赖缺失或指定了 -Install，正在安装 (pip install -r requirements.txt)..."
    & $VenvPython -m pip install -r $Requirements
    if ($LASTEXITCODE -ne 0) { Fail "Python 依赖安装失败。" }
    & $VenvPython -m pip install -e $Root
    if ($LASTEXITCODE -ne 0) { Fail "本地包 (pip install -e .) 安装失败。" }
    Write-Ok "Python 依赖已就绪。"
}

# 3. 定位 npm 并校验 Node 版本
$Npm = "npm.cmd"
if (-not (Get-Command $Npm -ErrorAction SilentlyContinue)) {
    $Npm = "npm"
}
$npmAvailable = $null -ne (Get-Command $Npm -ErrorAction SilentlyContinue)
if ($npmAvailable) {
    $nodeVersion = (& node --version) 2>$null
    if ($nodeVersion -match '^v(\d+)') {
        $nodeMajor = [int]$Matches[1]
        if ($nodeMajor -lt $MinNodeMajor) {
            Fail "Node.js 版本过低 (检测到 $nodeVersion)，需要 >= $MinNodeMajor。"
        }
    } else {
        Write-Note "无法解析 Node.js 版本 ($nodeVersion)，已跳过版本校验。"
    }
}

# 4. 前端依赖 / 构建
$nodeModules = Join-Path $FrontendDir "node_modules"
$indexHtml = Join-Path $FrontendDir "dist\index.html"

if ($Dev -or $Build) {
    if (-not $npmAvailable) {
        Fail "未找到 npm，请安装 Node.js (>= $MinNodeMajor) 后重试。"
    }
    if (-not (Test-Path -LiteralPath $nodeModules)) {
        if ($Check) {
            Write-Note "前端依赖未安装 (node_modules 缺失)。"
        } else {
            Write-Step "安装前端依赖 (npm install)"
            Push-Location $FrontendDir
            try {
                & $Npm install
                if ($LASTEXITCODE -ne 0) { Fail "npm install 失败。" }
            } finally {
                Pop-Location
            }
            Write-Ok "前端依赖已就绪。"
        }
    } else {
        Write-Ok "前端依赖已就绪。"
    }
}

if ($Build) {
    if ($Check) {
        Write-Note "已跳过前端构建 (npm run build)：-Check 不产生副作用。"
    } else {
        Write-Step "构建前端产物 (npm run build)"
        Push-Location $FrontendDir
        try {
            & $Npm run build
            if ($LASTEXITCODE -ne 0) { Fail "前端构建失败。" }
        } finally {
            Pop-Location
        }
        Write-Ok "前端构建完成。"
    }
} elseif (-not $Dev) {
    if (Test-Path -LiteralPath $indexHtml) {
        Write-Ok "前端产物已就绪。"
    } elseif ($Check) {
        if ($npmAvailable) {
            Write-Note "未找到前端产物 dist/index.html（去掉 -Check 运行会自动构建）。"
        } else {
            Write-Note "未找到前端产物且未安装 npm；将仅提供后端 API。"
        }
    } elseif ($npmAvailable) {
        Write-Note "未找到前端产物，正在自动构建 (npm run build)..."
        Push-Location $FrontendDir
        try {
            if (-not (Test-Path -LiteralPath $nodeModules)) {
                & $Npm install
                if ($LASTEXITCODE -ne 0) { Fail "npm install 失败。" }
            }
            & $Npm run build
            if ($LASTEXITCODE -ne 0) { Fail "前端构建失败。" }
        } finally {
            Pop-Location
        }
        Write-Ok "前端构建完成。"
    } else {
        Write-Note "未找到前端产物且未安装 npm；将仅提供后端 API。"
    }
}

if ($Check) {
    if ($depsOk) {
        $modeText = if ($Dev) { "开发热重载" } else { "统一生产" }
        Write-Ok "环境检查通过 (模式: $modeText)。"
        exit 0
    }
    Fail "环境检查未通过：Python 依赖缺失或不完整。"
}

# 5. 组装并启动
$pyArgs = @()
if ($Dev) { $pyArgs += "--dev"; $pyArgs += "--reload" }
if ($NoBrowser) { $pyArgs += "--no-browser" }
$pyArgs += @("--host", $BindHost, "--port", "$Port")

$mode = if ($Dev) { "开发热重载 (FastAPI:8000 + Vite:5173)" } else { "统一生产 (FastAPI 托管前后端)" }
Write-Step "启动 PPT-Agent-Studio — $mode"
Write-Host "  后端入口: http://${BindHost}:${Port}" -ForegroundColor DarkGray
Write-Host "  API 文档: http://${BindHost}:${Port}/docs" -ForegroundColor DarkGray
if ($Dev) { Write-Host "  前端入口: http://localhost:5173" -ForegroundColor DarkGray }
Write-Host "  按 Ctrl+C 可安全停止所有服务。" -ForegroundColor DarkGray
Write-Host ""

Push-Location $Root
try {
    & $VenvPython $MainPy @pyArgs
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
