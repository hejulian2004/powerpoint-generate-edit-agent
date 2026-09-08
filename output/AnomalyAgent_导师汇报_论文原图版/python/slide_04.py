# -*- coding: utf-8 -*-
# Slide 04 Definition DSL
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
            x=0.08,
            y=0.07,
            width=13.169,
            height=7.34,
            style={'border': '#D2DBEE', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.72,
            y=0.313,
            width=8.8,
            height=0.554,
            text='Core Idea — 从 Open-loop 到 Closed-loop',
            font={'name': '微软雅黑', 'size': 27.0, 'bold': False, 'italic': False, 'color': '#F4F7FF'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.74,
            y=0.81,
            width=6.2,
            height=0.31,
            text='Generation becomes an iterative optimization process.',
            font={'name': 'Segoe Print', 'size': 12.5, 'bold': False, 'italic': False, 'color': '#A4B3D7'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=0.8,
            y=1.43,
            width=1.37,
            height=0.4,
            style={'fill': '#3385F6', 'border': '#3385F6', 'border_width': 1.3},
            text='Perception',
            font={'name': 'Segoe Print', 'size': 13.0, 'bold': False, 'italic': False, 'color': '#F4F7FF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_connector(
        slide,
        start=(2.22, 1.63),
        end=(2.8, 1.63),
        arrow_start='triangle',
        line={'color': '#626E8B', 'width': 2.0, 'arrow_start': 'triangle'},
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=2.86,
            y=1.43,
            width=1.48,
            height=0.4,
            style={'fill': '#6C53E1', 'border': '#6C53E1', 'border_width': 1.3},
            text='Reflection',
            font={'name': 'Segoe Print', 'size': 13.0, 'bold': False, 'italic': False, 'color': '#F4F7FF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_connector(
        slide,
        start=(4.39, 1.63),
        end=(4.92, 1.63),
        arrow_start='triangle',
        line={'color': '#626E8B', 'width': 2.0, 'arrow_start': 'triangle'},
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=4.99,
            y=1.43,
            width=1.25,
            height=0.4,
            style={'fill': '#26AC6F', 'border': '#26AC6F', 'border_width': 1.3},
            text='Action',
            font={'name': 'Segoe Print', 'size': 13.0, 'bold': False, 'italic': False, 'color': '#F4F7FF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=6.78,
            y=1.452,
            width=5.45,
            height=0.335,
            text='允许第一次失败，关键是让系统知道“哪里错了、怎么改”。',
            font={'name': '微软雅黑', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#F4F7FF'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=0.84,
            y=3.08,
            width=1.33,
            height=0.9,
            style={'fill': '#19223A', 'border': '#626E8B', 'border_width': 1.3},
            text='Normal\nImage',
            font={'name': 'Segoe Print', 'size': 16.0, 'bold': False, 'italic': False, 'color': '#F4F7FF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=2.63,
            y=3.08,
            width=1.35,
            height=0.9,
            style={'fill': '#19223A', 'border': '#626E8B', 'border_width': 1.3},
            text='Prompt\nGeneration',
            font={'name': 'Segoe Print', 'size': 14.2, 'bold': False, 'italic': False, 'color': '#F4F7FF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=4.42,
            y=3.08,
            width=1.35,
            height=0.9,
            style={'fill': '#302859', 'border': '#6C53E1', 'border_width': 1.3},
            text='Image\nGeneration',
            font={'name': 'Segoe Print', 'size': 14.3, 'bold': False, 'italic': False, 'color': '#F4F7FF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=6.21,
            y=3.08,
            width=1.35,
            height=0.9,
            style={'fill': '#263653', 'border': '#626E8B', 'border_width': 1.3},
            text='Quality\nEvaluation',
            font={'name': 'Segoe Print', 'size': 14.3, 'bold': False, 'italic': False, 'color': '#F4F7FF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='diamond',
            x=8.08,
            y=3.03,
            width=1.17,
            height=1.02,
            style={'fill': '#43331F', 'border': '#806031', 'border_width': 1.3},
            text='Good?',
            font={'name': 'Segoe Print', 'size': 13.0, 'bold': False, 'italic': False, 'color': '#F4F7FF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=9.819,
            y=3.08,
            width=1.35,
            height=0.9,
            style={'fill': '#123930', 'border': '#26AC6F', 'border_width': 1.3},
            text='Mask\nGeneration',
            font={'name': 'Segoe Print', 'size': 14.2, 'bold': False, 'italic': False, 'color': '#F4F7FF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=11.629,
            y=3.08,
            width=1.2,
            height=0.9,
            style={'fill': '#123930', 'border': '#26AC6F', 'border_width': 1.3},
            text='Output\nImage +\nMask',
            font={'name': 'Segoe Print', 'size': 12.2, 'bold': False, 'italic': False, 'color': '#26AC6F'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_connector(
        slide,
        start=(2.17, 3.53),
        end=(2.58, 3.53),
        arrow_start='triangle',
        line={'color': '#626E8B', 'width': 2.0, 'arrow_start': 'triangle'},
    )

    add_connector(
        slide,
        start=(3.98, 3.53),
        end=(4.37, 3.53),
        arrow_start='triangle',
        line={'color': '#626E8B', 'width': 2.0, 'arrow_start': 'triangle'},
    )

    add_connector(
        slide,
        start=(5.77, 3.53),
        end=(6.16, 3.53),
        arrow_start='triangle',
        line={'color': '#626E8B', 'width': 2.0, 'arrow_start': 'triangle'},
    )

    add_connector(
        slide,
        start=(7.56, 3.53),
        end=(8.02, 3.53),
        arrow_start='triangle',
        line={'color': '#626E8B', 'width': 2.0, 'arrow_start': 'triangle'},
    )

    add_connector(
        slide,
        start=(9.249, 3.53),
        end=(9.759, 3.53),
        arrow_start='triangle',
        line={'color': '#2DD385', 'width': 2.3, 'arrow_start': 'triangle'},
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=9.339,
            y=3.135,
            width=0.4,
            height=0.419,
            text='YES',
            font={'name': 'Segoe Print', 'size': 9.5, 'bold': False, 'italic': False, 'color': '#2DD385'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_connector(
        slide,
        start=(11.169, 3.53),
        end=(11.569, 3.53),
        arrow_start='triangle',
        line={'color': '#2DD385', 'width': 2.3, 'arrow_start': 'triangle'},
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=7.78,
            y=4.68,
            width=1.55,
            height=0.7,
            style={'fill': '#302859', 'border': '#6C53E1', 'border_width': 1.3},
            text='Self-\nReflection',
            font={'name': 'Segoe Print', 'size': 13.5, 'bold': False, 'italic': False, 'color': '#967EFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='diamond',
            x=6.16,
            y=4.66,
            width=1.08,
            height=0.76,
            style={'fill': '#43331F', 'border': '#806031', 'border_width': 1.3},
            text='Need\nKR?',
            font={'name': 'Segoe Print', 'size': 10.5, 'bold': False, 'italic': False, 'color': '#F4F7FF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=4.15,
            y=4.67,
            width=1.52,
            height=0.72,
            style={'fill': '#123930', 'border': '#26AC6F', 'border_width': 1.3},
            text='Knowledge\nRetrieval',
            font={'name': 'Segoe Print', 'size': 12.4, 'bold': False, 'italic': False, 'color': '#26AC6F'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=2.24,
            y=4.67,
            width=1.47,
            height=0.72,
            style={'fill': '#302859', 'border': '#6C53E1', 'border_width': 1.3},
            text='Refine\nPrompt',
            font={'name': 'Segoe Print', 'size': 13.0, 'bold': False, 'italic': False, 'color': '#9A7EFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_connector(
        slide,
        start=(8.665, 4.04),
        end=(8.665, 4.62),
        arrow_start='triangle',
        line={'color': '#FF5269', 'width': 2.2, 'arrow_start': 'triangle'},
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=8.759,
            y=4.114,
            width=0.34,
            height=0.403,
            text='NO',
            font={'name': 'Segoe Print', 'size': 9.0, 'bold': False, 'italic': False, 'color': '#FF5269'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_connector(
        slide,
        start=(7.73, 5.03),
        end=(7.27, 5.03),
        arrow_start='triangle',
        line={'color': '#626E8B', 'width': 1.9, 'arrow_start': 'triangle'},
    )

    add_connector(
        slide,
        start=(6.12, 5.03),
        end=(5.72, 5.03),
        arrow_start='triangle',
        line={'color': '#26AC6F', 'width': 1.9, 'arrow_start': 'triangle'},
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=5.78,
            y=4.588,
            width=0.3,
            height=0.503,
            text='YES',
            font={'name': 'Segoe Print', 'size': 8.0, 'bold': False, 'italic': False, 'color': '#26AC6F'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_connector(
        slide,
        start=(4.1, 5.03),
        end=(3.76, 5.03),
        arrow_start='triangle',
        line={'color': '#626E8B', 'width': 1.9, 'arrow_start': 'triangle'},
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=4.35,
            y=5.389,
            width=1.12,
            height=0.242,
            text='(optional)',
            font={'name': 'Segoe Print', 'size': 8.5, 'bold': False, 'italic': False, 'color': '#A4B3D7'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_connector(
        slide,
        start=(6.7, 5.42),
        end=(6.7, 5.78),
        line={'color': '#626E8B', 'width': 1.6},
    )

    add_connector(
        slide,
        start=(6.7, 5.78),
        end=(2.98, 5.78),
        line={'color': '#626E8B', 'width': 1.6},
    )

    add_connector(
        slide,
        start=(2.98, 5.78),
        end=(2.98, 5.44),
        arrow_start='triangle',
        line={'color': '#626E8B', 'width': 1.6, 'arrow_start': 'triangle'},
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=6.25,
            y=5.405,
            width=0.34,
            height=0.369,
            text='NO',
            font={'name': 'Segoe Print', 'size': 8.0, 'bold': False, 'italic': False, 'color': '#A4B3D7'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_connector(
        slide,
        start=(2.98, 4.63),
        end=(2.98, 4.29),
        line={'color': '#626E8B', 'width': 2.0},
    )

    add_connector(
        slide,
        start=(2.98, 4.29),
        end=(5.095, 4.29),
        line={'color': '#626E8B', 'width': 2.0},
    )

    add_connector(
        slide,
        start=(5.095, 4.29),
        end=(5.095, 4.04),
        arrow_start='triangle',
        line={'color': '#6C53E1', 'width': 2.2, 'arrow_start': 'triangle'},
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=3.84,
            y=6.2,
            width=5.58,
            height=0.48,
            style={'fill': '#1D2744', 'border': '#C9D3EC'},
            text='Closed-loop optimization',
            font={'name': 'Segoe Print', 'size': 15.0, 'bold': False, 'italic': False, 'color': '#F4F7FF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.72,
            y=6.977,
            width=2.8,
            height=0.226,
            text='Su et al., arXiv:2604.07900',
            font={'name': 'Segoe Print', 'size': 7.5, 'bold': False, 'italic': False, 'color': '#697CA9'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=12.239,
            y=6.973,
            width=0.4,
            height=0.234,
            text='04',
            font={'name': 'Segoe Print', 'size': 8.0, 'bold': False, 'italic': False, 'color': '#697CA9'},
            paragraph={'align': 'right', 'vertical': 'middle'},
        )
    )

