import type {
  SlideIR, ShapeElementIR, TextElementIR,
  ConnectorElementIR, ImageElementIR, FillStyle, BorderStyle
} from '../types/ppt'
import { usePPTStore } from '../store/usePPTStore'

interface Props {
  slide: SlideIR
  isThumbnail?: boolean
}

export const SVGRendererComponent: React.FC<Props> = ({ slide, isThumbnail = false }) => {
  const { selectedElementId, setSelectedElementId } = usePPTStore()

  // Generate unique gradient IDs for this slide
  const renderDefs = () => {
    const defs: React.ReactNode[] = [
      <marker
        key="arrow-end"
        id={`arrow-end-${slide.id}`}
        viewBox="0 0 12 12"
        refX="10"
        refY="6"
        markerWidth="7"
        markerHeight="7"
        orient="auto-start-reverse"
      >
        <path d="M 0 1 L 12 6 L 0 11 z" fill="context-stroke" />
      </marker>,
      <marker
        key="arrow-start"
        id={`arrow-start-${slide.id}`}
        viewBox="0 0 12 12"
        refX="2"
        refY="6"
        markerWidth="7"
        markerHeight="7"
        orient="auto-start-reverse"
      >
        <path d="M 12 1 L 0 6 L 12 11 z" fill="context-stroke" />
      </marker>,
      <filter
        key="drop-shadow"
        id={`shadow-${slide.id}`}
        x="-20%"
        y="-20%"
        width="140%"
        height="140%"
      >
        <feDropShadow dx="2" dy="4" stdDeviation="4" floodOpacity="0.25" />
      </filter>
    ]

    // Scan for gradients in background and elements
    if (slide.background.type === 'gradient' && slide.background.gradient) {
      defs.push(
        renderLinearGradient(`bg-grad-${slide.id}`, slide.background.gradient)
      )
    }

    slide.elements.forEach((elem) => {
      if (elem.style.fill?.type === 'gradient' && elem.style.fill.gradient) {
        defs.push(
          renderLinearGradient(`grad-${elem.id}`, elem.style.fill.gradient)
        )
      }
    })

    return <defs>{defs}</defs>
  }

  const renderLinearGradient = (id: string, grad: any) => {
    const rad = (grad.angle * Math.PI) / 180
    const x1 = `${Math.round(50 - 50 * Math.cos(rad))}%`
    const y1 = `${Math.round(50 - 50 * Math.sin(rad))}%`
    const x2 = `${Math.round(50 + 50 * Math.cos(rad))}%`
    const y2 = `${Math.round(50 + 50 * Math.sin(rad))}%`

    return (
      <linearGradient key={id} id={id} x1={x1} y1={y1} x2={x2} y2={y2}>
        {grad.stops.map((s: any, idx: number) => (
          <stop
            key={idx}
            offset={`${Math.round(s.position * 100)}%`}
            stopColor={s.color}
            stopOpacity={s.alpha}
          />
        ))}
      </linearGradient>
    )
  }

  const getFillValue = (fill?: FillStyle, elemId?: string) => {
    if (!fill || fill.type === 'none') return 'none'
    if (fill.type === 'gradient' && fill.gradient) {
      return `url(#${elemId ? `grad-${elemId}` : `bg-grad-${slide.id}`})`
    }
    const color = fill.color || '#2A2A2A'
    if (fill.alpha < 1.0) {
      return hexToRgba(color, fill.alpha)
    }
    return color
  }

  const getStrokeProps = (border?: BorderStyle) => {
    if (!border || border.style === 'none' || border.width <= 0) {
      return { stroke: 'none', strokeWidth: 0 }
    }
    let stroke = border.color || '#333333'
    if (border.alpha < 1.0) {
      stroke = hexToRgba(stroke, border.alpha)
    }
    let strokeDasharray = undefined
    if (border.style === 'dashed') strokeDasharray = '6,4'
    else if (border.style === 'dotted') strokeDasharray = '2,2'

    return {
      stroke,
      strokeWidth: border.width,
      strokeDasharray
    }
  }

  const hexToRgba = (hex: string, alpha: number) => {
    const h = hex.replace('#', '')
    if (h.length === 6) {
      const r = parseInt(h.substring(0, 2), 16)
      const g = parseInt(h.substring(2, 4), 16)
      const b = parseInt(h.substring(4, 6), 16)
      return `rgba(${r},${g},${b},${alpha})`
    }
    return hex
  }

  // Render text inside shape or textbox
  const renderTextContent = (tc: any, x: number, y: number, w: number, _h: number, pad: number = 8) => {
    if (!tc || !tc.paragraphs || tc.paragraphs.length === 0) return null

    let currY = y + pad
    return (
      <g>
        {tc.paragraphs.map((para: any, pIdx: number) => {
          let anchor: 'start' | 'middle' | 'end' = 'start'
          let tx = x + pad
          if (para.align === 'center') {
            anchor = 'middle'
            tx = x + w / 2
          } else if (para.align === 'right') {
            anchor = 'end'
            tx = x + w - pad
          }

          let maxSize = 16
          para.runs?.forEach((r: any) => {
            if (r.font?.size && r.font.size > maxSize) maxSize = r.font.size
          })
          const lineSpacing = para.line_spacing || 1.2
          currY += maxSize * lineSpacing

          return (
            <text
              key={pIdx}
              x={tx}
              y={currY}
              textAnchor={anchor}
              style={{ pointerEvents: 'none', userSelect: 'none' }}
            >
              {para.runs?.map((run: any, rIdx: number) => {
                const font = run.font
                return (
                  <tspan
                    key={rIdx}
                    fontFamily={font?.name || 'Segoe UI, sans-serif'}
                    fontSize={`${font?.size || 16}px`}
                    fontWeight={font?.bold ? 'bold' : 'normal'}
                    fontStyle={font?.italic ? 'italic' : 'normal'}
                    fill={font?.color || '#F8FAFC'}
                  >
                    {run.text}
                  </tspan>
                )
              })}
            </text>
          )
        })}
      </g>
    )
  }

  const renderShapeGeometry = (elem: ShapeElementIR) => {
    const { shape_type, x, y, width: w, height: h, style } = elem
    const fill = getFillValue(style.fill, elem.id)
    const strokeProps = getStrokeProps(style.border)
    const filter = style.shadow?.enabled ? `url(#shadow-${slide.id})` : undefined

    if (shape_type === 'roundRect' || shape_type === 'rounded_rectangle') {
      const rx = style.radius && style.radius > 0 ? style.radius : 12
      return <rect x={x} y={y} width={w} height={h} rx={rx} ry={rx} fill={fill} filter={filter} {...strokeProps} />
    }
    if (shape_type === 'ellipse' || shape_type === 'circle') {
      return (
        <ellipse
          cx={x + w / 2}
          cy={y + h / 2}
          rx={w / 2}
          ry={h / 2}
          fill={fill}
          filter={filter}
          {...strokeProps}
        />
      )
    }
    if (shape_type === 'diamond') {
      const cx = x + w / 2
      const cy = y + h / 2
      const points = `${cx},${y} ${x + w},${cy} ${cx},${y + h} ${x},${cy}`
      return <polygon points={points} fill={fill} filter={filter} {...strokeProps} />
    }
    if (shape_type === 'triangle') {
      const points = `${x + w / 2},${y} ${x + w},${y + h} ${x},${y + h}`
      return <polygon points={points} fill={fill} filter={filter} {...strokeProps} />
    }
    if (shape_type === 'rightArrow' || shape_type === 'arrow') {
      const yMid = y + h / 2
      const headLen = Math.min(w * 0.4, 40)
      const shaftH = h * 0.4
      const yTop = yMid - shaftH / 2
      const yBot = yMid + shaftH / 2
      const headX = x + w - headLen
      const points = `${x},${yTop} ${headX},${yTop} ${headX},${y} ${x + w},${yMid} ${headX},${y + h} ${headX},${yBot} ${x},${yBot}`
      return <polygon points={points} fill={fill} filter={filter} {...strokeProps} />
    }

    // Default rectangle
    return <rect x={x} y={y} width={w} height={h} fill={fill} filter={filter} {...strokeProps} />
  }

  const renderConnector = (conn: ConnectorElementIR) => {
    const strokeProps = getStrokeProps(conn.style.border)
    const markerEnd = conn.arrow_end !== 'none' ? `url(#arrow-end-${slide.id})` : undefined
    const markerStart = conn.arrow_start !== 'none' ? `url(#arrow-start-${slide.id})` : undefined

    let d = `M ${conn.start_x} ${conn.start_y} L ${conn.end_x} ${conn.end_y}`
    if (conn.line_type === 'elbow') {
      const midX = (conn.start_x + conn.end_x) / 2
      d = `M ${conn.start_x} ${conn.start_y} H ${midX} V ${conn.end_y} H ${conn.end_x}`
    }

    return (
      <path
        d={d}
        fill="none"
        markerEnd={markerEnd}
        markerStart={markerStart}
        {...strokeProps}
      />
    )
  }

  return (
    <svg
      viewBox={`0 0 ${slide.width} ${slide.height}`}
      className="w-full h-full block"
      xmlns="http://www.w3.org/2000/svg"
      onClick={() => {
        if (!isThumbnail) setSelectedElementId(null)
      }}
    >
      {renderDefs()}

      {/* Background */}
      <rect
        width={slide.width}
        height={slide.height}
        fill={getFillValue(slide.background)}
      />

      {/* Elements in z-index order */}
      {slide.elements.map((elem) => {
        const isSelected = !isThumbnail && selectedElementId === elem.id
        const transform = elem.rotation ? `rotate(${elem.rotation} ${elem.x + elem.width / 2} ${elem.y + elem.height / 2})` : undefined

        return (
          <g
            key={elem.id}
            id={elem.id}
            transform={transform}
            opacity={elem.style.opacity ?? 1.0}
            className={!isThumbnail ? 'cursor-pointer' : undefined}
            onClick={(e) => {
              if (!isThumbnail) {
                e.stopPropagation()
                setSelectedElementId(elem.id)
              }
            }}
          >
            {elem.type === 'connector' && renderConnector(elem as ConnectorElementIR)}

            {elem.type === 'image' && (
              <image
                href={(elem as ImageElementIR).src}
                x={elem.x}
                y={elem.y}
                width={elem.width}
                height={elem.height}
                preserveAspectRatio="xMidYMid meet"
              />
            )}

            {elem.type === 'shape' && (
              <>
                {renderShapeGeometry(elem as ShapeElementIR)}
                {(elem as ShapeElementIR).text_content &&
                  renderTextContent(
                    (elem as ShapeElementIR).text_content,
                    elem.x,
                    elem.y,
                    elem.width,
                    elem.height,
                    elem.style.padding
                  )}
              </>
            )}

            {elem.type === 'text' && (
              <>
                {/* Optional background / border for text box */}
                {(elem.style.fill?.type !== 'none' || elem.style.border?.style !== 'none') && (
                  <rect
                    x={elem.x}
                    y={elem.y}
                    width={elem.width}
                    height={elem.height}
                    fill={getFillValue(elem.style.fill, elem.id)}
                    {...getStrokeProps(elem.style.border)}
                  />
                )}
                {renderTextContent(
                  (elem as TextElementIR).text_content,
                  elem.x,
                  elem.y,
                  elem.width,
                  elem.height,
                  elem.style.padding
                )}
              </>
            )}

            {/* Selection Bounding Box & Handles (Crisp Monochrome Hairline) */}
            {isSelected && (
              <g className="pointer-events-none">
                <rect
                  x={elem.x - 2}
                  y={elem.y - 2}
                  width={elem.width + 4}
                  height={elem.height + 4}
                  fill="none"
                  stroke="#FFFFFF"
                  strokeWidth="1.5"
                  strokeDasharray="4,3"
                />
                {/* 4 corner handles */}
                <rect x={elem.x - 5} y={elem.y - 5} width="6" height="6" fill="#FFFFFF" stroke="#000000" strokeWidth="1" />
                <rect x={elem.x + elem.width - 1} y={elem.y - 5} width="6" height="6" fill="#FFFFFF" stroke="#000000" strokeWidth="1" />
                <rect x={elem.x - 5} y={elem.y + elem.height - 1} width="6" height="6" fill="#FFFFFF" stroke="#000000" strokeWidth="1" />
                <rect x={elem.x + elem.width - 1} y={elem.y + elem.height - 1} width="6" height="6" fill="#FFFFFF" stroke="#000000" strokeWidth="1" />
                {/* Coordinate badge */}
                <rect
                  x={elem.x}
                  y={elem.y - 22}
                  width="110"
                  height="18"
                  rx="3"
                  fill="#121212"
                  stroke="#333333"
                  strokeWidth="1"
                />
                <text
                  x={elem.x + 6}
                  y={elem.y - 9}
                  fill="#EDEDED"
                  fontSize="10px"
                  fontFamily="monospace"
                >
                  {Math.round(elem.width)} × {Math.round(elem.height)} px
                </text>
              </g>
            )}
          </g>
        )
      })}
    </svg>
  )
}
