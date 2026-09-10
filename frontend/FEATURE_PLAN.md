# 前端功能规划：对齐 PowerPoint 全功能栈

> **目标**：在现有「SVG 画布 + PPT-IR 单一真理源 + LangGraph 子代理闭环」架构上，把 PowerPoint 桌面端的主流创作能力逐项补全到 Web 前端。
>
> **原则**：
> 1. 所有图元写操作仍统一走 `backend/agent/tools.py:execute()`，保证 Undo/Redo 快照完整。
> 2. 后端已有但前端未暴露的能力优先补齐（避免重复造轮子）。
> 3. 1280×720 基准画布、`0<=radius<=3px` 圆角、中文精炼文案等全局规范不破坏。
> 4. 交互保持「画布就地编辑 + 右侧图元属性检查器 + AI 协同」三段式，不另起灶。

---

## 0. 现状盘点

### 已实现（前端已有）
| 模块 | 覆盖能力 |
| :--- | :--- |
| 顶部 Header | 撤销/重做、新建页、导入 PPTX、导出 PPTX、AI 论文导入、模型配置 |
| 左侧 Sidebar | 缩略图大纲、增删页、页面切换 |
| 主画布 SlideCanvas | 缩放、网格、吸附、智能辅助线、拖拽/缩放/就地文本编辑 |
| CanvasToolbar | 文本、卡片、矩形/椭圆/三角形/菱形、连接线、智能对齐 |
| 右侧 ChatPanel | AI 协同对话、图元属性检查器、视觉评分报告 |
| PropertyPanel | 尺寸坐标、对齐、字体/字号/加粗/斜体/对齐/颜色、圆角、透明度、边框 |

### 后端已有但**未暴露**到前端的能力（高价值快速补齐点）
- `group_elements` / `ungroup_elements`（组合/取消组合）
- `align_elements`（左/右/上/下/中/垂直/水平分布对齐）
- `duplicate_slide`（复制页面）
- `clear_slide_elements`（清空页面）
- `format_text`（富文本格式化）
- `generate_slide_layout`（card_grid / timeline / kpi_metrics / comparison / title_slide 排版原型）
- `batch_add_cards`（批量卡片）
- `evaluate_layout` / `auto_fix_layout`（视觉健康评分与自愈）
- `TableElementIR`、`ImageElementIR` 的渲染与 OOXML 转换已存在，但**无新增表格/图片工具与 UI**

---

## 1. 功能分级（P0 / P1 / P2）

### P0 — 后端已支持，前端尽快接入（价值最高、成本最低）
1. **组合 / 取消组合**：多选图元（Shift+点击 或 框选）→ 组合为组；右键或属性面板「解散组合」。需前端新增多选状态与选区框。
2. **对齐 / 分布工具栏**：对齐到左/水平居中/右/顶/垂直居中/底 + 水平分布 + 垂直分布，复用 `align_elements`。
3. **复制幻灯片**：侧栏缩略图右键菜单或顶栏按钮，复用 `duplicate_slide`。
4. **清空页面**：清空当前页元素（保留标题），复用 `clear_slide_elements`。
5. **排版原型一键生成**：在空页/新页上通过侧栏「+」或快捷入口生成 `title_slide / card_grid / timeline / kpi_metrics / comparison` 五种原型，复用 `generate_slide_layout`。
6. **视觉健康评分面板**：当前页实时 `evaluate_layout` 分数 + 「一键自愈」`auto_fix_layout` 按钮（把目前藏在 ChatPanel 遥测里的能力独立成可手动触发工具）。

### P1 — 补全 PowerPoint 常见元素与媒体
7. **图片插入**：上传本地图片 / 从 PPTX 资源库选择；缩放、裁剪（clipPath 圆角）、替换、Alt 文本。需要后端新增 `add_image` 工具（渲染与导出已有）。
8. **表格**：插入 N×M 表格、编辑单元格文本、合并/拆分单元格、行列增删、表头样式。需要后端新增 `add_table` / `update_table` 工具（TableElementIR 与 OOXML 导出已就绪）。
9. **形状库扩充**：右箭头、六边形、五角星、流程图（流程/判定/文档）、圆角箭头、缺角矩形等常见 `presetGeometry`。
10. **SmartArt / 结构原型**：把 timeline、KPI、对比等原型做成「一键插入到当前页」而不是仅靠 AI 对话触发。

### P2 — 高级编排与体验
11. **幻灯片母版 / 版式**：编辑全局 theme/master token，应用统一页脚、页码、LOGO 占位。
12. **备注 / 演讲者视图**：`slide.notes` 编辑 + 演讲者备注模式。
13. **动画 / 过渡**：PowerPoint 核心但 IR 未建模。先落「切换过渡」预设（淡入/推入/切割），动画后续扩展。
14. **多选框选 + 批量操作**：选区、批量移动/缩放/对齐/删除。
15. **图层管理（排列顺序）**：置于顶层/底层/上移/下移一层，基于 `z_index` 重新排序。
16. **复制 / 粘贴 / 样式刷**：图元级复制粘贴、格式刷（复制填充/字体/边框）。
17. **标尺与参考线**：垂直/水平参考线、对象吸附到参考线（现已有吸附引擎，可加自定义参考线源）。
18. **导出增强**：PDF / PNG 快照导出、16:9 与 4:3 尺寸切换。
19. **撤销面板 / 历史时间线**：把 `history` patch 记录可视化为可回溯时间线。
20. **快捷键体系**：Ctrl+D 复制、Ctrl+G 组合、Ctrl+Shift+G 取消组合、方向键微调、Del 删除、Ctrl+A 全选。

