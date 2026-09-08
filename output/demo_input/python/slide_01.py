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
            type='roundRect',
            x=1.2,
            y=2.5,
            width=2.5,
            height=1.0,
            radius=0.1667,
            style={'fill': '#3366FF', 'border': '#FFFFFF', 'border_width': 1.5, 'shadow': True},
            text='Image Generation',
            font={'name': 'Aptos', 'size': 18.0, 'bold': False, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_connector(
        slide,
        start=(3.7, 3.0),
        end=(5.5, 3.0),
        arrow='triangle',
        line={'color': '#3366FF', 'width': 2.0, 'arrow_end': 'triangle'},
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=5.5,
            y=2.5,
            width=2.5,
            height=1.0,
            style={'fill': '#22AA55', 'border': '#FFFFFF'},
            text='Model Training',
            font={'name': 'Aptos', 'size': 18.0, 'bold': False, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

