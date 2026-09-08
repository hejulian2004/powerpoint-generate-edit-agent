# PPT-Agent-Studio

## AI Agent 驱动的 PPT 生成与编辑平台技术架构

版本：v1.0

---

## 1. 项目定位

PPT-Agent-Studio 是一个基于 LLM Agent 的智能 PPT 创建与编辑系统。

目标：

- PPTX 导入
- PPT 结构解析
- SVG/HTML 实时渲染
- Web 在线编辑
- AI Agent 自动修改
- PPTX 导出

核心思想：

> PPTX 不是核心数据格式，PPT-IR（Presentation Intermediate Representation）才是系统核心。

---

## 2. 总体架构

```
用户
 |
聊天界面
 |
PPT Agent
 |
LLM Provider
(OpenAI Compatible API)
 |
PPT Tools
 |
PPT-IR
 |
+----------------+
|                |
SVG Renderer   PPTX Renderer
|                |
实时预览        导出PPTX
```

---

## 3. 核心设计原则

系统不让 Agent 直接修改 PPTX。

采用：

```
PPTX
 |
Parser
 |
PPT-IR
 |
Renderer
 |
PPTX
```

PPT-IR 负责：

- Agent 操作对象
- 编辑器状态
- 渲染输入
- 历史版本管理

---

## 4. LLM 接入

支持 OpenAI Compatible API。

兼容：

- OpenAI
- Azure OpenAI
- OneAPI
- LiteLLM
- 自建模型服务

配置：

```json
{
  "base_url":"https://api.xxx/v1",
  "api_key":"xxx",
  "model":"xxx"
}
```

支持：

- Reasoning Model：PPT规划
- Vision Model：查看截图
- Fast Model：简单修改

---

## 5. Vision Loop

Agent 可以查看当前 PPT 状态。

流程：

```
PPT-IR
 |
SVG Render
 |
Screenshot
 |
Vision LLM
 |
分析问题
 |
Tool Call修改
 |
重新截图验证
```

推荐：

- Playwright
- Chromium

---

## 6. Agent 工作循环

```
Observe
 |
Think
 |
Plan
 |
Tool Call
 |
Render
 |
Observe Again
```

---

## 7. PPT Tool API

Agent 通过工具操作 PPT。

主要工具：

- create_presentation
- create_slide
- add_text
- add_shape
- update_element
- optimize_layout
- render_slide
- export_pptx

---

## 8. PPT-IR 数据模型

Slide：

```json
{
"id":"slide_01",
"width":1280,
"height":720,
"elements":[]
}
```

Element：

```json
{
"id":"element_01",
"type":"shape",
"x":100,
"y":200,
"width":300,
"height":100,
"style":{},
"content":{}
}
```

支持：

- Text
- Shape
- Image
- Table
- Chart
- Connector
- Group

---

## 9. 实时预览

架构：

```
Agent修改

↓

PPT-IR Update

↓

WebSocket

↓

Frontend State

↓

SVG刷新
```

目标：

页面修改延迟 < 500ms。

---

## 10. 前端架构

技术：

- React
- TypeScript
- SVG
- Zustand
- WebSocket

界面：

```
+----------------+
| PPT Preview    |
+----------------+

+----------------+
| Chat           |
+----------------+
```

---

## 11. Agent Memory

保存：

- 用户风格偏好
- 历史修改
- 设计规则

例如：

```
academic style
dark theme
less text
more diagrams
```

---

## 12. Version Control

每次修改生成 Patch。

支持：

- Undo
- Redo
- Compare
- Rollback

---

## 13. PPTX 导出

MVP：

```
PPT-IR
 |
python-pptx
 |
PPTX
```

高级版本：

```
PPT-IR
 |
OOXML Writer
 |
PPTX
```

---

## 14. 开发阶段

### Phase 0
项目初始化：

- Backend
- Frontend
- LLM Provider

### Phase 1
PPT Runtime：

- PPT-IR
- SVG Renderer
- Screenshot

### Phase 2
Agent：

- Tool Calling
- 修改工具

### Phase 3
实时编辑：

- WebSocket
- Preview

### Phase 4
PPTX Import：

- OOXML Parser

### Phase 5
PPTX Export：

- PPTX Renderer

---

## 15. 验收标准

系统能够：

1. 上传 PPTX
2. Agent 阅读页面截图
3. 用户聊天修改 PPT
4. Agent 调用工具
5. 浏览器实时显示变化
6. 导出新的 PPTX

---

## 16. Gemini/Codex 实现要求

实现一个 AI PPT Agent 平台。

要求：

1. 使用 PPT-IR 作为核心状态。
2. 支持 OpenAI Compatible API。
3. 支持 Vision LLM 输入 PPT 截图。
4. 支持 Agent Tool Calling。
5. 支持实时 SVG Preview。
6. 支持 PPTX 导入和导出。

不要实现简单 PPT 生成器。

目标：

一个可以通过聊天控制 PPT 创建和修改的 Agent Runtime。

开发顺序：

Phase 0:
项目初始化。

Phase 1:
PPT-IR + Renderer。

Phase 2:
LLM Provider。

Phase 3:
Agent Tools。

Phase 4:
Realtime Preview。

Phase 5:
PPT Import/Export。

每阶段：

- 编写测试
- 验证功能
- 保持架构稳定
