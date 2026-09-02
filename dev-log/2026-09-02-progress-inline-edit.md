# 开发日志 2026-09-02（二）

## 功能：进度条目双击行内就地编辑（与标题编辑一致）

### 需求

已录入的进度条目也要支持双击修改，交互与标题双击编辑保持一致。

### 原状与差距

- 标题：双击 → 行内就地编辑（原位输入框，Enter/失焦提交、Esc 取消）。
- 进度：仅展开模式可双击，且弹 `QInputDialog` 模态对话框；
  **折叠模式的最新一条进度不可编辑**（`ElidedLabel` 鼠标透传）。

### 改动（`app/views/progress_widget.py`）

1. **折叠行换可编辑 label**：最新一条进度的 `ElidedLabel` → `ClickableElidedLabel`
   （关闭鼠标透传、双击回调、IBeam 光标），样式与展开行统一（hover accent 描边
   提示可编辑）。删除按钮仍仅在展开模式提供。
2. **行内就地编辑取代对话框**：双击任意进度条目（折叠行 = 最新一条，展开行 =
   对应条目）→ 该行原地变同高度 `_EditInput` 输入框（预填原文、全选体验与
   添加模式一致）——隐藏行内展示控件、原位 `insertWidget(0)`，不新增行。
   Enter / 失焦触发 `_commit_edit` 提交，Esc 触发 `_cancel_edit` 取消。
3. **提交语义**（对齐控制器 `_on_edit_progress`）：空文本或 strip 后未变更
   → 静默退出不发射；有变更 → `signal_progress_edited(entry_id, text)`，
   沿既有链路 `TodoCard → ExpandedView → AppController` 落盘+刷新，控制器无改动。
   保留 `_generation` 防御：emit 链路中数据刷新已重建行时跳过二次 `_refresh`。
4. **模式互斥**：编辑/添加互斥——编辑中禁"＋"与提示行（`_on_add_button_clicked`、
   `_enter_add_mode_in_row`、`_HoverRow.can_reveal` 均加 `_edit_input` 守卫），
   添加中双击无效。
5. **生命周期**：`set_entries`/`_refresh` 重建行时同步丢弃 `_edit_input`
   （外部数据刷新自动退出编辑，未提交内容作废，与添加模式行为一致）。

行为影响：

- 折叠态直接双击最新进度即可修正，不必先展开；
- 编辑过程不再有模态对话框（旧实现进入嵌套事件循环，还需防御期间卡片被销毁）；
- 已完成卡片：仍可双击修正历史进度（只禁添加入口，语义不变）。

### 测试

- 新增 `tests/test_progress_edit.py` 12 项：折叠/展开双击进入编辑、行内替换
  不新增行、预填原文、Enter 提交发射 `(entry_id, new_text)`、Esc 取消不发射、
  空文本/未变更不提交、`set_entries` 重建取消编辑、展开模式双击首行/中间行
  定位正确、编辑与添加互斥、TodoCard 信号接线（item_id 包装）、已完成卡片
  可编辑、编辑期间 hover 不揭示"＋"。双击用真实 `QMouseEvent`
  （`MouseButtonDblClick`）走 `mouseDoubleClickEvent` 路径，无弃用警告。
- 全量回归 228 项通过（约 13 分钟，offscreen）；`ruff check app tests` 通过。

### 备注

- 教训：沙箱内勿用 PowerShell 管道改写 UTF-8 源文件（按 GBK 解码回写会损坏
  中文注释），一律用 write/edit 工具。
