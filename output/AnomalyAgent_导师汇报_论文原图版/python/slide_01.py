# -*- coding: utf-8 -*-
# Slide 01 Definition DSL
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
            type='line',
            x=0.35,
            y=0.0,
            width=0.0,
            height=7.5,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=1.3,
            y=0.0,
            width=0.0,
            height=7.5,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=2.25,
            y=0.0,
            width=0.0,
            height=7.5,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=3.2,
            y=0.0,
            width=0.0,
            height=7.5,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=4.15,
            y=0.0,
            width=0.0,
            height=7.5,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=5.1,
            y=0.0,
            width=0.0,
            height=7.5,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=6.05,
            y=0.0,
            width=0.0,
            height=7.5,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=7.0,
            y=0.0,
            width=0.0,
            height=7.5,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=7.95,
            y=0.0,
            width=0.0,
            height=7.5,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=8.9,
            y=0.0,
            width=0.0,
            height=7.5,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=9.85,
            y=0.0,
            width=0.0,
            height=7.5,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=10.8,
            y=0.0,
            width=0.0,
            height=7.5,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=11.75,
            y=0.0,
            width=0.0,
            height=7.5,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=12.7,
            y=0.0,
            width=0.0,
            height=7.5,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=0.0,
            y=0.3,
            width=13.333,
            height=0.0,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=0.0,
            y=1.2,
            width=13.333,
            height=0.0,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=0.0,
            y=2.1,
            width=13.333,
            height=0.0,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=0.0,
            y=3.0,
            width=13.333,
            height=0.0,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=0.0,
            y=3.9,
            width=13.333,
            height=0.0,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=0.0,
            y=4.8,
            width=13.333,
            height=0.0,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=0.0,
            y=5.7,
            width=13.333,
            height=0.0,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=0.0,
            y=6.6,
            width=13.333,
            height=0.0,
            style={'border': '#18213B', 'border_width': 0.7},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.82,
            y=1.15,
            width=7.8,
            height=0.85,
            text='AnomalyAgent',
            font={'name': 'Noto Sans CJK SC', 'size': 39.0, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.85,
            y=2.03,
            width=7.95,
            height=1.35,
            text='Agentic Industrial Anomaly Synthesis via\nTool-Augmented Reinforcement Learning',
            font={'name': 'Noto Sans CJK SC', 'size': 27.0, 'bold': True, 'italic': False, 'color': '#DDE5FF'},
            paragraph={'align': 'left', 'vertical': 'top'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.86,
            y=5.57,
            width=8.5,
            height=0.34,
            text='arXiv:2604.07900  ·  汇报人：何聚敛  ·  2026-09-08',
            font={'name': 'Noto Sans CJK SC', 'size': 12.5, 'bold': False, 'italic': False, 'color': '#A9B2CC'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

