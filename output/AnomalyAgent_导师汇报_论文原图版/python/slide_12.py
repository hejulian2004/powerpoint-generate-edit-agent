# -*- coding: utf-8 -*-
# Slide 12 Definition DSL
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
            x=0.72,
            y=0.42,
            width=10.5,
            height=0.55,
            text='Critical Discussion & My Takeaways',
            font={'name': 'Noto Sans CJK SC', 'size': 28.0, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.74,
            y=0.93,
            width=10.9,
            height=0.36,
            text='这篇工作最值得延伸的，不只是更强生成器，而是更可验证、更经济、更自治的闭环。',
            font={'name': 'Noto Sans CJK SC', 'size': 13.0, 'bold': False, 'italic': False, 'color': '#AAB4D3'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=0.82,
            y=1.63,
            width=0.54,
            height=0.34,
            radius=0.5294,
            style={'fill': '#2D7FF9', 'border': '#2D7FF9', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.82,
            y=1.63,
            width=0.54,
            height=0.34,
            text='01',
            font={'name': 'Noto Sans CJK SC', 'size': 9.5, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=1.6,
            y=1.61,
            width=3.28,
            height=0.36,
            text='Zero-shot definition',
            font={'name': 'Noto Sans CJK SC', 'size': 16.0, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=4.88,
            y=1.6,
            width=7.45,
            height=0.52,
            text='训练 trajectory 使用 VisA 真实异常，更准确地说是 cross-dataset / unseen-anomaly generalization。',
            font={'name': 'Noto Sans CJK SC', 'size': 12.2, 'bold': False, 'italic': False, 'color': '#C6CDE2'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=1.6,
            y=2.32,
            width=10.73,
            height=0.0,
            style={'border': '#303A5C', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=0.82,
            y=2.66,
            width=0.54,
            height=0.34,
            radius=0.5294,
            style={'fill': '#E85D75', 'border': '#E85D75', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.82,
            y=2.66,
            width=0.54,
            height=0.34,
            text='02',
            font={'name': 'Noto Sans CJK SC', 'size': 9.5, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=1.6,
            y=2.64,
            width=3.28,
            height=0.36,
            text='Proprietary tool dependency',
            font={'name': 'Noto Sans CJK SC', 'size': 16.0, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=4.88,
            y=2.63,
            width=7.45,
            height=0.52,
            text='Gemini + Google Search 带来可复现性、隐私与部署成本问题。',
            font={'name': 'Noto Sans CJK SC', 'size': 12.2, 'bold': False, 'italic': False, 'color': '#C6CDE2'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=1.6,
            y=3.35,
            width=10.73,
            height=0.0,
            style={'border': '#303A5C', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=0.82,
            y=3.69,
            width=0.54,
            height=0.34,
            radius=0.5294,
            style={'fill': '#F2B84B', 'border': '#F2B84B', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.82,
            y=3.69,
            width=0.54,
            height=0.34,
            text='03',
            font={'name': 'Noto Sans CJK SC', 'size': 9.5, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=1.6,
            y=3.67,
            width=3.28,
            height=0.36,
            text='“Verifiable” reward?',
            font={'name': 'Noto Sans CJK SC', 'size': 16.0, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=4.88,
            y=3.66,
            width=7.45,
            height=0.52,
            text='核心视觉质量仍依赖 LLM-as-a-Judge，主观性与偏差值得验证。',
            font={'name': 'Noto Sans CJK SC', 'size': 12.2, 'bold': False, 'italic': False, 'color': '#C6CDE2'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=1.6,
            y=4.38,
            width=10.73,
            height=0.0,
            style={'border': '#303A5C', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=0.82,
            y=4.72,
            width=0.54,
            height=0.34,
            radius=0.5294,
            style={'fill': '#29A36A', 'border': '#29A36A', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.82,
            y=4.72,
            width=0.54,
            height=0.34,
            text='04',
            font={'name': 'Noto Sans CJK SC', 'size': 9.5, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=1.6,
            y=4.7,
            width=3.28,
            height=0.36,
            text='Adaptive routing is constrained',
            font={'name': 'Noto Sans CJK SC', 'size': 16.0, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=4.88,
            y=4.69,
            width=7.45,
            height=0.52,
            text='PG-first / QE-after-IG / KR-after-low-score 等行为被 prompt + behavior reward 强塑形。',
            font={'name': 'Noto Sans CJK SC', 'size': 12.2, 'bold': False, 'italic': False, 'color': '#C6CDE2'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=1.6,
            y=5.41,
            width=10.73,
            height=0.0,
            style={'border': '#303A5C', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.84,
            y=5.92,
            width=2.3,
            height=0.34,
            text='Possible directions',
            font={'name': 'Noto Sans CJK SC', 'size': 14.0, 'bold': True, 'italic': False, 'color': '#AAB4D3'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=3.0,
            y=5.86,
            width=2.22,
            height=0.44,
            radius=0.4091,
            style={'fill': '#263450', 'border': '#263450', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=3.0,
            y=5.86,
            width=2.22,
            height=0.44,
            text='Cost-aware tool routing',
            font={'name': 'Noto Sans CJK SC', 'size': 10.2, 'bold': True, 'italic': False, 'color': '#DDE5FF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=5.36,
            y=5.86,
            width=2.16,
            height=0.44,
            radius=0.4091,
            style={'fill': '#263450', 'border': '#263450', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=5.36,
            y=5.86,
            width=2.16,
            height=0.44,
            text='Uncertainty-driven KR',
            font={'name': 'Noto Sans CJK SC', 'size': 10.2, 'bold': True, 'italic': False, 'color': '#DDE5FF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=7.66,
            y=5.86,
            width=2.74,
            height=0.44,
            radius=0.4091,
            style={'fill': '#263450', 'border': '#263450', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=7.66,
            y=5.86,
            width=2.74,
            height=0.44,
            text='Multi-critic / verifiable reward',
            font={'name': 'Noto Sans CJK SC', 'size': 10.2, 'bold': True, 'italic': False, 'color': '#DDE5FF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=10.54,
            y=5.86,
            width=1.82,
            height=0.44,
            radius=0.4091,
            style={'fill': '#263450', 'border': '#263450', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=10.54,
            y=5.86,
            width=1.82,
            height=0.44,
            text='Hard-negative synthesis',
            font={'name': 'Noto Sans CJK SC', 'size': 9.7, 'bold': True, 'italic': False, 'color': '#DDE5FF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=1.1,
            y=6.63,
            width=11.1,
            height=0.52,
            radius=0.1923,
            style={'fill': '#1B2440', 'border': '#DDE5FF'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=1.28,
            y=6.71,
            width=10.74,
            height=0.36,
            text='Key takeaway: AnomalyAgent turns anomaly generation from a one-shot process into an iterative optimization loop.',
            font={'name': 'Noto Sans CJK SC', 'size': 15.0, 'bold': True, 'italic': False, 'color': '#DDE5FF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.73,
            y=7.13,
            width=4.0,
            height=0.18,
            text='Su et al., arXiv:2604.07900',
            font={'name': 'Noto Sans CJK SC', 'size': 8.0, 'bold': False, 'italic': False, 'color': '#687392'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=12.15,
            y=7.13,
            width=0.55,
            height=0.2,
            text='14',
            font={'name': 'Noto Sans CJK SC', 'size': 8.5, 'bold': False, 'italic': False, 'color': '#687392'},
            paragraph={'align': 'right', 'vertical': 'middle'},
        )
    )

