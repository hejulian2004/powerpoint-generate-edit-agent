# -*- coding: utf-8 -*-
# Slide 13 Definition DSL
from pptx_agent_converter.dsl import (
    Shape,
    Connector,
    TextBox,
    Image,
    add_shape,
    add_connector,
    add_textbox,
    add_image
)

def build(slide):
    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.75,
            y=0.34,
            width=3.5,
            height=0.24,
            text='DISCUSSION',
            font={'name': 'Calibri', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#000000'},
            paragraph={'align': 'left', 'vertical': 'top'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.75,
            y=0.63,
            width=11.5,
            height=0.52,
            text='局限性与我的研究启发',
            font={'name': 'Calibri', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#000000'},
            paragraph={'align': 'left', 'vertical': 'top'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.75,
            y=1.26,
            width=11.82,
            height=0.012,
            style={'fill': '#E0E2E6'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=12.0,
            y=0.36,
            width=0.55,
            height=0.28,
            text='14',
            font={'name': 'Calibri', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#000000'},
            paragraph={'align': 'right', 'vertical': 'top'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.95,
            y=1.55,
            width=4.7,
            height=0.4,
            text='Limitations',
            font={'name': 'Calibri', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#000000'},
            paragraph={'align': 'left', 'vertical': 'top'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=0.9,
            y=2.1,
            width=5.35,
            height=1.05,
            style={'fill': '#FAEBEB', 'border': '#E0E2E6'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.9,
            y=2.1,
            width=0.06,
            height=1.05,
            style={'fill': '#B73B3B'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=1.12,
            y=2.28,
            width=4.95,
            height=0.36,
            text='Zero-shot 边界',
            font={'name': 'Calibri', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#000000'},
            paragraph={'align': 'left', 'vertical': 'top'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=1.12,
            y=2.72,
            width=4.95,
            height=0.27,
            text='训练轨迹仍来自 VisA 的真实异常。',
            font={'name': 'Calibri', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#000000'},
            paragraph={'align': 'left', 'vertical': 'top'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=0.9,
            y=3.45,
            width=5.35,
            height=1.05,
            style={'fill': '#FAEBEB', 'border': '#E0E2E6'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.9,
            y=3.45,
            width=0.06,
            height=1.05,
            style={'fill': '#B73B3B'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=1.12,
            y=3.63,
            width=4.95,
            height=0.36,
            text='闭源依赖',
            font={'name': 'Calibri', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#000000'},
            paragraph={'align': 'left', 'vertical': 'top'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=1.12,
            y=4.07,
            width=4.95,
            height=0.27,
            text='Gemini + Search 影响复现与隐私。',
            font={'name': 'Calibri', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#000000'},
            paragraph={'align': 'left', 'vertical': 'top'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=0.9,
            y=4.8,
            width=5.35,
            height=1.05,
            style={'fill': '#FAEBEB', 'border': '#E0E2E6'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.9,
            y=4.8,
            width=0.06,
            height=1.05,
            style={'fill': '#B73B3B'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=1.12,
            y=4.98,
            width=4.95,
            height=0.36,
            text='Reward 主观性',
            font={'name': 'Calibri', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#000000'},
            paragraph={'align': 'left', 'vertical': 'top'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=1.12,
            y=5.42,
            width=4.95,
            height=0.27,
            text='视觉质量核心仍依赖 LLM-as-a-Judge。',
            font={'name': 'Calibri', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#000000'},
            paragraph={'align': 'left', 'vertical': 'top'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=7.0,
            y=1.55,
            width=4.8,
            height=0.4,
            text='Possible directions',
            font={'name': 'Calibri', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#000000'},
            paragraph={'align': 'left', 'vertical': 'top'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=6.95,
            y=2.1,
            width=5.45,
            height=1.05,
            style={'fill': '#E8EEFC', 'border': '#E0E2E6'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=6.95,
            y=2.1,
            width=0.06,
            height=1.05,
            style={'fill': '#2454B4'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=7.17,
            y=2.28,
            width=5.05,
            height=0.36,
            text='Cost-aware routing',
            font={'name': 'Calibri', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#000000'},
            paragraph={'align': 'left', 'vertical': 'top'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=7.17,
            y=2.72,
            width=5.05,
            height=0.27,
            text='根据难度动态跳过高成本工具。',
            font={'name': 'Calibri', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#000000'},
            paragraph={'align': 'left', 'vertical': 'top'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=6.95,
            y=3.45,
            width=5.45,
            height=1.05,
            style={'fill': '#E8EEFC', 'border': '#E0E2E6'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=6.95,
            y=3.45,
            width=0.06,
            height=1.05,
            style={'fill': '#2454B4'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=7.17,
            y=3.63,
            width=5.05,
            height=0.36,
            text='Uncertainty-driven KR',
            font={'name': 'Calibri', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#000000'},
            paragraph={'align': 'left', 'vertical': 'top'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=7.17,
            y=4.07,
            width=5.05,
            height=0.27,
            text='只在“真的不确定”时检索知识。',
            font={'name': 'Calibri', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#000000'},
            paragraph={'align': 'left', 'vertical': 'top'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=6.95,
            y=4.8,
            width=5.45,
            height=1.05,
            style={'fill': '#E8EEFC', 'border': '#E0E2E6'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=6.95,
            y=4.8,
            width=0.06,
            height=1.05,
            style={'fill': '#2454B4'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=7.17,
            y=4.98,
            width=5.05,
            height=0.36,
            text='Verifiable reward',
            font={'name': 'Calibri', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#000000'},
            paragraph={'align': 'left', 'vertical': 'top'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=7.17,
            y=5.42,
            width=5.05,
            height=0.27,
            text='引入几何、物理或多 Critic 约束。',
            font={'name': 'Calibri', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#000000'},
            paragraph={'align': 'left', 'vertical': 'top'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=1.15,
            y=6.25,
            width=11.0,
            height=0.72,
            style={'fill': '#141416', 'border': '#141416'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=1.35,
            y=6.43,
            width=10.6,
            height=0.32,
            text='Takeaway: 生成模型只是“执行器”；真正的增益来自 Evaluator–Reflection–Tool Loop。',
            font={'name': 'Calibri', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#000000'},
            paragraph={'align': 'center', 'vertical': 'top'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.75,
            y=7.13,
            width=11.8,
            height=0.18,
            text='Source: Su et al., arXiv:2604.07900 (2026)',
            font={'name': 'Calibri', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#000000'},
            paragraph={'align': 'left', 'vertical': 'top'},
        )
    )

