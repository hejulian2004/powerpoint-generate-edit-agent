# -*- coding: utf-8 -*-
# Slide 07 Definition DSL
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
            text='Three Trajectory Types + SFT',
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
            text='SFT learns format and basic tool-use patterns; RL learns decision quality.',
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
            width=0.82,
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
            width=0.82,
            height=0.33,
            text='SFT',
            font={'name': 'Noto Sans CJK SC', 'size': 9.5, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=0.75,
            y=1.95,
            width=3.45,
            height=2.35,
            radius=0.0425,
            style={'fill': '#FAFBFD', 'border': '#D8DDEA'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=0.97,
            y=2.16,
            width=0.98,
            height=0.34,
            radius=0.5294,
            style={'fill': '#29A36A', 'border': '#29A36A', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=0.97,
            y=2.16,
            width=0.98,
            height=0.34,
            text='Single',
            font={'name': 'Noto Sans CJK SC', 'size': 10.5, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=2.15,
            y=2.16,
            width=1.72,
            height=0.34,
            text='一次生成即通过',
            font={'name': 'Noto Sans CJK SC', 'size': 10.5, 'bold': False, 'italic': False, 'color': '#5B6479'},
            paragraph={'align': 'right', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=1.0,
            y=3.05,
            width=0.48,
            height=0.42,
            radius=0.2381,
            style={'fill': '#F6F7FB', 'border': '#D8DDEA', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=1.0,
            y=3.05,
            width=0.48,
            height=0.42,
            text='PG',
            font={'name': 'Noto Sans CJK SC', 'size': 8.8, 'bold': True, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=1.5,
            y=3.26,
            width=0.07,
            height=0.0,
            style={'border': '#5B6479', 'border_width': 1.1},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=1.59,
            y=3.05,
            width=0.48,
            height=0.42,
            radius=0.2381,
            style={'fill': '#EAF2FF', 'border': '#D8DDEA', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=1.59,
            y=3.05,
            width=0.48,
            height=0.42,
            text='IG',
            font={'name': 'Noto Sans CJK SC', 'size': 8.8, 'bold': True, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=2.09,
            y=3.26,
            width=0.07,
            height=0.0,
            style={'border': '#5B6479', 'border_width': 1.1},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=2.18,
            y=3.05,
            width=0.48,
            height=0.42,
            radius=0.2381,
            style={'fill': '#F6F7FB', 'border': '#D8DDEA', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=2.18,
            y=3.05,
            width=0.48,
            height=0.42,
            text='QE',
            font={'name': 'Noto Sans CJK SC', 'size': 8.8, 'bold': True, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=2.68,
            y=3.26,
            width=0.07,
            height=0.0,
            style={'border': '#5B6479', 'border_width': 1.1},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=2.77,
            y=3.05,
            width=0.48,
            height=0.42,
            radius=0.2381,
            style={'fill': '#F6F7FB', 'border': '#D8DDEA', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=2.77,
            y=3.05,
            width=0.48,
            height=0.42,
            text='MG',
            font={'name': 'Noto Sans CJK SC', 'size': 8.8, 'bold': True, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=4.44,
            y=1.95,
            width=3.45,
            height=2.35,
            radius=0.0425,
            style={'fill': '#FAFBFD', 'border': '#D8DDEA'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=4.66,
            y=2.16,
            width=0.98,
            height=0.34,
            radius=0.5294,
            style={'fill': '#2D7FF9', 'border': '#2D7FF9', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=4.66,
            y=2.16,
            width=0.98,
            height=0.34,
            text='Dual',
            font={'name': 'Noto Sans CJK SC', 'size': 10.5, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=5.84,
            y=2.16,
            width=1.72,
            height=0.34,
            text='一次失败后修正',
            font={'name': 'Noto Sans CJK SC', 'size': 10.5, 'bold': False, 'italic': False, 'color': '#5B6479'},
            paragraph={'align': 'right', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=4.69,
            y=3.05,
            width=0.48,
            height=0.42,
            radius=0.2381,
            style={'fill': '#F6F7FB', 'border': '#D8DDEA', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=4.69,
            y=3.05,
            width=0.48,
            height=0.42,
            text='PG',
            font={'name': 'Noto Sans CJK SC', 'size': 8.8, 'bold': True, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=5.19,
            y=3.26,
            width=0.07,
            height=0.0,
            style={'border': '#5B6479', 'border_width': 1.1},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=5.28,
            y=3.05,
            width=0.48,
            height=0.42,
            radius=0.2381,
            style={'fill': '#EAF2FF', 'border': '#D8DDEA', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=5.28,
            y=3.05,
            width=0.48,
            height=0.42,
            text='IG',
            font={'name': 'Noto Sans CJK SC', 'size': 8.8, 'bold': True, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=5.78,
            y=3.26,
            width=0.07,
            height=0.0,
            style={'border': '#5B6479', 'border_width': 1.1},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=5.87,
            y=3.05,
            width=0.48,
            height=0.42,
            radius=0.2381,
            style={'fill': '#F6F7FB', 'border': '#D8DDEA', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=5.87,
            y=3.05,
            width=0.48,
            height=0.42,
            text='QE',
            font={'name': 'Noto Sans CJK SC', 'size': 8.8, 'bold': True, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=6.37,
            y=3.26,
            width=0.07,
            height=0.0,
            style={'border': '#5B6479', 'border_width': 1.1},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=6.46,
            y=3.05,
            width=0.55,
            height=0.42,
            radius=0.2381,
            style={'fill': '#E8F6EF', 'border': '#29A36A', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=6.46,
            y=3.05,
            width=0.55,
            height=0.42,
            text='KR?',
            font={'name': 'Noto Sans CJK SC', 'size': 8.8, 'bold': True, 'italic': False, 'color': '#29A36A'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=6.722,
            y=3.514,
            width=0.07,
            height=0.0,
            rotation=90.0,
            style={'border': '#5B6479', 'border_width': 1.1},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=5.905,
            y=3.549,
            width=0.48,
            height=0.42,
            radius=0.2381,
            style={'fill': '#EAF2FF', 'border': '#D8DDEA', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=5.905,
            y=3.549,
            width=0.48,
            height=0.42,
            text='IG',
            font={'name': 'Noto Sans CJK SC', 'size': 8.8, 'bold': True, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=6.4,
            y=3.76,
            width=0.07,
            height=0.0,
            rotation=180.0,
            style={'border': '#5B6479', 'border_width': 1.1},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=6.495,
            y=3.549,
            width=0.48,
            height=0.42,
            radius=0.2381,
            style={'fill': '#F6F7FB', 'border': '#D8DDEA', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=6.483,
            y=3.549,
            width=0.48,
            height=0.42,
            text='QE',
            font={'name': 'Noto Sans CJK SC', 'size': 8.8, 'bold': True, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=8.275,
            y=3.293,
            width=0.07,
            height=0.0,
            style={'border': '#5B6479', 'border_width': 1.1},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=8.365,
            y=3.083,
            width=0.48,
            height=0.42,
            radius=0.2381,
            style={'fill': '#F6F7FB', 'border': '#D8DDEA', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=8.365,
            y=3.083,
            width=0.48,
            height=0.42,
            text='MG',
            font={'name': 'Noto Sans CJK SC', 'size': 8.8, 'bold': True, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=8.195,
            y=1.983,
            width=3.45,
            height=2.35,
            radius=0.0425,
            style={'fill': '#FAFBFD', 'border': '#D8DDEA'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=8.415,
            y=2.193,
            width=0.98,
            height=0.34,
            radius=0.5294,
            style={'fill': '#6C5CE7', 'border': '#6C5CE7', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=8.415,
            y=2.193,
            width=0.98,
            height=0.34,
            text='Triple',
            font={'name': 'Noto Sans CJK SC', 'size': 10.5, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=9.595,
            y=2.193,
            width=1.72,
            height=0.34,
            text='多轮困难样本',
            font={'name': 'Noto Sans CJK SC', 'size': 10.5, 'bold': False, 'italic': False, 'color': '#5B6479'},
            paragraph={'align': 'right', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=8.445,
            y=3.083,
            width=0.48,
            height=0.42,
            radius=0.2381,
            style={'fill': '#F6F7FB', 'border': '#D8DDEA', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=8.445,
            y=3.083,
            width=0.48,
            height=0.42,
            text='PG',
            font={'name': 'Noto Sans CJK SC', 'size': 8.8, 'bold': True, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=8.945,
            y=3.293,
            width=0.07,
            height=0.0,
            style={'border': '#5B6479', 'border_width': 1.1},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=9.035,
            y=3.083,
            width=0.48,
            height=0.42,
            radius=0.2381,
            style={'fill': '#EAF2FF', 'border': '#D8DDEA', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=9.035,
            y=3.083,
            width=0.48,
            height=0.42,
            text='IG',
            font={'name': 'Noto Sans CJK SC', 'size': 8.8, 'bold': True, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=9.535,
            y=3.293,
            width=0.07,
            height=0.0,
            style={'border': '#5B6479', 'border_width': 1.1},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=9.625,
            y=3.083,
            width=0.48,
            height=0.42,
            radius=0.2381,
            style={'fill': '#F6F7FB', 'border': '#D8DDEA', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=9.625,
            y=3.083,
            width=0.48,
            height=0.42,
            text='QE',
            font={'name': 'Noto Sans CJK SC', 'size': 8.8, 'bold': True, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=10.125,
            y=3.293,
            width=0.07,
            height=0.0,
            style={'border': '#5B6479', 'border_width': 1.1},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=10.215,
            y=3.083,
            width=0.48,
            height=0.42,
            radius=0.2381,
            style={'fill': '#E8F6EF', 'border': '#29A36A', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=10.215,
            y=3.083,
            width=0.48,
            height=0.42,
            text='KR',
            font={'name': 'Noto Sans CJK SC', 'size': 8.8, 'bold': True, 'italic': False, 'color': '#29A36A'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=10.715,
            y=3.293,
            width=0.07,
            height=0.0,
            style={'border': '#5B6479', 'border_width': 1.1},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=10.805,
            y=3.083,
            width=0.48,
            height=0.42,
            radius=0.2381,
            style={'fill': '#EAF2FF', 'border': '#D8DDEA', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=10.805,
            y=3.083,
            width=0.48,
            height=0.42,
            text='IG',
            font={'name': 'Noto Sans CJK SC', 'size': 8.8, 'bold': True, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=11.031,
            y=3.565,
            width=0.07,
            height=0.0,
            rotation=90.0,
            style={'border': '#5B6479', 'border_width': 1.1},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=9.056,
            y=3.6,
            width=0.48,
            height=0.42,
            radius=0.2381,
            style={'fill': '#F6F7FB', 'border': '#D8DDEA', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=9.056,
            y=3.6,
            width=0.48,
            height=0.42,
            text='QE',
            font={'name': 'Noto Sans CJK SC', 'size': 8.8, 'bold': True, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=9.556,
            y=3.81,
            width=0.07,
            height=0.0,
            style={'border': '#5B6479', 'border_width': 1.1},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=9.646,
            y=3.6,
            width=0.48,
            height=0.42,
            radius=0.2381,
            style={'fill': '#EAF2FF', 'border': '#D8DDEA', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=9.646,
            y=3.6,
            width=0.48,
            height=0.42,
            text='IG',
            font={'name': 'Noto Sans CJK SC', 'size': 8.8, 'bold': True, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=10.146,
            y=3.81,
            width=0.07,
            height=0.0,
            style={'border': '#5B6479', 'border_width': 1.1},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=10.236,
            y=3.6,
            width=0.48,
            height=0.42,
            radius=0.2381,
            style={'fill': '#F6F7FB', 'border': '#D8DDEA', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=10.236,
            y=3.6,
            width=0.48,
            height=0.42,
            text='QE',
            font={'name': 'Noto Sans CJK SC', 'size': 8.8, 'bold': True, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='line',
            x=10.736,
            y=3.81,
            width=0.07,
            height=0.0,
            style={'border': '#5B6479', 'border_width': 1.1},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=10.826,
            y=3.6,
            width=0.48,
            height=0.42,
            radius=0.2381,
            style={'fill': '#F6F7FB', 'border': '#D8DDEA', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=10.826,
            y=3.6,
            width=0.48,
            height=0.42,
            text='MG',
            font={'name': 'Noto Sans CJK SC', 'size': 8.8, 'bold': True, 'italic': False, 'color': '#15203B'},
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
            text='Trajectory taxonomy & Eq.(1) · §3.2',
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
            text='07',
            font={'name': 'Noto Sans CJK SC', 'size': 8.5, 'bold': False, 'italic': False, 'color': '#8A92A8'},
            paragraph={'align': 'right', 'vertical': 'middle'},
        )
    )

