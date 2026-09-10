import React, { useState, useRef, useEffect } from 'react'
import type {
  SlideIR, ElementIR, ShapeElementIR, TextElementIR,
  ConnectorElementIR, ImageElementIR, GroupElementIR, FillStyle, BorderStyle
} from '../types/ppt'
import { usePPTStore } from '../store/usePPTStore'
import { themeColors } from '../theme/tokens'
import { AlignmentGuides } from './AlignmentGuides'
import type { SnapGuide } from '../editor/snapping/types'
import { canResize, getBounds, unionBounds } from '../editor/geometry/adapter'

interface Props {
  slide: SlideIR
  isThumbnail?: boolean
  onElementMouseDown?: (elemId: string, e: React.MouseEvent) => void
  onElementDoubleClick?: (elemId: string, e: React.MouseEvent) => void
  onResizeHandleMouseDown?: (handle: 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w', e: React.MouseEvent) => void
  onBackgroundMouseDown?: (e: React.MouseEvent) => void
  alignmentGuides?: SnapGuide[]
  selectionBox?: { x: number; y: number; width: number; height: number } | null
  editingElementId?: string | null
  onCommitInlineEdit?: (elemId: string, text: string) => void
  onCancelInlineEdit?: () => void
  draftMap?: Map<string, ElementIR> | null
}

interface InlineTextEditorProps {
  element: ElementIR
  onCommit: (text: string) => void
  onCancel: () => void
}

export const getPlainText = (tc: any): string => {
  if (!tc) return ''
  if (typeof tc.plain_text === 'string' && tc.plain_text) return tc.plain_text
  if (Array.isArray(tc.paragraphs)) {
    return tc.paragraphs
      .map((p: any) =>
        Array.isArray(p.runs)
          ? p.runs.map((r: any) => (r && typeof r.text === 'string' ? r.text : '')).join('')
          : ''
      )
      .join('\n')
  }
  return ''
}

const InlineTextEditor: React.FC<InlineTextEditorProps> = ({ element, onCommit, onCancel }) => {
  const tc = (element as any).text_content
  const initialText = getPlainText(tc)
  const [val, setVal] = useState(initialText)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const firstPara = tc?.paragraphs?.[0]
  const firstRun = firstPara?.runs?.[0]
  const fontSize = firstRun?.font?.size ?? (element.type === 'text' ? 24 : 16)
  const fontColor = firstRun?.font?.color ?? themeColors.content.primary
  const fontFamily = firstRun?.font?.name ?? 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
  const isBold = firstRun?.font?.bold ?? false
  const isItalic = firstRun?.font?.italic ?? false
  const align = firstPara?.align ?? 'left'

  useEffect(() => {
    const timer = setTimeout(() => {
      if (textareaRef.current) {
        textareaRef.current.focus()
        textareaRef.current.select()
      }
    }, 20)
    return () => clearTimeout(timer)
  }, [])

  const handleBlur = () => {
    onCommit(val)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    e.stopPropagation()
    if (e.key === 'Escape') {
      onCancel()
    } else if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      onCommit(val)
    }
  }

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        alignItems: 'flex-start',
        boxSizing: 'border-box',
        padding: `${element.style?.padding ?? 6}px`,
        pointerEvents: 'auto'
      }}
      onClick={(e) => {
        e.stopPropagation()
        textareaRef.current?.focus()
      }}
      onMouseDown={(e) => e.stopPropagation()}
      onDoubleClick={(e) => e.stopPropagation()}
    >
      <textarea
        ref={textareaRef}
        value={val}
        autoFocus
        tabIndex={0}
        onChange={(e) => setVal(e.target.value)}
        onBlur={handleBlur}
        onKeyDown={handleKeyDown}
        placeholder="输入文本内容..."
        style={{
          width: '100%',
          height: '100%',
          resize: 'none',
          outline: 'none',
          border: '1.5px solid #3B82F6',
          borderRadius: `${typeof element.style?.radius === 'number' ? Math.max(0, element.style.radius - 2) : 2}px`,
          backgroundColor: 'rgba(255, 255, 255, 0.96)',
          color: fontColor,
          fontFamily: fontFamily,
          fontSize: `${fontSize}px`,
          fontWeight: isBold ? 600 : 400,
          fontStyle: isItalic ? 'italic' : 'normal',
          textAlign: align as any,
          lineHeight: 1.25,
          boxShadow: '0 0 0 3px rgba(59, 130, 246, 0.25)',
          padding: '4px',
          pointerEvents: 'auto',
          userSelect: 'text',
          cursor: 'text'
        }}
      />
    </div>
  )
}

