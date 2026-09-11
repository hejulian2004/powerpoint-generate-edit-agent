// Backward-compatible barrel for presentation types.
//
// The canonical IR contract is generated from the backend schema and lives in
// `presentation-ir.generated.ts` (the source of truth). Editor/UI-only types
// live in `editor.ts`. New code should import from those modules directly; this
// barrel exists so existing imports keep working and to make the split explicit.

export type {
  GradientStop,
  GradientFill,
  FillStyle,
  BorderStyle,
  ShadowStyle,
  FontIR,
  RunIR,
  ParagraphIR,
  TextContentIR,
  ElementStyleIR,
  TransformIR,
  ShapeElementIR,
  TextElementIR,
  ConnectorElementIR,
  ImageElementIR,
  TableCellIR,
  TableElementIR,
  GroupElementIR,
  ElementIR,
  SlideIR,
  PresentationIR
} from './presentation-ir.generated'

export type {
  PatchRecord,
  VisualQualityScore,
  VisualRemediationEvent,
  ContextUsageData,
  ChatMessage,
  MutationStatus,
  PreviewUpdateEvent,
  PPTEditorState
} from './editor'
