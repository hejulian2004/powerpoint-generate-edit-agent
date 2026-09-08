# -*- coding: utf-8 -*-
# Slide 08 Definition DSL
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
            x=0.65,
            y=0.32,
            width=10.9,
            height=0.55,
            text='Reward Design —— 从结果、改进和行为三个维度优化 Agent',
            font={'name': 'Noto Sans CJK SC', 'size': 26.0, 'bold': True, 'italic': False, 'color': '#0B1020'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.67,
            y=0.85,
            width=11.3,
            height=0.34,
            text='核心目标：不仅奖励“生成得好”，还奖励“每一步真的变好”和“工具调用合理”。',
            font={'name': 'Noto Sans CJK SC', 'size': 10.5, 'bold': False, 'italic': False, 'color': '#5B6479'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=0.65,
            y=1.17,
            width=12.0,
            height=0.0,
            style={'border': '#D8DDEA', 'border_width': 1.1},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=0.7,
            y=1.42,
            width=1.12,
            height=0.33,
            radius=0.5454,
            style={'fill': '#F2B84B', 'border': '#F2B84B', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.7,
            y=1.42,
            width=1.12,
            height=0.33,
            text='REWARD',
            font={'name': 'Noto Sans CJK SC', 'size': 9.5, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=0.76,
            y=2.02,
            width=3.32,
            height=3.85,
            radius=0.0301,
            style={'fill': '#EAF2FF', 'border': '#2D7FF9'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=0.98,
            y=2.26,
            width=0.48,
            height=0.34,
            radius=0.5294,
            style={'fill': '#2D7FF9', 'border': '#2D7FF9', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.98,
            y=2.26,
            width=0.48,
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
            x=1.61,
            y=2.2,
            width=2.13,
            height=0.42,
            text='Task Reward',
            font={'name': 'Noto Sans CJK SC', 'size': 17.0, 'bold': True, 'italic': False, 'color': '#2D7FF9'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=1.0,
            y=2.88,
            width=2.82,
            height=0.32,
            text='Is it authentic?',
            font={'name': 'Noto Sans CJK SC', 'size': 10.5, 'bold': True, 'italic': False, 'color': '#5B6479'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=0.99,
            y=3.38,
            width=2.86,
            height=0.82,
            radius=0.122,
            style={'fill': '#FFFFFF', 'border': '#E1E5EF'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=1.07,
            y=4.53,
            width=2.7,
            height=0.72,
            text='最终图是否真实 / 缺陷位置是否合理',
            font={'name': 'Noto Sans CJK SC', 'size': 12.1, 'bold': False, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=4.52,
            y=2.02,
            width=3.32,
            height=3.85,
            radius=0.0301,
            style={'fill': '#EEEAFB', 'border': '#6C5CE7'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=4.74,
            y=2.26,
            width=0.48,
            height=0.34,
            radius=0.5294,
            style={'fill': '#6C5CE7', 'border': '#6C5CE7', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=4.74,
            y=2.26,
            width=0.48,
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
            x=5.37,
            y=2.2,
            width=2.13,
            height=0.42,
            text='Reflection Reward',
            font={'name': 'Noto Sans CJK SC', 'size': 17.0, 'bold': True, 'italic': False, 'color': '#6C5CE7'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=4.76,
            y=2.88,
            width=2.82,
            height=0.32,
            text='Can it improve?',
            font={'name': 'Noto Sans CJK SC', 'size': 10.5, 'bold': True, 'italic': False, 'color': '#5B6479'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=4.75,
            y=3.38,
            width=2.86,
            height=0.82,
            radius=0.122,
            style={'fill': '#FFFFFF', 'border': '#E1E5EF'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=4.83,
            y=4.53,
            width=2.7,
            height=0.72,
            text='每次 refinement 是否真的让质量变好',
            font={'name': 'Noto Sans CJK SC', 'size': 12.1, 'bold': False, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=8.28,
            y=2.02,
            width=3.32,
            height=3.85,
            radius=0.0301,
            style={'fill': '#E8F6EF', 'border': '#29A36A'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=8.5,
            y=2.26,
            width=0.48,
            height=0.34,
            radius=0.5294,
            style={'fill': '#29A36A', 'border': '#29A36A', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=8.5,
            y=2.26,
            width=0.48,
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
            x=9.13,
            y=2.2,
            width=2.13,
            height=0.42,
            text='Behavior Reward',
            font={'name': 'Noto Sans CJK SC', 'size': 17.0, 'bold': True, 'italic': False, 'color': '#29A36A'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=8.52,
            y=2.88,
            width=2.82,
            height=0.32,
            text='Is it well executed?',
            font={'name': 'Noto Sans CJK SC', 'size': 10.5, 'bold': True, 'italic': False, 'color': '#5B6479'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=8.51,
            y=3.38,
            width=2.86,
            height=0.82,
            radius=0.122,
            style={'fill': '#FFFFFF', 'border': '#E1E5EF'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=8.59,
            y=4.28,
            width=2.7,
            height=1.521,
            text='工具顺序、格式、效率是否符合预期\n是否正确执行 Agent workflow\n✓ tool transition validity\n✓ format correctness\n✓ efficient trajectory length\n✓ reasonable KR usage',
            font={'name': 'Noto Sans CJK SC', 'size': 12.1, 'bold': False, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=4.95,
            y=5.32,
            width=0.44,
            height=0.36,
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=3.49,
            y=6.31,
            width=6.36,
            height=0.55,
            radius=0.1818,
            style={'fill': '#0B1020', 'border': '#FFFFFF'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=3.67,
            y=6.39,
            width=6.0,
            height=0.39,
            text='R = αR_task + βR_ref + γR_beh',
            font={'name': 'Noto Sans CJK SC', 'size': 15.0, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.67,
            y=7.16,
            width=5.8,
            height=0.18,
            text='Reward design · Eq.(3–6), §3.3',
            font={'name': 'Noto Sans CJK SC', 'size': 8.0, 'bold': False, 'italic': False, 'color': '#8A92A8'},
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
            text='10',
            font={'name': 'Noto Sans CJK SC', 'size': 8.5, 'bold': False, 'italic': False, 'color': '#8A92A8'},
            paragraph={'align': 'right', 'vertical': 'middle'},
        )
    )

    add_image(
        slide,
        src='assets/image4.png',
        x=1.594,
        y=3.556,
        width=1.637,
        height=0.428,
    )

    add_image(
        slide,
        src='assets/image5.png',
        x=4.921,
        y=3.429,
        width=2.497,
        height=0.722,
    )

    add_image(
        slide,
        src='assets/image6.png',
        x=8.59,
        y=3.499,
        width=2.649,
        height=0.582,
    )