---

## 2. 推荐实现顺序（里程碑）

| 里程碑 | 内容 | 关键改动 |
| :--- | :--- | :--- |
| **M1 对齐与组织** | 多选框选、组合/取消组合、对齐/分布、复制页、清空页 | store 多选状态、CanvasToolbar 扩展、侧栏右键 |
| **M2 排版原型库** | 5 种原型一键生成、批量卡片、视觉健康面板、一键自愈 | 新增原型面板组件、复用后端 layout 工具 |
| **M3 媒体与表格** | 图片上传/裁剪、表格插入与单元格编辑 | 后端 `add_image`/`add_table` 工具 + 前端面板 |
| **M4 图层与剪贴板** | 图层顺序、复制粘贴、格式刷、快捷键 | 属性面板新增图层区、全局快捷键表 |
| **M5 体验增强** | 母版/备注/过渡、标尺参考线、导出增强、历史时间线 | 新增 Master/Notes 编辑面板、导出选项 |

---

## 3. 各功能实现要点（供落地时参考）

### 3.1 多选与组合（M1）
- `usePPTStore` 增加 `selectedElementIds: string[]`，与现有单选 `selectedElementId` 并存。
- `SlideCanvas` 支持框选（拖空白出虚线选区）与 Shift 累选。
- 多选时 `PropertyPanel` 顶部显示「N 个图元」，提供：组合、对齐、分布、批量删除。
- 组合调用 `executeDirectAction('group_elements', { element_ids, group_name })`，需在 `websocket.py` 的 `direct_action` 分支补充 `group_elements` / `ungroup_elements` / `align_elements` 转发。

### 3.2 排版原型库（M2）
- 新增右侧 `LayoutPrototypePanel`：五个原型按钮 + 参数（标题/副标题/条数）。
- 调用 `executeDirectAction('generate_slide_layout', { layout_type, title, ... })`，websocket 需转发 `generate_slide_layout`、`batch_add_cards`。
- 视觉健康面板：读 `preview_update` 的 `quality_score`，展示五维雷达/条形图 + 「一键自愈」按钮调用 `auto_fix_layout`。

### 3.3 图片与表格（M3）
- **图片**：后端新增 `add_image(pres, history, slide_id, src/asset_id, x, y, w, h, radius)` 工具；前端上传走 `POST /api/asset` 存储，渲染/导出走已有 `ImageElementIR` 路径。
- **表格**：后端新增 `add_table(pres, history, rows, cols, data[][], ...)` 与 `update_table_cell`；前端 `TableEditorPanel` 编辑 `TableElementIR.cells`，渲染复用 `SVGRendererComponent` 的 table 分支。

### 3.4 图层顺序（M4）
- `z_index` 语义化：前端按 `z_index` 排序渲染，提供上移/下移/置顶/置底按钮。
- 需要后端 `reorder_element` 工具（或复用 `update_element` 改 `z_index`）并记录 patch。

### 3.5 母版 / 备注 / 过渡（M5）
- 母版：编辑 `pres.master` 与 theme token，提供页脚/页码/LOGO 统一开关。
- 备注：`slide.notes` 文本域编辑。
- 过渡：在 `SlideIR` 增加 `transition` 元数据（新建字段），导出映射到 OOXML `<p:transition>`。

---

## 4. 需新增 / 修改的后端触点（前端依赖清单）

| 后端触点 | 用途 | 状态 |
| :--- | :--- | :--- |
| `websocket.py` direct_action 分支 | 转发 `group/ungroup/align/generate_slide_layout/batch_add_cards/clear_slide_elements/auto_fix_layout` | 需扩展 |
| `tools.py` `add_image` | 图片插入 | 需新增 |
| `tools.py` `add_table` / `update_table` | 表格插入与编辑 | 需新增 |
| `tools.py` `reorder_element` | 图层顺序 | 需新增 |
| `POST /api/asset` | 图片素材上传 | 需新增 |
| OOXML 导出 | 表格/图片/过渡映射 | 表格图片已具备，过渡待扩展 |

> 前端 IR 类型 `ppt.ts` 已包含 `TableElementIR`、`ImageElementIR`、`ConnectorElementIR`、`GroupElementIR`，无需大改类型层。

---

## 5. 设计规范不变量（实现时须遵守）
- 画布物理基准 **1280 × 720**，坐标始终以该比例换算。
- 圆角 `0 <= radius <= 3px`（商业编辑感），图像/卡片统一用 `<clipPath>` 裁切。
- 中文为主，单条文案 ≤ 20~25 字。
- 主 Agent 是唯一对话端点，子代理仅通过遥测呈现，不新增聊天角色。
- 所有图元写操作必须经过 `tools.execute()`，保证 undo/redo 完整。