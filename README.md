# PPT-Agent-Studio

> AI Agent 驱动的智能 PPT 生成、可视化编辑与高保真 OOXML 重构平台。

---

## 📖 项目定位与核心思想

> 💡 **架构与记忆地图导航**：系统拓扑、多子代理闭环编排与核心约束详见 [`MEMORY_MAP.md`](./MEMORY_MAP.md)。

**PPT-Agent-Studio** 突破了传统单一提示词生成简单 PPT 的局限，构建了一套以 **PPT-IR (Presentation Intermediate Representation)** 为核心的 Agent Runtime 智能平台。

> **核心架构理念：PPTX 不是核心数据格式，PPT-IR 才是系统状态核心。**

```
用户 (Web UI / 聊天流)
        │
        ▼
   PPT Agent (Observe-Think-Plan-Execute-Review Loop)
        │
        ▼
    LLM Provider (OpenAI Compatible API / Multi-Model Roles)
        │
        ▼
    PPT Tools (create_slide, add_shape, update_element, etc.)
        │
        ▼
    PPT-IR (1280×720 标准矢量中间表示，毫秒级 Patch 差异版本控制)
        │
   ┌────┴────────────────────────┐
   ▼                             ▼
SVG 实时渲染器 (前端 WebSocket 推送)   原生 OOXML 编解码引擎 (pptx_agent_converter)
   │                             │
高保真交互画布 / Vision Loop 视觉自省       原生 OOXML 双向转换框架，支持核心元素高保真导入导出，复杂对象持续完善
```

---

## 🎯 当前能力支持矩阵 (Current Support Matrix)

### Supported (完全支持)
- **文本与段落排版** (Text, Paragraphs & Fonts)
- **基础几何形状与圆角卡片** (Basic Shapes, Rounded Cards, Diamonds, Triangles)
- **图片与媒体资产** (Images & Media Assets)
- **连接导线与箭头** (Connectors & Arrows)
- **PPT-IR 矢量交互与协同编辑** (PPT-IR Direct Editing & Canvas Controls)

### Partially Supported (部分支持 / 持续完善)
- **组合对象** (Groups & Flattening)
- **主题色与字体方案** (Themes & Scheme Mapping)
- **高级排版与特效** (Advanced Formatting, Shadows & Gradients)

### Not Guaranteed (暂不承诺 / 后续演进)
- **动态 SmartArt 图示** (SmartArt)
- **幻灯片过渡与对象动画** (Animations & Transitions)
- **复杂图表与数据透视** (Complex Charts)
- **OLE 嵌入式对象** (Embedded Objects)

---

## 🚀 核心特性

1. **PPT-IR 统一中间层**：
   - 采用标准 1280×720 ViewBox 像素坐标系，直观对应 Web 画布与 SVG 矢量渲染。
   - 具备严格精确的 96 DPI / EMU / Inch 双向换算，保证与微软 PowerPoint 原生坐标零失真互转。
2. **AI Agent 闭环运行时**：
   - 支持自然语言对话指令（如“帮我添加 3 个特性卡片并规整排版”、“换成深色科技主题”、“从左侧卡片连接到右侧”）。
   - 自动规划并调用专业 PPT 工具（`add_text`, `add_shape`, `add_connector`, `update_element`, `optimize_layout`, `apply_theme` 等）。
3. **Vision Loop 多模态视觉自省**：
   - 结合 Headless 浏览器截图与高质量 SVG 快照，将实时视觉呈现回传给 Vision LLM。
   - 自动检测文字重叠、布局拥挤或色彩冲突，实现自我反思与连续校正。
4. **全功能版本控制与 Undo/Redo**：
   - 每次 Agent 修改或用户直接编辑均生成严格可逆的 Patch 记录。
   - 支持全局随时撤销（Ctrl+Z）、重做（Ctrl+Y）与历史回溯。
5. **极速双向 WebSocket 协同**：
   - 画布实时更新延迟 < 500ms，毫秒级推送补丁。
6. **底层 OOXML 原生高保真重构 (`pptx_agent_converter`)**：
   - 直解与重构 DrawingML / PresentationML，完整保真渐变、阴影、圆角、连接箭头及媒体资产。

---

## 📂 项目结构

