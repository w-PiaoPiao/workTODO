# 待办事项和便签 — 一键打包脚本
#
# 用法：
#     powershell -ExecutionPolicy Bypass -File tools\build.ps1
#
# 产物：dist\待办事项和便签v{版本号}.exe（版本号取自 app\config.py 的 APP_VERSION）
#
# 说明：
# - 通过 --exclude-module 排除未使用的 Qt 模块（WebEngine/Qml/Quick/3D/多媒体等），
#   显著减小体积（实测 46MB → 约 30MB 以下）
# - 必须保留 PySide6.QtSvg（QSvgRenderer 渲染 SVG 图标依赖）
# - 打包前请确认已安装：pip install -r requirements.txt -r requirements-dev.txt

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# ── 读取版本号（app/config.py 中的 APP_VERSION） ──────────────
$ConfigText = Get-Content -Raw -Encoding UTF8 (Join-Path $Root "app\config.py")
$VersionMatch = [regex]::Match($ConfigText, 'APP_VERSION\s*=\s*"([^"]+)"')
if (-not $VersionMatch.Success) {
    Write-Error "无法从 app\config.py 解析 APP_VERSION"
}
$Version = $VersionMatch.Groups[1].Value
$ExeName = "待办事项和便签v$Version"

Write-Host "==> 打包版本: $Version"
Write-Host "==> 产物名称: $ExeName.exe"

# ── 未使用的 Qt 模块排除清单 ─────────────────────────────────
$Excludes = @(
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebChannel",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtNetwork",
    "PySide6.QtSql",
    "PySide6.QtSerialPort",
    "PySide6.QtSensors",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtDBus",
    "PySide6.QtTest"
)

$ExcludeArgs = $Excludes | ForEach-Object { "--exclude-module", $_ }

# ── 执行 PyInstaller ─────────────────────────────────────────
pyinstaller `
    --onefile `
    --windowed `
    --name $ExeName `
    --icon "app\resources\icon.ico" `
    --add-data "app\resources;app\resources" `
    --clean `
    --noconfirm `
    @ExcludeArgs `
    main.py

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller 打包失败 (exit=$LASTEXITCODE)"
}

# ── 输出结果 ─────────────────────────────────────────────────
$Out = Join-Path $Root "dist\$ExeName.exe"
if (Test-Path $Out) {
    $SizeMB = [math]::Round((Get-Item $Out).Length / 1MB, 1)
    Write-Host ""
    Write-Host "==> 打包完成: $Out ($SizeMB MB)"
} else {
    Write-Error "未找到产物: $Out"
}
