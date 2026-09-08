# -*- coding: utf-8 -*-
# Slide 02 Definition DSL
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
            text='为什么需要异常合成？',
            font={'name': 'Noto Sans CJK SC', 'size': 24.0, 'bold': True, 'italic': False, 'color': '#0B1020'},
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
            style={'fill': '#E85D75', 'border': '#E85D75', 'border_width': 0.8},
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
            text='存在的问题',
            font={'name': 'Noto Sans CJK SC', 'size': 14.0, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=0.72,
            y=1.9,
            width=5.75,
            height=4.62,
            radius=0.0216,
            style={'fill': '#FFFFFF', 'border': '#D8DDEA'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=1.0,
            y=2.12,
            width=2.4,
            height=0.38,
            text='现实数据分布',
            font={'name': 'Noto Sans CJK SC', 'size': 18.0, 'bold': True, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=1.05,
            y=2.82,
            width=1.25,
            height=0.32,
            text='正常样本',
            font={'name': 'Noto Sans CJK SC', 'size': 13.0, 'bold': True, 'italic': False, 'color': '#29A36A'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=1.07,
            y=3.22,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=1.55,
            y=3.22,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=2.03,
            y=3.22,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=2.51,
            y=3.22,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=2.99,
            y=3.22,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=3.47,
            y=3.22,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=3.95,
            y=3.22,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=1.07,
            y=3.7,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=1.55,
            y=3.7,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=2.03,
            y=3.7,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=2.51,
            y=3.7,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=2.99,
            y=3.7,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=3.47,
            y=3.7,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=3.95,
            y=3.7,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=1.07,
            y=4.18,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=1.55,
            y=4.18,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=2.03,
            y=4.18,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=2.51,
            y=4.18,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=2.99,
            y=4.18,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=3.47,
            y=4.18,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=3.95,
            y=4.18,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=1.07,
            y=4.66,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=1.55,
            y=4.66,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=2.03,
            y=4.66,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=2.51,
            y=4.66,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=2.99,
            y=4.66,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=3.47,
            y=4.66,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=3.95,
            y=4.66,
            width=0.31,
            height=0.31,
            radius=0.1935,
            style={'fill': '#D9F2E6', 'border': '#B8E5CE', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=4.35,
            y=3.96,
            width=1.55,
            height=0.32,
            text='正样本多/易采集',
            font={'name': 'Noto Sans CJK SC', 'size': 12.0, 'bold': False, 'italic': False, 'color': '#29A36A'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=1.05,
            y=5.12,
            width=1.25,
            height=0.32,
            text='异常样本',
            font={'name': 'Noto Sans CJK SC', 'size': 13.0, 'bold': True, 'italic': False, 'color': '#E85D75'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=1.04,
            y=5.44,
            width=0.34,
            height=0.34,
            radius=0.1765,
            style={'fill': '#FADAE1', 'border': '#F3AABC', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=1.56,
            y=5.44,
            width=0.34,
            height=0.34,
            radius=0.1765,
            style={'fill': '#FADAE1', 'border': '#F3AABC', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=2.08,
            y=5.44,
            width=0.34,
            height=0.34,
            radius=0.1765,
            style={'fill': '#FADAE1', 'border': '#F3AABC', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=2.6,
            y=5.44,
            width=0.34,
            height=0.34,
            radius=0.1765,
            style={'fill': '#FADAE1', 'border': '#F3AABC', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=3.12,
            y=5.44,
            width=0.34,
            height=0.34,
            radius=0.1765,
            style={'fill': '#FADAE1', 'border': '#F3AABC', 'border_width': 0.6},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=3.78,
            y=5.515,
            width=2.601,
            height=0.535,
            text='缺陷极少+种类多样+难采集\n导致训练数据不足',
            font={'name': 'Noto Sans CJK SC', 'size': 12.0, 'bold': False, 'italic': False, 'color': '#E85D75'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=6.85,
            y=1.9,
            width=5.75,
            height=4.62,
            radius=0.0216,
            style={'fill': '#FFFFFF', 'border': '#D8DDEA'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=6.955,
            y=2.12,
            width=5.666,
            height=0.38,
            text='工业异常合成（Industrial Anomaly Synthesis）',
            font={'name': 'Noto Sans CJK SC', 'size': 14.0, 'bold': True, 'italic': False, 'color': '#15203B'},
            paragraph={'align': 'left', 'vertical': 'middle'},
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
            text='Su et al., arXiv:2604.07900 (2026)',
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
            text='02',
            font={'name': 'Noto Sans CJK SC', 'size': 8.5, 'bold': False, 'italic': False, 'color': '#8A92A8'},
            paragraph={'align': 'right', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='roundRect',
            x=6.85,
            y=1.42,
            width=1.2,
            height=0.33,
            radius=0.5454,
            style={'fill': '#E85D75', 'border': '#E85D75', 'border_width': 0.8},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=6.85,
            y=1.42,
            width=1.2,
            height=0.33,
            text='现有思路',
            font={'name': 'Noto Sans CJK SC', 'size': 14.0, 'bold': True, 'italic': False, 'color': '#FFFFFF'},
            paragraph={'align': 'center', 'vertical': 'middle'},
        )
    )

    add_shape(
        slide,
        Shape(
            type='rectangle',
            x=7.049,
            y=3.482,
            width=5.262,
            height=0.706,
            text='人为合成裂纹、孔洞、破损等缺陷，再用这些合成数据训练异常检测或异常分割模型',
            font={'name': '', 'size': 14.0, 'bold': False, 'italic': False, 'color': '#000000'},
            paragraph={'align': 'left', 'vertical': 'middle'},
        )
    )