export const SVGRendererComponent: React.FC<Props> = ({
  slide,
  isThumbnail = false,
  onElementMouseDown,
  onElementDoubleClick,
  onResizeHandleMouseDown,
  onBackgroundMouseDown,
  alignmentGuides = [],
  selectionBox = null,
  editingElementId = null,
  onCommitInlineEdit,
  onCancelInlineEdit,
  draftMap = null
}) => {
  const { selectedElementIds, selectionScope, setSelectedElementId, toggleElementSelection } = usePPTStore()

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

    const collectClipPaths = (elements: ElementIR[]) => {
      elements.forEach((elem) => {
        if (elem.type === 'image') {
          const rx = typeof elem.style?.radius === 'number' ? elem.style.radius : 0
          defs.push(
            <clipPath key={`clip-${elem.id}`} id={`clip-${elem.id}`}>
              <rect x={elem.x} y={elem.y} width={elem.width} height={elem.height} rx={rx} ry={rx} />
            </clipPath>
          )
        }
        if (elem.type === 'group' && (elem as GroupElementIR).children) {
          collectClipPaths((elem as GroupElementIR).children)
        }
      })
    }
    collectClipPaths(slide.elements)

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
      const rx = typeof style.radius === 'number' ? style.radius : 12
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

    // Default rectangle (supports custom radius too)
    const rx = typeof style.radius === 'number' ? style.radius : 0
    return <rect x={x} y={y} width={w} height={h} rx={rx} ry={rx} fill={fill} filter={filter} {...strokeProps} />
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

  const renderElementNode = (elem: ElementIR, ancestors: string[]) => {
    elem = draftMap?.get(elem.id) ?? elem
    const isInteractive = !isThumbnail &&
      ancestors.length === selectionScope.length &&
      ancestors.every((ancestor, index) => ancestor === selectionScope[index])
    const isScopeGroup = elem.type === 'group' && selectionScope[ancestors.length] === elem.id
    const isSelected = !isThumbnail && selectedElementIds.includes(elem.id)
    const isPrimary = !isThumbnail && selectedElementIds.length === 1 && selectedElementIds[0] === elem.id
    const isEditing = !isThumbnail && editingElementId === elem.id
    const transform = elem.rotation ? `rotate(${elem.rotation} ${elem.x + elem.width / 2} ${elem.y + elem.height / 2})` : undefined

    const handleMouseDown = (e: React.MouseEvent) => {
      if (isThumbnail) return
      if (isEditing) {
        e.stopPropagation()
        return
      }
      if (!isInteractive) return
      e.stopPropagation()
      if (e.shiftKey) {
        toggleElementSelection(elem.id)
        return
      }
      setSelectedElementId(elem.id)
      onElementMouseDown?.(elem.id, e)
    }

    return (
      <g
        key={elem.id}
        id={elem.id}
        transform={transform}
        opacity={elem.style.opacity ?? 1.0}
        className={!isThumbnail ? (isEditing ? 'cursor-text' : isInteractive ? 'cursor-move' : undefined) : undefined}
        onMouseDown={handleMouseDown}
        onDoubleClick={(e) => {
          if (isThumbnail || !isInteractive) return
          e.stopPropagation()
          setSelectedElementId(elem.id)
          onElementDoubleClick?.(elem.id, e)
        }}
      >
        {elem.type === 'connector' && renderConnector(elem as ConnectorElementIR)}

        {elem.type === 'image' && (
          <g>
            <image
              href={(elem as ImageElementIR).src}
              x={elem.x}
              y={elem.y}
              width={elem.width}
              height={elem.height}
              preserveAspectRatio="xMidYMid meet"
              clipPath={`url(#clip-${elem.id})`}
              onDragStart={(e) => e.preventDefault()}
              style={{ userSelect: 'none', pointerEvents: 'auto' }}
            />
            {elem.style?.border && elem.style.border.style !== 'none' && elem.style.border.width > 0 && (
              <rect
                x={elem.x}
                y={elem.y}
                width={elem.width}
                height={elem.height}
                rx={typeof elem.style?.radius === 'number' ? elem.style.radius : 0}
                ry={typeof elem.style?.radius === 'number' ? elem.style.radius : 0}
                fill="none"
                pointerEvents="none"
                {...getStrokeProps(elem.style.border)}
              />
            )}
          </g>
        )}

        {elem.type === 'shape' && (
          <>
            {renderShapeGeometry(elem as ShapeElementIR)}
            {isEditing ? (
              <foreignObject
                x={elem.x}
                y={elem.y}
                width={elem.width}
                height={elem.height}
                className="overflow-visible"
                style={{ pointerEvents: 'auto', overflow: 'visible' }}
              >
                <InlineTextEditor
                  element={elem}
                  onCommit={(text) => onCommitInlineEdit?.(elem.id, text)}
                  onCancel={() => onCancelInlineEdit?.()}
                />
              </foreignObject>
            ) : (
              (elem as ShapeElementIR).text_content &&
                renderTextContent(
                  (elem as ShapeElementIR).text_content,
                  elem.x,
                  elem.y,
                  elem.width,
                  elem.height,
                  elem.style.padding
                )
            )}
          </>
        )}

        {elem.type === 'text' && (
          <>
            {/* Always render an interactive hit-testing and background surface */}
            <rect
              x={elem.x}
              y={elem.y}
              width={elem.width}
              height={elem.height}
              rx={typeof elem.style?.radius === 'number' ? elem.style.radius : 0}
              ry={typeof elem.style?.radius === 'number' ? elem.style.radius : 0}
              fill={elem.style.fill?.type !== 'none' ? getFillValue(elem.style.fill, elem.id) : 'transparent'}
              pointerEvents="all"
              {...getStrokeProps(elem.style.border)}
            />
            {isEditing ? (
              <foreignObject
                x={elem.x}
                y={elem.y}
                width={elem.width}
                height={elem.height}
                className="overflow-visible"
                style={{ pointerEvents: 'auto', overflow: 'visible' }}
              >
                <InlineTextEditor
                  element={elem}
                  onCommit={(text) => onCommitInlineEdit?.(elem.id, text)}
                  onCancel={() => onCancelInlineEdit?.()}
                />
              </foreignObject>
            ) : (
              renderTextContent(
                (elem as TextElementIR).text_content,
                elem.x,
                elem.y,
                elem.width,
                elem.height,
                elem.style.padding
              )
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
          <>
            <g
              id={`group-content-${elem.id}`}
              className="group-container"
              style={isScopeGroup ? undefined : { pointerEvents: 'none' }}
            >
              {(elem as GroupElementIR).children?.map((child) =>
                renderElementNode(child, [...ancestors, elem.id])
              )}
            </g>
            {isInteractive && !isScopeGroup && (
              <rect
                x={elem.x}
                y={elem.y}
                width={elem.width}
                height={elem.height}
                fill="transparent"
                pointerEvents="all"
              />
            )}
          </>
        )}

        {/* Precision Architectural Selection Frame & Interactive Resize Handles */}
        {isSelected && !isThumbnail && (() => {
          const bounds = getBounds(elem)
          const showHandles = isPrimary && canResize(elem)
          return (
            <g>
              {/* Continuous Hairline Bounding Stroke */}
              <rect
                x={bounds.x - 1.5}
                y={bounds.y - 1.5}
                width={bounds.width + 3}
                height={bounds.height + 3}
                fill="none"
                stroke={isPrimary ? themeColors.content.primary : '#2563EB'}
                strokeWidth="1.2"
                strokeDasharray="4,2"
                pointerEvents="none"
              />

              {/* 8 Interactive Resize Handles (single selection only) */}
              {showHandles &&
                [
                  { id: 'nw', cx: bounds.x, cy: bounds.y, cursor: 'nwse-resize' },
                  { id: 'n', cx: bounds.x + bounds.width / 2, cy: bounds.y, cursor: 'ns-resize' },
                  { id: 'ne', cx: bounds.x + bounds.width, cy: bounds.y, cursor: 'nesw-resize' },
                  { id: 'e', cx: bounds.x + bounds.width, cy: bounds.y + bounds.height / 2, cursor: 'ew-resize' },
                  { id: 'se', cx: bounds.x + bounds.width, cy: bounds.y + bounds.height, cursor: 'nwse-resize' },
                  { id: 's', cx: bounds.x + bounds.width / 2, cy: bounds.y + bounds.height, cursor: 'ns-resize' },
                  { id: 'sw', cx: bounds.x, cy: bounds.y + bounds.height, cursor: 'nesw-resize' },
                  { id: 'w', cx: bounds.x, cy: bounds.y + bounds.height / 2, cursor: 'ew-resize' },
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
                    onClick={(e) => {
                      e.stopPropagation()
                    }}
                  />
                ))}

              {/* Dimension & Coordinates Tooltip Pill */}
              {isPrimary && (
                <g pointerEvents="none">
                  <rect
                    x={bounds.x}
                    y={bounds.y - 24}
                    width={112}
                    height={18}
                    rx={4}
                    fill={themeColors.surface.inverted}
                    stroke={themeColors.surface.invertedHover}
                    strokeWidth={1}
                  />
                  <text
                    x={bounds.x + 56}
                    y={bounds.y - 11}
                    textAnchor="middle"
                    fill={themeColors.content.inverted}
                    fontSize="10px"
                    fontFamily="'JetBrains Mono', 'SF Mono', Consolas, monospace"
                    fontWeight="500"
                  >
                    {Math.round(bounds.width)} × {Math.round(bounds.height)} px
                  </text>
                </g>
              )}
            </g>
          )
        })()}
      </g>
    )
  }

  const collectSelected = (elements: ElementIR[]): ElementIR[] => {
    const result: ElementIR[] = []
    for (const element of elements) {
      if (selectedElementIds.includes(element.id)) result.push(element)
      if (element.type === 'group') result.push(...collectSelected(element.children))
    }
    return result
  }

  const multiBounds = (() => {
    if (isThumbnail || selectedElementIds.length < 2) return null
    const selected = collectSelected(slide.elements).map((el) => draftMap?.get(el.id) ?? el)
    if (selected.length < 2) return null
    return unionBounds(selected)
  })()

  return (
    <svg
      viewBox={`0 0 ${slide.width} ${slide.height}`}
      className="w-full h-full block"
      xmlns="http://www.w3.org/2000/svg"
    >
      {renderDefs()}

      {/* Background */}
      <rect
        width={slide.width}
        height={slide.height}
        fill={getFillValue(slide.background)}
        onMouseDown={(e) => {
          if (!isThumbnail) {
            e.stopPropagation()
            if (onBackgroundMouseDown) {
              onBackgroundMouseDown(e)
            } else {
              setSelectedElementId(null)
            }
          }
        }}
      />

      {/* Elements in z-index order */}
      {slide.elements.map((elem) => renderElementNode(elem, []))}

      {/* Multi-selection union bounding frame (pointer-events none) */}
      {!isThumbnail && multiBounds && (
        <g pointerEvents="none">
          <rect
            x={multiBounds.x}
            y={multiBounds.y}
            width={multiBounds.width}
            height={multiBounds.height}
            fill="none"
            stroke="#2563EB"
            strokeWidth="1.2"
            strokeDasharray="6,3"
          />
        </g>
      )}

      {/* Drag box-selection marquee (pointer-events none) */}
      {!isThumbnail && selectionBox && (
        <rect
          x={selectionBox.x}
          y={selectionBox.y}
          width={selectionBox.width}
          height={selectionBox.height}
          fill="rgba(59,130,246,0.10)"
          stroke="#3B82F6"
          strokeWidth="1"
          strokeDasharray="4,3"
          pointerEvents="none"
        />
      )}

      {/* Active snapping smart guides (slide-coordinate overlay, pointer-events none) */}
      {!isThumbnail && <AlignmentGuides guides={alignmentGuides} />}
    </svg>
  )
}
