# -*- coding: utf-8 -*-
# Slide 10 Definition DSL
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
            text='Visualization + Ablation',
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
            width=1.7,
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
            width=1.7,
            height=0.33,
            text='PAPER RESULTS',
            font={'name': 'Noto Sans CJK SC', 'size': 9.5, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=0.72,
            y=1.82,
            width=6.44,
            height=4.84,
            radius=0.0284,
            style={'fill': '#F6F7FB', 'border': '#D8DDEA'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.98,
            y=6.328,
            width=5.85,
            height=0.24,
            text='Fig.5 · qualitative synthesis comparison',
            font={'name': 'Noto Sans CJK SC', 'size': 9.2, 'bold': False, 'italic': False, 'color': '#5B6479'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=7.38,
            y=1.82,
            width=5.15,
            height=4.84,
            radius=0.0207,
            style={'fill': '#FFFFFF', 'border': '#D8DDEA'},
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
            text='Paper screenshots: Fig.5 + Table 4/5 (p.8)',
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
            text='12',
            font={'name': 'Noto Sans CJK SC', 'size': 8.5, 'bold': False, 'italic': False, 'color': '#8A92A8'},
            paragraph={'align': 'right', 'vertical': 'middle'},
        )
    )

    add_image(
        slide,
        src='assets/image9.png',
        x=7.533,
        y=1.96,
        width=4.842,
        height=4.608,
    )

    add_image(
        slide,
        src='assets/image10.png',
        x=0.784,
        y=2.139,
        width=6.242,
        height=4.051,
    )