```
D:\PPT/
│
├── backend/                    # FastAPI 后端服务与 Agent 运行时
│   ├── main.py                 # FastAPI 入口与静态单页应用挂载
│   ├── config.py               # 环境变量与动态多模型配置
│   ├── ir/                     # PPT-IR 核心模块
│   │   ├── models.py           # PPT-IR 强类型 Pydantic 模型
│   │   ├── converter.py        # PPT-IR 与 OOXML 双向转换器
│   │   ├── patch.py            # Patch 记录与 Undo/Redo 历史引擎
│   │   └── svg_renderer.py     # 服务端独立 SVG 渲染器
│   ├── agent/                  # Agent 核心模块
│   │   ├── llm.py              # OpenAI Compatible API 客户端（流式+多角色路由）
│   │   ├── tools.py            # PPT Tool API 注册中心与执行处理器
│   │   ├── runtime.py          # Agent 执行循环 (Observe-Think-Plan-Execute-Review)
│   │   ├── vision.py           # Vision Loop 快照捕获与多模态质检
│   │   └── memory.py           # 用户偏好、设计规范与近期记忆
│   ├── state/                  # 运行时状态与连接管理
│   │   └── store.py            # Presentation 单例存储与 WebSocket 广播中心
│   └── api/                    # 接口层
│       ├── routes.py           # REST API (上传、导出、设置、撤销重做)
│       └── websocket.py        # WebSocket 实时交互信道
│
├── frontend/                   # 现代 React + Vite + TypeScript 前端 Studio
│   ├── src/
│   │   ├── components/
│   │   │   ├── Header.tsx      # 顶部操作栏（撤销、重做、导入、导出、设置、状态）
│   │   │   ├── Sidebar.tsx     # 左侧幻灯片缩略图大纲列表（实时微缩 SVG 预览）
│   │   │   ├── SlideCanvas.tsx # 中间高保真 16:9 画布容器与缩放控制器
│   │   │   ├── SVGRendererComponent.tsx # 矢量 SVG 交互渲染核心与元素选中框
│   │   │   ├── ChatPanel.tsx   # 右侧 Copilot 聊天面板（工具状态卡片、思考动画、快捷指令）
│   │   │   └── SettingsModal.tsx # LLM 配置与多模型路由弹窗
│   │   ├── store/              # Zustand 全局响应式状态管理
│   │   └── types/              # 完整的 PPT-IR TypeScript 类型声明
│   └── dist/                   # 生产环境静态打包产物
│
├── pptx_agent_converter/       # 底层高保真 OOXML 解析与重建引擎
│   ├── extractor/              # OOXML 深度解构 (pptx_parser, shape_parser 等)
│   ├── model/                  # OOXML 物理领域模型
│   └── renderer/               # OOXML 重建器 (pptx_builder, shape_renderer 等)
│
├── run_studio.py               # 一键启动完整 Studio 平台的启动脚本
├── cli.py                      # 独立 PPTX 转换器命令行工具
└── tests/                      # 自动化测试套件 (包含 34+ 项全链路单元与集成测试)
```

---

## 🛠️ 安装与快速启动

### 1. 环境准备

要求 **Python 3.11+** 与 **Node.js 18+**。

```bash
# 激活虚拟环境
.venv\Scripts\activate

# 安装后端依赖
pip install -r requirements.txt
pip install -e .

# 安装前端依赖并构建静态资源
cd frontend
npm install
npm run build
cd ..
```

### 2. 一键启动服务

直接运行根目录的一键启动脚本：

```bash
# 统一生产模式 (FastAPI 托管完整前后端与 WebSocket，自动唤起浏览器)
python main.py

# 或开启前端热重载开发模式 (FastAPI 8000 + Vite 5173 同步热重载)
python main.py --dev
```

终端将输出：
```text
================================================================
  🎨 PPT-Agent-Studio 协同制作平台 一键启动成功
================================================================
  👉 Web 访问入口: http://127.0.0.1:8000
  📖 API 接口文档: http://127.0.0.1:8000/docs
  ⚙️ 运行工作模式: 统一生产模式 (FastAPI 托管前后端与 WS)
  💡 按 Ctrl+C 可安全终止所有服务
================================================================
```

在浏览器中打开 `http://127.0.0.1:8000`（开发模式访问 `http://localhost:5173`），即可立即使用完整的 **PPT-Agent-Studio** 平台！

---

## 🧪 自动化测试验证

系统配备了全面的测试覆盖，包含 PPT-IR 校验、双向转换保真度、Agent 运行时、REST API 与 PPTX 原生回环：

```bash
pytest -v
```

执行结果：
```text
tests/test_agent_runtime.py::test_tool_create_and_delete_slide PASSED
tests/test_agent_runtime.py::test_tool_add_and_update_shape PASSED
tests/test_agent_runtime.py::test_agent_runtime_turn PASSED
tests/test_backend_api.py::test_api_get_presentation PASSED
tests/test_backend_api.py::test_api_slide_svg PASSED
tests/test_backend_api.py::test_api_settings_update PASSED
tests/test_backend_api.py::test_pptx_import_export_roundtrip PASSED
tests/test_backend_api.py::test_api_upload_and_export PASSED
tests/test_backend_api.py::test_frontend_spa_serving PASSED
tests/test_ppt_ir.py::test_ppt_ir_model_creation PASSED
tests/test_ppt_ir.py::test_svg_renderer PASSED
tests/test_ppt_ir.py::test_bidirectional_conversion PASSED
tests/test_ppt_ir.py::test_history_manager_undo_redo PASSED
tests/test_roundtrip.py::test_full_roundtrip_workflow PASSED
... (34 项测试全部通过)
```

---

## 💻 核心操作工作流

1. **导入 PPTX**：点击顶部导航栏的“导入 PPTX”，底层 OOXML 解析器将自动解构母版、形状、文字、图片及连线，并投射为标准 PPT-IR。
2. **AI 自然语言编辑**：在右侧 Copilot 面板输入你的意图，例如：
   - *“在当前页右下角添加一个指标卡片，标题为数据增长，数值 150%”*
   - *“将所有卡片规整排版为水平等宽网格”*
   - *“将整套 PPT 配色切换为深蓝科技风”*
3. **实时预览与撤销**：画布即时接收 WebSocket 补丁并平滑重绘，可随时通过撤销按钮或快捷键 `Ctrl+Z` 回滚至上一状态。
4. **高保真导出**：点击“导出 PPTX”，系统自动组装标准的 PresentationML 压缩包，可在 Microsoft PowerPoint、WPS 或 Keynote 中无损打开与二次编辑。
