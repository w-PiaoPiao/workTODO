# 待办事项和便签 — 项目指引

## 项目概述

Windows 桌面悬浮待办事项软件，支持快速记录、进度跟踪、办结归档。

## 文档体系

| 文档 | 路径 | 说明 |
|------|------|------|
| 需求文档 | `docs/需求文档.md` | 用户需求与功能边界 |
| 技术方案 | `docs/技术方案.md` | 架构设计、技术选型、数据模型 |
| 设计规范 | `docs/设计规范.md` | UI 视觉风格、交互规范 |
| 开发规范 | `docs/开发规范.md` | 编码规范、测试要求 |
| 执行步骤 | `docs/执行步骤.md` | 分步实施计划与进度 |
| 开发日志 | `dev-log/YYYY-MM-DD.md` | 每日开发记录 |

## 开发流程

1. 每次开始工作前，阅读 `docs/执行步骤.md` 确定当前步骤
2. 开发后更新 `dev-log/` 记录完成事项
3. 每完成一个步骤，在 `docs/执行步骤.md` 勾选确认

## 技术栈

- Python 3.12 + PySide6
- 数据持久化：本地 JSON 文件（原子写入防损坏）
- 图像处理：Pillow（桌宠白底去除）
- 打包：PyInstaller（`tools/build.ps1`，含未用 Qt 模块排除）
- 静态检查：ruff（`pyproject.toml`），pre-commit 钩子可选安装

## 启动方式

```bash
python main.py
```

## 版本规则

每次打包即发布一个新版本。版本号遵守**语义化版本**（SemVer），格式 `主版本.次版本.修订号`。

- 默认情况下，修订号（最后一位）加 1：`0.1.1` → `0.1.2` → `0.1.3`
- 若有特别要求（如重大更新），再按需调整主版本或次版本

打包前需同步更新 `app/config.py` 中的 `APP_VERSION`。

## 打包约定

打包 EXE 时，文件名须附加 `config.py` 中 `AppConfig.APP_VERSION` 定义的版本号，格式为 `待办事项和便签v{版本号}.exe`。

**推荐使用一键打包脚本**（自动读取版本号、排除未使用的 Qt 模块，产物更小）：

```bash
powershell -ExecutionPolicy Bypass -File tools\build.ps1
```

等价的手动命令（示例：当前版本 0.4.4）：

```bash
pyinstaller --onefile --windowed \
    --name "待办事项和便签v0.4.4" \
    --icon "app/resources/icon.ico" \
    --add-data "app/resources;app/resources" \
    --exclude-module PySide6.QtWebEngineCore \
    --exclude-module PySide6.QtWebEngineWidgets \
    --exclude-module PySide6.QtQml \
    --exclude-module PySide6.QtQuick \
    --exclude-module PySide6.QtMultimedia \
    --exclude-module PySide6.Qt3DCore \
    --exclude-module PySide6.QtNetwork \
    --clean --noconfirm \
    main.py
```

注意：**必须保留 PySide6.QtSvg**（QSvgRenderer 渲染 SVG 图标依赖）。

应用图标源文件为 `app/resources/icon.ico`，如需修改请运行 `python tools/make_icon.py` 重新生成。
