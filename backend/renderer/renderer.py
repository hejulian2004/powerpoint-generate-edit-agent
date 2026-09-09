"""Core PPTX Renderer Engine (PR11).

Orchestrates the conversion of DeckLayoutSpec into OOXML PowerPoint presentation.
Strictly enforces architectural separation:
  - Input must be DeckLayoutSpec
  - Coordinates and sizes are deterministic
  - Layout is not recomputed
  - python-pptx is accessed solely via PPTXBuilder
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from ..layout.schema import DeckLayoutSpec, ElementType
from .assets import AssetResolver
from .pptx_builder import PPTXBuilder
from .schema import RenderConfig
from .theme import AcademicTheme


def render_pptx(
    deck_layout: DeckLayoutSpec,
    output_path: Union[str, Path],
    asset_resolver: Optional[AssetResolver] = None,
    theme: Optional[AcademicTheme] = None,
    validate_fidelity: bool = True,
    config: Optional[RenderConfig] = None,
) -> str:
    """Render a DeckLayoutSpec into a PowerPoint presentation file (.pptx).

    Args:
        deck_layout: Fully calculated DeckLayoutSpec geometry from PR10 Layout Engine.
        output_path: Target filesystem path to save the .pptx presentation.
        asset_resolver: Optional asset resolver for figures and tables.
        theme: Optional AcademicTheme; defaults to academic_modern.
        validate_fidelity: Whether to execute automated fidelity inspection on the output.
        config: Optional RenderConfig options.

    Returns:
        The string path of the generated .pptx file.

    Raises:
        TypeError: If input is not a DeckLayoutSpec (e.g. attempting to pass SlideSpec directly).
        RuntimeError: If fidelity validation fails in strict mode.
    """
    # 1. Strict Boundary Guard
    if not isinstance(deck_layout, DeckLayoutSpec):
        raise TypeError(
            f"render_pptx requires a DeckLayoutSpec, but received {type(deck_layout).__name__}. "
            f"Direct SlideSpec -> PPTX rendering is strictly prohibited to preserve layout decoupling."
        )

    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # 2. Setup environment
    active_config = config or RenderConfig(validate_fidelity=validate_fidelity)
    active_theme = theme or AcademicTheme()
    active_resolver = asset_resolver or AssetResolver()
    builder = PPTXBuilder(canvas=deck_layout.canvas)

    # Set document core properties
    core_props = builder.prs.core_properties
    core_props.title = deck_layout.title
    if active_config.custom_properties:
        for prop_name, prop_val in active_config.custom_properties.items():
            if hasattr(core_props, prop_name) and isinstance(prop_val, str):
                setattr(core_props, prop_name, prop_val)

    # 3. Render Slides in Order
    for slide_spec in deck_layout.slides:
        builder.add_slide(slide_spec)

        # Sort elements by z_index so backgrounds/containers render before text/badges
        sorted_elements = sorted(slide_spec.elements, key=lambda el: el.z_index)

        for element in sorted_elements:
            el_type = element.element_type

            if el_type == ElementType.CONTAINER:
                builder.add_shape(element, active_theme)

            elif el_type == ElementType.BADGE:
                builder.add_shape(element, active_theme)

            elif el_type == ElementType.TEXT:
                builder.add_text(element, active_theme)

            elif el_type == ElementType.FIGURE:
                caption = ""
                if isinstance(element.content, dict):
                    figure_id = (
                        element.content.get("source_figure_id")
                        or element.source_block_id
                        or element.element_id
                    )
                    caption = element.content.get("caption", "")
                elif isinstance(element.content, str) and element.content:
                    figure_id = element.content
                else:
                    figure_id = element.source_block_id or element.element_id

                try:
                    img_path = active_resolver.resolve_figure(
                        figure_id=figure_id,
                        caption_hint=caption,
                        allow_synthetic=active_config.allow_synthetic_assets,
                    )
                    builder.add_image(element, img_path, active_theme)
                except FileNotFoundError:
                    # Missing raster asset on disk: render explicit placeholder shape without fabricating fake images
                    builder.add_shape(element, active_theme)

            elif el_type == ElementType.TABLE:
                content_payload: Dict[str, Any] = {}
                if isinstance(element.content, dict):
                    content_payload = element.content
                    table_id = (
                        content_payload.get("source_table_id")
                        or element.source_block_id
                        or element.element_id
                    )
                elif isinstance(element.content, str) and element.content:
                    table_id = element.content
                else:
                    table_id = element.source_block_id or element.element_id

                try:
                    table_data = active_resolver.resolve_table(
                        table_id=table_id,
                        content_payload=content_payload,
                    )
                    builder.add_table(element, table_data, active_theme)
                except FileNotFoundError:
                    # Missing table data: render explicit placeholder shape without fabricating fake table structures
                    builder.add_shape(element, active_theme)

    # 4. Save Presentation
    saved_path = builder.save(out_file)

    # 5. Post-Render Fidelity Validation
    should_validate = validate_fidelity and active_config.validate_fidelity
    if should_validate:
        from .validators import validate_pptx_fidelity

        report = validate_pptx_fidelity(deck_layout, saved_path)
        if not report.is_valid:
            errors_str = "\n".join(report.errors)
            raise RuntimeError(f"Fidelity validation failed for {out_file}:\n{errors_str}")

    return str(saved_path)
