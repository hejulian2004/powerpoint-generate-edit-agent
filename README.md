# pptx_agent_converter

> 面向 PPT Agent 的高性能、高保真 PPTX OOXML 工程化解析与重建工具链。

## 📖 项目简介

传统的 `python-pptx` 高层封装方案在重绘或修改 PPT 时会丢失大量视觉效果与元数据，例如：
- 主题（Theme：fontScheme, clrScheme）与母版（Slide Master / Layout）继承
- 渐变填充（Gradient Fill：多色标、角度、线性/路径）与透明度（Alpha）
- 阴影（Outer Shadow：模糊半径、距离、方向、透明度）与形状特效
- 连线与接头（Connector）的精确起点/终点与箭头方向（防止反向）
- 自定义圆角矩形曲率（Radius / adjustment values）
- 细粒度的段落和 Run 级别字体样式与对齐方式

`pptx_agent_converter` 采用**底层 OOXML 直解与重构架构**，直接解析 `.pptx` (ZIP) 内部的 `ppt/slides/*.xml`、`ppt/theme/*.xml`、`ppt/slideMasters/*.xml`、`ppt/slideLayouts/*.xml` 和 `ppt/media/*`，将复杂的 PresentationML 和 DrawingML 转化为严谨、可被 AI 轻松理解与编辑的结构化 JSON 和 Python DSL，并支持无损或高保真重新组装打包为原生 PPTX 文件。

---

## 🚀 核心特性

1. **直接 OOXML 解构**：完全不依赖 `python-pptx` 作为主解析器，基于 `lxml` 与 `xml.etree.ElementTree` 精确解析 DrawingML 命名空间。
2. **结构化 JSON 规范**：每页 Slide 导出独立规范的 JSON，专为 LLM / PPT Agent 读取与局部重写优化。
3. **富有表现力的 Python DSL**：摆脱臃肿的底层 API 调用，提供 `add_shape`、`add_connector`、`add_textbox` 等声明式 DSL，支持 `build.py` 自动化一键生成。
4. **箭头方向与连线保真**：通过精确解析 `xfrm`（`off`, `ext`, `flipH`, `flipV`）和 `tailEnd`/`headEnd`，确保从 A 到 B 的连接线和箭头绝不反向。
5. **完整保留原 PPT 设计资产**：自动解包并管理媒体文件（图片），重新构建时完整映射 Relationship 引用。
6. **全套 CLI 工具链**：支持完整转译、全量重建、单页导出、单页重建。

---

## 📂 项目结构

```
pptx_agent_converter/
│
├── cli.py                  # CLI 命令行入口
├── extractor/              # OOXML 深度解析器
│   ├── pptx_parser.py      # PPTX ZIP/OPC 容器总解析器
│   ├── slide_parser.py     # 单页 Slide 与形状树解析
│   ├── shape_parser.py     # 几何图形、坐标转换、连线方向计算
│   ├── text_parser.py      # 段落、Run、字体、对齐解析
│   ├── style_parser.py     # 颜色、渐变填充、边框、阴影、主题解析
│   ├── media_parser.py     # 图片与关系(rels)管理
│   └── constants.py        # 命名空间、EMU单位换算、几何预设映射
│
├── model/                  # 强类型 Dataclass 数据模型
│   ├── slide.py            # Slide, Presentation, ThemeInfo, SlideSize
│   ├── shape.py            # ShapeElement, ConnectorElement, ImageElement
│   ├── text.py             # TextBlock, Paragraph, Run
│   └── style.py            # Fill, Line, Shadow, Font, ParagraphStyle, Color
│
├── exporter/               # 数据导出器
│   ├── json_exporter.py    # 输出 presentation.json, slides/*.json, assets/*
│   └── python_exporter.py  # 输出 slide_*.py, build.py
│
├── renderer/               # OOXML 重建与渲染器
│   ├── pptx_builder.py     # OPC ZIP 打包、母版布局合成、全局 Rel 组装
│   ├── shape_renderer.py   # 生成 p:sp, p:cxnSp, p:pic, p:grpSp 节点
│   └── style_renderer.py   # 生成 DrawingML 填充、线条、阴影、文本样式
│
├── dsl/                    # Python DSL 运行时
│   └── api.py              # Shape, Connector, TextBox, Image, add_* API
│
├── output/                 # 转换生成的工程目录
│
└── tests/                  # 自动化测试用例套件
    ├── test_text.py        # 文本与字体测试
    ├── test_shape.py       # 形状、填充、圆角、阴影测试
    ├── test_connector.py   # 连线端点与箭头方向测试
    └── test_roundtrip.py   # 完整 PPTX -> JSON -> PPTX 端到端回环测试
```

