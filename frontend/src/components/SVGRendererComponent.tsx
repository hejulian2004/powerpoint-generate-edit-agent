import type {
  SlideIR, ElementIR, ShapeElementIR, TextElementIR,
  ConnectorElementIR, ImageElementIR, GroupElementIR, FillStyle, BorderStyle
} from '../types/ppt'
import { usePPTStore } from '../store/usePPTStore'
import { themeColors } from '../theme/tokens'
import { AlignmentGuides } from './AlignmentGuides'
import type { SnapGuide } from '../editor/snapping/types'

interface Props {
  slide: SlideIR
  isThumbnail?: boolean
  onElementMouseDown?: (elemId: string, e: React.MouseEvent) => void
  onResizeHandleMouseDown?: (handle: 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w', e: React.MouseEvent) => void
  alignmentGuides?: SnapGuide[]
}

export const SVGRendererComponent: React.FC<Props> = ({
  slide,
  isThumbnail = false,
  onElementMouseDown,
  onResizeHandleMouseDown,
  alignmentGuides = []
}) => {
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
        <feDropShadow dx="0" dy="6" stdDeviation="6" floodColor="#000000" floodOpacity="0.4" />
      </filter>
    ]

    // Scan for gradients in background and elements recursively
    if (slide.background.type === 'gradient' && slide.background.gradient) {
      defs.push(
        renderLinearGradient(`bg-grad-${slide.id}`, slide.background.gradient)
      )
    }

