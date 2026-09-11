// AUTO-GENERATED FILE. DO NOT EDIT.
// Source of truth: backend/ir/models.py (via backend.ir.ts_export).
// Regenerate: python -m backend.ir.ts_export

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
  type: 'none' | 'solid' | 'gradient' | 'theme'
  color?: string | null
  alpha: number
  gradient?: GradientFill | null
  theme_color?: string | null
}
export interface BorderStyle {
  color?: string | null
  width: number
  style: 'solid' | 'dashed' | 'dotted' | 'none'
  alpha: number
  theme_color?: string | null
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
  highlight?: string | null
  theme_color?: string | null
}
export interface RunIR {
  text: string
  font?: FontIR | null
  hyperlink?: string | null
}
export interface ParagraphIR {
  align: 'left' | 'center' | 'right' | 'justify'
  vertical_align?: 'top' | 'middle' | 'bottom'
  line_spacing: number
  space_before?: number
  space_after?: number
  bullet?: string | null
  indent_level?: number
  margin_left?: number
  runs: RunIR[]
}
export interface TextContentIR {
  paragraphs: ParagraphIR[]
  plain_text?: string
}
export interface ElementStyleIR {
  fill?: FillStyle | null
  border?: BorderStyle | null
  shadow?: ShadowStyle | null
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
export interface ShapeElementIR {
  id: string
  type: 'shape'
  name?: string | null
  x: number
  y: number
  width: number
  height: number
  rotation: number
  transform?: TransformIR | null
  z_index: number
  locked?: boolean
  style: ElementStyleIR
  children?: (ShapeElementIR | TextElementIR | ConnectorElementIR | ImageElementIR | TableElementIR | GroupElementIR)[]
  source_ref?: string | null
  source_evidence_ids?: string[]
  metadata?: Record<string, any>
  shape_type: string
  text_content?: TextContentIR | null
  flip_h?: boolean
  flip_v?: boolean
  adjust_values?: Record<string, number>
  custom_geometry?: string | null
}
export interface TextElementIR {
  id: string
  type: 'text'
  name?: string | null
  x: number
  y: number
  width: number
  height: number
  rotation: number
  transform?: TransformIR | null
  z_index: number
  locked?: boolean
  style: ElementStyleIR
  children?: (ShapeElementIR | TextElementIR | ConnectorElementIR | ImageElementIR | TableElementIR | GroupElementIR)[]
  source_ref?: string | null
  source_evidence_ids?: string[]
  metadata?: Record<string, any>
  text_content: TextContentIR
}
export interface ConnectorElementIR {
  id: string
  type: 'connector'
  name?: string | null
  x: number
  y: number
  width: number
  height: number
  rotation: number
  transform?: TransformIR | null
  z_index: number
  locked?: boolean
  style: ElementStyleIR
  children?: (ShapeElementIR | TextElementIR | ConnectorElementIR | ImageElementIR | TableElementIR | GroupElementIR)[]
  source_ref?: string | null
  source_evidence_ids?: string[]
  metadata?: Record<string, any>
  start_x: number
  start_y: number
  end_x: number
  end_y: number
  start_shape_id?: string | null
  end_shape_id?: string | null
  start_site_index?: number | null
  end_site_index?: number | null
  arrow_start: 'none' | 'triangle' | 'stealth' | 'oval'
  arrow_end: 'none' | 'triangle' | 'stealth' | 'oval'
  line_type: 'straight' | 'elbow' | 'curved'
}
export interface ImageElementIR {
  id: string
  type: 'image'
  name?: string | null
  x: number
  y: number
  width: number
  height: number
  rotation: number
  transform?: TransformIR | null
  z_index: number
  locked?: boolean
  style: ElementStyleIR
  children?: (ShapeElementIR | TextElementIR | ConnectorElementIR | ImageElementIR | TableElementIR | GroupElementIR)[]
  source_ref?: string | null
  source_evidence_ids?: string[]
  metadata?: Record<string, any>
  src: string
  asset_id?: string | null
  alt_text?: string | null
  crop?: Record<string, number> | null
}
export interface TableCellIR {
  row: number
  col: number
  row_span?: number
  col_span?: number
  text_content: TextContentIR
  style?: ElementStyleIR | null
}
export interface TableElementIR {
  id: string
  type: 'table'
  name?: string | null
  x: number
  y: number
  width: number
  height: number
  rotation: number
  transform?: TransformIR | null
  z_index: number
  locked?: boolean
  style: ElementStyleIR
  children?: (ShapeElementIR | TextElementIR | ConnectorElementIR | ImageElementIR | TableElementIR | GroupElementIR)[]
  source_ref?: string | null
  source_evidence_ids?: string[]
  metadata?: Record<string, any>
  rows: number
  cols: number
  cells: TableCellIR[][]
}
export interface GroupElementIR {
  id: string
  type: 'group'
  name?: string | null
  x: number
  y: number
  width: number
  height: number
  rotation: number
  transform?: TransformIR | null
  z_index: number
  locked?: boolean
  style: ElementStyleIR
  children: (ShapeElementIR | TextElementIR | ConnectorElementIR | ImageElementIR | TableElementIR | GroupElementIR)[]
  source_ref?: string | null
  source_evidence_ids?: string[]
  metadata?: Record<string, any>
}
export type ElementIR = ShapeElementIR | TextElementIR | ConnectorElementIR | ImageElementIR | TableElementIR | GroupElementIR

export interface SlideIR {
  id: string
  slide_num: number
  title?: string | null
  width: number
  height: number
  background: FillStyle
  elements: (ShapeElementIR | TextElementIR | ConnectorElementIR | ImageElementIR | TableElementIR | GroupElementIR)[]
  notes?: string
  master?: Record<string, any> | null
  theme?: Record<string, any> | null
  theme_ref?: string | null
  layout_name?: string | null
}
export interface PresentationIR {
  id: string
  title: string
  width: number
  height: number
  theme: Record<string, any>
  master?: Record<string, any> | null
  slides: SlideIR[]
  active_slide_id?: string | null
  version: number
  assets: Record<string, string>
  asset_metadata?: Record<string, any>
  metadata?: Record<string, any>
  capabilities?: Record<string, boolean>
}
