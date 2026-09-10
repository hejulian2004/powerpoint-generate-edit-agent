import type {
  ConnectorElementIR,
  ElementIR,
  GroupElementIR,
  PresentationIR,
  ShapeElementIR,
  SlideIR,
  TextElementIR
} from '../types/ppt'

export const makeText = (
  id: string,
  text = 'hello',
  x = 0,
  y = 0,
  width = 200,
  height = 60
): TextElementIR => ({
  id,
  type: 'text',
  x,
  y,
  width,
  height,
  rotation: 0,
  z_index: 0,
  style: { opacity: 1, radius: 0, padding: 8 },
  text_content: {
    plain_text: text,
    paragraphs: [{ align: 'left', line_spacing: 1.25, runs: [{ text }] }]
  },
  children: []
})

export const makeShape = (
  id: string,
  x: number,
  y: number,
  width = 100,
  height = 50
): ShapeElementIR => ({
  id,
  type: 'shape',
  shape_type: 'roundRect',
  x,
  y,
  width,
  height,
  rotation: 0,
  z_index: 0,
  style: { opacity: 1, radius: 2, padding: 8 },
  children: []
})

export const makeConnector = (
  id: string,
  startX: number,
  startY: number,
  endX: number,
  endY: number
): ConnectorElementIR => ({
  id,
  type: 'connector',
  x: Math.min(startX, endX),
  y: Math.min(startY, endY),
  width: Math.max(Math.abs(endX - startX), 1),
  height: Math.max(Math.abs(endY - startY), 1),
  rotation: 0,
  z_index: 0,
  start_x: startX,
  start_y: startY,
  end_x: endX,
  end_y: endY,
  arrow_start: 'none',
  arrow_end: 'triangle',
  line_type: 'straight',
  style: { opacity: 1, radius: 0, padding: 8 },
  children: []
})

export const makeGroup = (
  id: string,
  x: number,
  y: number,
  width: number,
  height: number,
  children: ElementIR[]
): GroupElementIR => ({
  id,
  type: 'group',
  x,
  y,
  width,
  height,
  rotation: 0,
  z_index: 0,
  style: { opacity: 1, radius: 0, padding: 8 },
  children
})

export const makeSlide = (elements: ElementIR[], id = 'slide_1'): SlideIR => ({
  id,
  slide_num: 1,
  title: 'Test Slide',
  width: 1280,
  height: 720,
  background: { type: 'solid', color: '#FFFFFF', alpha: 1 },
  elements
})

export const makePresentation = (
  slides: SlideIR[] = [makeSlide([])],
  version = 1
): PresentationIR => ({
  id: 'pres_1',
  title: 'Test Deck',
  width: 1280,
  height: 720,
  theme: {},
  slides,
  active_slide_id: slides[0]?.id,
  version,
  assets: {}
})
