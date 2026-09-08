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
  theme_color?: string
}

export interface BorderStyle {
  color?: string
  width: number
  style: 'solid' | 'dashed' | 'dotted' | 'none'
  alpha: number
  theme_color?: string
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
  highlight?: string
  theme_color?: string
}

export interface RunIR {
  text: string
  font?: FontIR
  hyperlink?: string
}

export interface ParagraphIR {
  align: 'left' | 'center' | 'right' | 'justify'
  vertical_align?: 'top' | 'middle' | 'bottom'
  line_spacing: number
  space_before?: number
  space_after?: number
  bullet?: string
  indent_level?: number
  margin_left?: number
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

export interface TransformIR {
  x: number
  y: number
  width: number
  height: number
  rotation: number
  flip_h?: boolean
  flip_v?: boolean
  scale_x?: number
  scale_y?: number
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
  transform?: TransformIR
  z_index: number
  locked?: boolean
  style: ElementStyleIR
  children?: ElementIR[]
}

export interface ShapeElementIR extends BaseElementIR {
  type: 'shape'
  shape_type: string
  text_content?: TextContentIR
  flip_h?: boolean
  flip_v?: boolean
  adjust_values?: Record<string, number>
  custom_geometry?: string
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
  start_shape_id?: string
  end_shape_id?: string
  start_site_index?: number
  end_site_index?: number
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

export interface GroupElementIR extends BaseElementIR {
  type: 'group'
  children: ElementIR[]
}

export type ElementIR =
  | ShapeElementIR
  | TextElementIR
  | ConnectorElementIR
  | ImageElementIR
  | TableElementIR
  | GroupElementIR

export interface SlideIR {
  id: string
  slide_num: number
  title?: string
  width: number
  height: number
  background: FillStyle
  elements: ElementIR[]
  notes?: string
  master?: Record<string, any>
  theme?: Record<string, any>
  theme_ref?: string
  layout_name?: string
}

export interface PresentationIR {
  id: string
  title: string
  width: number
  height: number
  theme: Record<string, any>
  master?: Record<string, any>
  slides: SlideIR[]
  active_slide_id?: string
  version: number
  assets: Record<string, string>
  asset_metadata?: Record<string, any>
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