    const collectGradients = (elements: ElementIR[]) => {
      elements.forEach((elem) => {
        if (elem.style?.fill?.type === 'gradient' && elem.style.fill.gradient) {
          defs.push(
            renderLinearGradient(`grad-${elem.id}`, elem.style.fill.gradient)
          )
        }
        if (elem.type === 'group' && (elem as GroupElementIR).children) {
          collectGradients((elem as GroupElementIR).children)
        }
      })
    }
    collectGradients(slide.elements)

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
    const color = fill.color || themeColors.content.primary
    if (fill.alpha < 1.0) {
      return hexToRgba(color, fill.alpha)
    }
    return color
  }

  const getStrokeProps = (border?: BorderStyle) => {
    if (!border || border.style === 'none' || border.width <= 0) {
      return { stroke: 'none', strokeWidth: 0 }
    }
    let stroke = border.color || themeColors.border.focus
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
  const renderTextContent = (tc: any, x: number, y: number, w: number, _h: number, pad: number = 10) => {
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
          const lineSpacing = para.line_spacing || 1.25
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
                    fontFamily={font?.name || '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'}
                    fontSize={`${font?.size || 16}px`}
                    fontWeight={font?.bold ? '600' : '400'}
                    fontStyle={font?.italic ? 'italic' : 'normal'}
                    fill={font?.color || themeColors.content.primary}
                    letterSpacing="-0.01em"
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

  const renderElementNode = (elem: ElementIR) => {
    const isSelected = !isThumbnail && selectedElementId === elem.id
    const transform = elem.rotation ? `rotate(${elem.rotation} ${elem.x + elem.width / 2} ${elem.y + elem.height / 2})` : undefined

    return (
      <g
        key={elem.id}
        id={elem.id}
        transform={transform}
        opacity={elem.style.opacity ?? 1.0}
        className={!isThumbnail ? 'cursor-move' : undefined}
        onMouseDown={(e) => {
          if (!isThumbnail) {
            e.stopPropagation()
            setSelectedElementId(elem.id)
            onElementMouseDown?.(elem.id, e)
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
            {/* Background / border for text box */}
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

        {elem.type === 'table' && (
          <g id={`table-${elem.id}`} className="table-container">
            {((elem as any).cells || []).flatMap((row: any[], rIdx: number) => {
              const cW = elem.width / Math.max((elem as any).cols || 1, 1)
              const cH = elem.height / Math.max((elem as any).rows || 1, 1)
              return row.map((cell: any, cIdx: number) => {
                const cx = elem.x + cIdx * cW
                const cy = elem.y + rIdx * cH
                const fill = cell.style?.fill?.color || themeColors.surface.panel
                const stroke = cell.style?.border?.color || themeColors.border.strong
                const strokeW = cell.style?.border?.width || 1
                return (
                  <g key={`cell-${rIdx}-${cIdx}`}>
                    <rect x={cx} y={cy} width={cW} height={cH} fill={fill} stroke={stroke} strokeWidth={strokeW} />
                    {cell.text_content && renderTextContent(cell.text_content, cx, cy, cW, cH, 6)}
                  </g>
                )
              })
            })}
          </g>
        )}

        {elem.type === 'group' && (
          <g id={`group-content-${elem.id}`} className="group-container">
            {(elem as GroupElementIR).children?.map((child) => renderElementNode(child))}
          </g>
        )}

        {/* Precision Architectural Selection Frame & Interactive Resize Handles */}
        {isSelected && !isThumbnail && (
          <g>
            {/* Continuous Hairline Bounding Stroke */}
            <rect
              x={elem.x - 1.5}
              y={elem.y - 1.5}
              width={elem.width + 3}
              height={elem.height + 3}
              fill="none"
              stroke={themeColors.content.primary}
              strokeWidth="1.2"
              strokeDasharray="4,2"
              pointerEvents="none"
            />

            {/* 8 Interactive Resize Handles */}
            {[
              { id: 'nw', cx: elem.x, cy: elem.y, cursor: 'nwse-resize' },
              { id: 'n', cx: elem.x + elem.width / 2, cy: elem.y, cursor: 'ns-resize' },
              { id: 'ne', cx: elem.x + elem.width, cy: elem.y, cursor: 'nesw-resize' },
              { id: 'e', cx: elem.x + elem.width, cy: elem.y + elem.height / 2, cursor: 'ew-resize' },
              { id: 'se', cx: elem.x + elem.width, cy: elem.y + elem.height, cursor: 'nwse-resize' },
              { id: 's', cx: elem.x + elem.width / 2, cy: elem.y + elem.height, cursor: 'ns-resize' },
              { id: 'sw', cx: elem.x, cy: elem.y + elem.height, cursor: 'nesw-resize' },
              { id: 'w', cx: elem.x, cy: elem.y + elem.height / 2, cursor: 'ew-resize' },
            ].map((h) => (
              <rect
                key={h.id}
                x={h.cx - 4.5}
                y={h.cy - 4.5}
                width={9}
                height={9}
                rx={2}
                fill={themeColors.surface.panel}
                stroke={themeColors.content.primary}
                strokeWidth={1.5}
                style={{ cursor: h.cursor }}
                onMouseDown={(e) => {
                  e.stopPropagation()
                  onResizeHandleMouseDown?.(h.id as any, e)
                }}
              />
            ))}

            {/* Dimension & Coordinates Tooltip Pill */}
            <g pointerEvents="none">
              <rect
                x={elem.x}
                y={elem.y - 24}
                width={112}
                height={18}
                rx={4}
                fill={themeColors.surface.inverted}
                stroke={themeColors.surface.invertedHover}
                strokeWidth={1}
              />
              <text
                x={elem.x + 56}
                y={elem.y - 11}
                textAnchor="middle"
                fill={themeColors.content.inverted}
                fontSize="10px"
                fontFamily="'JetBrains Mono', 'SF Mono', Consolas, monospace"
                fontWeight="500"
              >
                {Math.round(elem.width)} × {Math.round(elem.height)} px
              </text>
            </g>
          </g>
        )}
      </g>
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
      {slide.elements.map((elem) => renderElementNode(elem))}

      {/* Active snapping smart guides (slide-coordinate overlay, pointer-events none) */}
      {!isThumbnail && <AlignmentGuides guides={alignmentGuides} />}
    </svg>
  )
}
