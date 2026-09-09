import React from 'react'
import type { SnapGuide } from '../editor/snapping/types'
import { guideStrokeStyle } from '../editor/snapping/guideStyle'

interface Props {
  guides: SnapGuide[]
}

/**
 * Renders active snapping alignment guides in slide coordinate space so they
 * stay aligned at any zoom. `vectorEffect="non-scaling-stroke"` keeps the
 * on-screen stroke width constant across 50% / 100% / 200% zoom (the dashed
 * gap pattern still scales with zoom, being expressed in SVG user units).
 * Slide-center guides render solid; element guides render dashed.
 * Guides never intercept pointer events.
 */
export const AlignmentGuides: React.FC<Props> = ({ guides }) => {
  if (guides.length === 0) return null

  return (
    <g className="smart-guides" pointerEvents="none">
      {guides.map((guide, idx) => {
        const style = guideStrokeStyle(guide.kind)
        return guide.axis === 'x' ? (
          <line
            key={idx}
            x1={guide.position}
            y1={guide.start}
            x2={guide.position}
            y2={guide.end}
            stroke={style.stroke}
            strokeWidth={style.strokeWidth}
            strokeDasharray={style.strokeDasharray}
            vectorEffect="non-scaling-stroke"
          />
        ) : (
          <line
            key={idx}
            x1={guide.start}
            y1={guide.position}
            x2={guide.end}
            y2={guide.position}
            stroke={style.stroke}
            strokeWidth={style.strokeWidth}
            strokeDasharray={style.strokeDasharray}
            vectorEffect="non-scaling-stroke"
          />
        )
      })}
    </g>
  )
}