---

## 🛠️ 安装与环境

要求 **Python 3.11+**。

建议使用虚拟环境：

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
pip install -e .
```

---

## 💻 命令行使用说明

### 1. 转换 PPTX 为 JSON / Python DSL
```bash
python cli.py convert input.pptx
```
输出目录结构：
```
output/
└── input_name/
    ├── presentation.json       # 演示文稿全局元数据与主题定义
    ├── slides/
    │   ├── slide_01.json       # 各单页结构化 JSON
    │   ├── slide_02.json
    │   └── ...
    ├── assets/
    │   ├── image1.png          # 原始图片素材
    │   └── ...
    └── python/
        ├── slide_01.py         # 各单页声明式 Python DSL
        ├── slide_02.py
        └── build.py            # DSL 独立重建脚本
```

### 2. 重建 PPTX
从生成的工程目录中重新打包生成 PPTX：
```bash
python cli.py build output/input_name --output output/input_name/rebuild.pptx
```

### 3. 单页导出
单独导出 PPTX 中的某一页为独立 JSON：
```bash
python cli.py export-slide input.pptx --slide 1 --output single_slide_export/
```

### 4. 单页重建
将单独修改后的 `slide_01.json` 重建为独立 PPTX：
```bash
python cli.py build-slide single_slide_export/slide_01.json --output single_slide.pptx
```

---

## 🎨 Python DSL 示例

转换后生成的 `slide_01.py` 如下所示，清晰直观，易于让 LLM Agent 针对特定元素进行增删改查：

```python
# -*- coding: utf-8 -*-
from pptx_agent_converter.dsl import (
    Shape,
    Connector,
    TextBox,
    Image,
    add_shape,
    add_connector
)

def build(slide):
    # 添加带阴影与圆角的圆角矩形
    add_shape(
        slide,
        Shape(
            type="roundRect",
            x=1.2,
            y=2.5,
            width=2.5,
            height=1.0,
            radius=0.1667,
            style={
                "fill": "#3366FF",
                "border": "#FFFFFF",
                "border_width": 1.5,
                "shadow": True
            },
            text="Image Generation",
            font={"name": "Aptos", "size": 18.0, "color": "#FFFFFF"},
            paragraph={"align": "center", "vertical": "middle"}
        )
    )

    # 添加带三角箭头的连线（箭头方向严格保持）
    add_connector(
        slide,
        start=(3.7, 3.0),
        end=(5.5, 3.0),
        arrow="triangle",
        line={"color": "#3366FF", "width": 2.0}
    )
```

直接运行 `python output/input_name/python/build.py` 亦可无缝完成 DSL 到 PPTX 的编译。

---

## 🧪 运行测试套件

执行全部自动化测试：

```bash
pytest -v
```

测试覆盖内容：
- `test_text.py`: 字体名称、字号、颜色、粗体、斜体、对齐方式、多段落与多 Run 解析与还原。
- `test_shape.py`: 矩形、圆角矩形、椭圆、菱形、箭头等形状类型，纯色填充、渐变填充、透明度、边框虚线、圆角半径、阴影效果。
- `test_connector.py`: 连线起点与终点计算、横向/纵向/对角连线、箭头方向不反向验证。
- `test_roundtrip.py`: PPTX → JSON → PPTX 完整端到端回环测试，对比页面数量、形状类型、文本内容与坐标，以及 CLI 命令和图片资源保真度。
