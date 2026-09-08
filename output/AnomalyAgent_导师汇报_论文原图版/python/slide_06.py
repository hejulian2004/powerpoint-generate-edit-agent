# -*- coding: utf-8 -*-
# Slide 06 Definition DSL
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
            text='关键创新 — Trajectory Construction',
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
            text='用真实异常反向构造多轮 Agent trajectory，无需人工逐步标注。',
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
            width=1.55,
            height=0.33,
            radius=0.5454,
            style={'fill': '#29A36A', 'border': '#29A36A', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.7,
            y=1.42,
            width=1.55,
            height=0.33,
            text='PAPER FIG.3',
            font={'name': 'Noto Sans CJK SC', 'size': 9.5, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=1.55,
            y=1.76,
            width=10.22,
            height=4.88,
            radius=0.0205,
            style={'fill': '#FFFFFF', 'border': '#D8DDEA'},
        )
    )

    add_image(
        slide,
        src='assets/image3.png',
        x=1.78,
        y=1.91,
        width=9.78,
        height=4.78,
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=2.12,
            y=6.47,
            width=9.1,
            height=0.46,
            radius=0.2174,
            style={'fill': '#0B1020', 'border': '#FFFFFF'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=2.3,
            y=6.55,
            width=8.74,
            height=0.3,
            text='核心：Reverse synthesis 得到 I_normal；最终 target 仍是真实 anomaly image。',
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
            text='Paper screenshot: Fig.3 (p.4) · §3.2',
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
            text='06',
            font={'name': 'Noto Sans CJK SC', 'size': 8.5, 'bold': False, 'italic': False, 'color': '#8A92A8'},
            paragraph={'align': 'right', 'vertical': 'middle'},
        )
    )

