# -*- coding: utf-8 -*-
# Slide 03 Definition DSL
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
            text='现有方法以及局限',
            font={'name': 'Noto Sans CJK SC', 'size': 26.0, 'bold': True, 'italic': False, 'color': '#0B1020'},
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
            style={'fill': '#6C5CE7', 'border': '#6C5CE7', 'border_width': 0.8},
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
            text='PAPER FIG.1',
            font={'name': 'Noto Sans CJK SC', 'size': 9.5, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=0.695,
            y=1.78,
            width=4.601,
            height=5.219,
            radius=0.022,
            style={'fill': '#FBFCFE', 'border': '#D8DDEA'},
        )
    )

    add_image(
        slide,
        src='assets/image1.png',
        x=0.88,
        y=1.9,
        width=4.2,
        height=5.0,
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=5.55,
            y=1.78,
            width=6.98,
            height=1.24,
            radius=0.0806,
            style={'fill': '#E8F6EF', 'border': '#C7E8D7'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=5.82,
            y=2.02,
            width=1.18,
            height=0.34,
            radius=0.5294,
            style={'fill': '#29A36A', 'border': '#29A36A', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=5.82,
            y=2.02,
            width=1.18,
            height=0.34,
            text='Few-shot',
            font={'name': 'Noto Sans CJK SC', 'size': 10.5, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=7.22,
            y=1.819,
            width=4.8,
            height=1.147,
            text='少样本异常生成\n通过GAN、Diffusion等生成模型学习缺陷分布\n更贴近真实缺陷分布，但受训练异常类型限制。',
            font={'name': 'Noto Sans CJK SC', 'size': 14.0, 'bold': True, 'italic': False, 'color': '#29A36A'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=5.55,
            y=3.17,
            width=6.98,
            height=1.24,
            radius=0.0806,
            style={'fill': '#EAF2FF', 'border': '#C7D9FB'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=5.82,
            y=3.42,
            width=1.28,
            height=0.34,
            radius=0.5294,
            style={'fill': '#2D7FF9', 'border': '#2D7FF9', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=5.82,
            y=3.42,
            width=1.28,
            height=0.34,
            text='Zero-shot',
            font={'name': 'Noto Sans CJK SC', 'size': 10.5, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=7.22,
            y=3.191,
            width=5.306,
            height=1.139,
            text='零样本异常生成\n进行裁剪、粘贴、扰动,利用预训练生成模型来生成异常\n更容易开放集泛化，但语义真实性往往不足。',
            font={'name': 'Noto Sans CJK SC', 'size': 14.0, 'bold': True, 'italic': False, 'color': '#2D7FF9'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=5.55,
            y=4.58,
            width=6.98,
            height=1.58,
            radius=0.0633,
            style={'fill': '#FCECEF', 'border': '#F1C9D2'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=5.82,
            y=4.83,
            width=1.58,
            height=0.34,
            radius=0.5294,
            style={'fill': '#E85D75', 'border': '#E85D75', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=5.82,
            y=4.83,
            width=1.58,
            height=0.34,
            text='Common issue',
            font={'name': 'Noto Sans CJK SC', 'size': 10.2, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=7.55,
            y=4.83,
            width=4.4,
            height=0.34,
            text='Single-step / Open-loop generation',
            font={'name': 'Noto Sans CJK SC', 'size': 15.5, 'bold': True, 'italic': False, 'color': '#E85D75'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=5.84,
            y=5.34,
            width=6.551,
            height=0.52,
            text='生成错了以后，没有reasoning、reflection，也没有iterative refinement。',
            font={'name': 'Noto Sans CJK SC', 'size': 13.1, 'bold': False, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=5.66,
            y=6.35,
            width=6.74,
            height=0.52,
            radius=0.1923,
            style={'fill': '#EEEAFB', 'border': '#6C5CE7'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=5.84,
            y=6.43,
            width=6.38,
            height=0.36,
            text='关键转变：把 anomaly synthesis 重定义为 sequential decision making',
            font={'name': 'Noto Sans CJK SC', 'size': 15.0, 'bold': True, 'italic': False, 'color': '#6C5CE7'},
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
            text='Paper screenshot: Fig.1 (p.1) · Su et al., arXiv:2604.07900',
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
            text='03',
            font={'name': 'Noto Sans CJK SC', 'size': 8.5, 'bold': False, 'italic': False, 'color': '#8A92A8'},
            paragraph={'align': 'right', 'vertical': 'middle'},
        )
    )

