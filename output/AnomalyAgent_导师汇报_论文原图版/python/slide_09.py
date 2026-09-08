# -*- coding: utf-8 -*-
# Slide 09 Definition DSL
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
            text='Main Results',
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
            width=1.2,
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
            width=1.2,
            height=0.33,
            text='RESULTS',
            font={'name': 'Noto Sans CJK SC', 'size': 9.5, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
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
            text='Main results · abstract / experiment tables',
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
            text='11',
            font={'name': 'Noto Sans CJK SC', 'size': 8.5, 'bold': False, 'italic': False, 'color': '#8A92A8'},
            paragraph={'align': 'right', 'vertical': 'middle'},
        )
    )

    add_image(
        slide,
        src='assets/image7.png',
        x=0.7,
        y=2.0,
        width=5.413,
        height=4.844,
    )

    add_image(
        slide,
        src='assets/image8.png',
        x=6.826,
        y=2.0,
        width=4.459,
        height=3.438,
    )

