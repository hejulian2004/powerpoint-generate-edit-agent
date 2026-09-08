# -*- coding: utf-8 -*-
# Slide 05 Definition DSL
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
            text='AnomalyAgent Architecture',
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
            style={'fill': '#2D7FF9', 'border': '#2D7FF9', 'border_width': 0.8},
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
            text='PAPER FIG.2',
            font={'name': 'Noto Sans CJK SC', 'size': 9.5, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=1.395,
            y=1.76,
            width=10.525,
            height=5.4,
            radius=0.0192,
            style={'fill': '#FFFFFF', 'border': '#D8DDEA'},
        )
    )

    add_image(
        slide,
        src='assets/image2.png',
        x=1.6,
        y=1.91,
        width=10.14,
        height=5.2,
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.67,
            y=7.16,
            width=5.8,
            height=0.18,
            text='Paper screenshot: Fig.2 (p.2) · implementation from §4.1',
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
            text='05',
            font={'name': 'Noto Sans CJK SC', 'size': 8.5, 'bold': False, 'italic': False, 'color': '#8A92A8'},
            paragraph={'align': 'right', 'vertical': 'middle'},
        )
    )

