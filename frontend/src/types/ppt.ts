export interface GradientStop {
  position: number
  color: string
  alpha: number
}

export interface GradientFill {
  type: 'linear' | 'radial'
  angle: number
  stops: GradientStop[]
}

export interface FillStyle {
  type: 'none' | 'solid' | 'gradient'
  color?: string
  alpha: number
  gradient?: GradientFill
}

export interface BorderStyle {
  color?: string
  width: number
  style: 'solid' | 'dashed' | 'dotted' | 'none'
  alpha: number
}

export interface ShadowStyle {
  enabled: boolean
  color: string
  blur: number
  angle: number
  distance: number
  alpha: number
}

export interface FontIR {
  name: string
  size: number
  color: string
  bold?: boolean
  italic?: boolean
  underline?: boolean
  strikethrough?: boolean
}

export interface RunIR {
  text: string
  font?: FontIR
}

export interface ParagraphIR {
  align: 'left' | 'center' | 'right' | 'justify'
  vertical_align?: 'top' | 'middle' | 'bottom'
  line_spacing: number
  space_before?: number
  space_after?: number
  runs: RunIR[]
}

export interface TextContentIR {
  paragraphs: ParagraphIR[]
  plain_text?: string
}

export interface ElementStyleIR {
  fill?: FillStyle
  border?: BorderStyle
  shadow?: ShadowStyle
  opacity: number
  radius: number
  padding: number
}

export interface BaseElementIR {
  id: string
  type: string
  name?: string
  x: number
  y: number
  width: number
  height: number
  rotation: number
  z_index: number
  locked?: boolean
  style: ElementStyleIR
}

export interface ShapeElementIR extends BaseElementIR {
  type: 'shape'
  shape_type: string
  text_content?: TextContentIR
}

export interface TextElementIR extends BaseElementIR {
  type: 'text'
  text_content: TextContentIR
}

export interface ConnectorElementIR extends BaseElementIR {
  type: 'connector'
  start_x: number
  start_y: number
  end_x: number
  end_y: number
  arrow_start: 'none' | 'triangle' | 'stealth' | 'oval'
  arrow_end: 'none' | 'triangle' | 'stealth' | 'oval'
  line_type: 'straight' | 'elbow' | 'curved'
}

export interface ImageElementIR extends BaseElementIR {
  type: 'image'
  src: string
  asset_id?: string
  alt_text?: string
}

export interface TableCellIR {
  row: number
  col: number
  row_span?: number
  col_span?: number
  text_content: TextContentIR
  style?: ElementStyleIR
}

export interface TableElementIR extends BaseElementIR {
  type: 'table'
  rows: number
  cols: number
  cells: TableCellIR[][]
}

export type ElementIR = ShapeElementIR | TextElementIR | ConnectorElementIR | ImageElementIR | TableElementIR

export interface SlideIR {
  id: string
  slide_num: number
  title?: string
  width: number
  height: number
  background: FillStyle
  elements: ElementIR[]
  notes?: string
}

export interface PresentationIR {
  id: string
  title: string
  width: number
  height: number
  theme: Record<string, any>
  slides: SlideIR[]
  active_slide_id?: string
  version: number
  assets: Record<string, string>
}

export interface PatchRecord {
  id: string
  timestamp: number
  action: string
  description: string
  slide_id?: string
  element_id?: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  toolCalls?: Array<{
    tool: string
    arguments: any
    result?: any
  }>
  visionCritique?: string
  isStreaming?: boolean
}
