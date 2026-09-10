# frontend/MEMORY_MAP.md: 前端专属架构与上下文记忆地图

> **适用范围**：本文件为涉及 `frontend/` 相关 UI 组件、SVG 画布渲染、吸附对齐引擎、状态管理与交互开发时的专项记忆地图。
> **跨端全局契约**：参见根目录 [`../MEMORY_MAP.md`](../MEMORY_MAP.md)。

---

## 1. 技术栈与环境规范

- **核心技术栈**：React 19.2 + TypeScript 6.0 + Vite 8.2 + Tailwind CSS v4.3 + Zustand 5.0。
- **图标体系**：Lucide React。
- **Linter & Test**：Oxlint (`npm run lint`) + Vitest (`npm run test`)。
- **画布物理比例**：基准画布尺寸严格为 **1280 × 720** (16:9 比例)。

---

## 2. 目录结构与核心组件分布

```
frontend/src/
├── types/
│   └── ppt.ts                   # 核心 TypeScript 类型定义 (PresentationIR, ElementIR, ContextUsageData 等)
├── store/
│   └── usePPTStore.ts           # Zustand 全局响应式状态树与 WebSocket 通信管道
├── components/
│   ├── ChatPanel.tsx            # 主 Agent 协同工作台 (用户对话唯一入口)
│   ├── ContextUsageIndicator.tsx # 环形圆形进度规 (Token 容量与 90% 自动压缩预警)
│   ├── SlideCanvas.tsx          # 1280x720 主画布容器与图元交互事件处理
│   ├── SVGRendererComponent.tsx # 矢量图元 SVG 实时渲染器 (矩形、文字、线条、图片等)
│   ├── AlignmentGuides.tsx      # 动态几何对齐线与智能吸附吸附线渲染
│   ├── CanvasToolbar.tsx        # 缩放、撤销/重做、图元快捷工具栏
│   ├── PropertyPanel.tsx        # 选中文本/形状图元的高级属性检查器
│   ├── Header.tsx               # 顶部导航、演示文稿标题与操作按钮
│   ├── Sidebar.tsx              # 左侧幻灯片缩略图大纲列表
│   └── SettingsModal.tsx        # 大模型端点与上下文容量 (128k/256k/512k/1m) 配置
├── editor/snapping/             # 几何吸附与对齐算法引擎
│   ├── snapEngine.ts            # 吸附核心算法与阈值判定 (5px 吸附距离)
│   ├── candidates.ts            # 画布边界与邻近图元特征线提取
│   ├── geometry.ts              # 点/线段几何相交与距离计算
│   └── guideStyle.ts            # 辅助线渲染样式
├── theme/
│   └── tokens.ts                # 色彩阶梯与设计 Token 定义
├── App.tsx                      # 根应用布局容器
└── index.css                    # Tailwind CSS v4 样式与主题变量
```

---

## 3. 全双工状态流 (`store/usePPTStore.ts`)

### 3.1 核心状态树 (State)
- `presentation: PresentationIR | null`：当前演示文稿完整 IR。
- `activeSlideId: string | null`：当前聚焦的页面 ID。
- `selectedElementId: string | null`：当前选中的图元 ID。
- `messages: ChatMessage[]`：会话历史（仅展示用户与主 Agent 的对话）。
- `contextUsage: ContextUsageData | null`：后端推送的上下文 Token 统计与压缩状态。
- `visualRemediation: VisualRemediationEvent | null`：排版自愈卡片事件。
- `isAgentThinking: boolean` & `thinkingStatus: string`：思考与子代理运行状态。

### 3.2 WebSocket 协议管道
前端挂载 `/ws/{sessionId}`，核心监听事件：
- `presentation_update`：同步 PPT-IR 全量更新并重绘。
- `context_usage`：同步上下文容量、百分比与压缩状态。
- `subagent_lifecycle` / `content_critique`：子代理审查过程遥测，更新状态文本，**不插入聊天泡泡**。
- `visual_remediation`：推送视觉评估缺陷与自愈修复报告。

---

## 4. UI 交互不变量与设计准则

1. **主 Agent 对话唯一性**：
   - 聊天面板（`ChatPanel.tsx`）仅展示用户与主 Agent 的交互。
   - 子代理（Plan Critic、Content Critic、Visual Critic）仅通过顶部状态指示器和遥测卡片展示，不得作为独立聊天角色插话。
2. **上下文容量指示规 (`ContextUsageIndicator.tsx`)**：
   - 采用 SVG 环形圆弧进度条：
     - `< 75%`：青绿色（健康）
     - `75% ~ 89%`：琥珀黄色（预警）
     - `≥ 90%`：玫红色（闪烁指示“已压缩”）
3. **画布矢量渲染、吸附与就地编辑**：
   - 画布坐标系保持 1280x720，通过容器的 `scale` 变换适配各种屏幕尺寸。
   - 拖拽与缩放图元时调用 `snapEngine` 提供实时对齐线与中线吸附。
   - 双击文本/卡片进入 `<foreignObject>` 毫秒级就地编辑模式，失焦或 `Cmd/Ctrl+Enter` 自动提交。
   - 选中文本/形状/图像图元时，在画布底部实时唤出浮动格式控制栏（编辑文字、字号微调、加粗、文字色盘、0~16px 圆角快捷药丸）。
4. **卡片圆角严控与图像裁剪**：
   - 前端生成的背景卡片圆角必须在 `0 <= radius <= 3px`，严禁药丸形大圆角。
   - 图像与卡片通过 SVG `<clipPath>` 统一裁切圆角，支持通过滑块自由微调。

---

## 5. 前端开发与构建指令

```powershell
# 依赖安装
npm install

# 启动本地开发服务 (http://localhost:5173)
npm run dev

# 静态类型检查与 Vite 生产打包 (修改前端代码后必须运行验证)
npm run build

# 快速代码检查
npm run lint

# 单元测试 (Vitest)
npm run test
```
