"""Unit tests for element direct editing, image radius clipPath, and font color styling."""

from backend.ir.models import PresentationIR, SlideIR, ShapeElementIR, ImageElementIR, TextElementIR
from backend.ir.patch import HistoryManager
from backend.agent.tools import update_element, add_shape, add_text
from backend.ir.svg_renderer import SVGRenderer


def test_update_element_initializes_text_content_for_empty_shape():
    """Verify that updating typography on a shape without text initializes text_content."""
    pres = PresentationIR()
    history = HistoryManager()
    slide = SlideIR(id="slide_1", slide_num=1, title="Test Slide")
    pres.slides.append(slide)

    # Add shape with empty text
    res = add_shape(pres, history, slide.id, shape_type="roundRect", text="")
    assert res["success"] is True
    elem_id = res["element_id"]

    elem = slide.get_element(elem_id)
    assert elem.text_content is None

    # Update font color, size and text
    up_res = update_element(
        pres, history, elem_id, slide.id,
        font_color="#3B82F6",
        font_size=24.0,
        text="新卡片文字"
    )
    assert up_res["success"] is True
    updated_elem = slide.get_element(elem_id)
    assert updated_elem.text_content is not None
    assert updated_elem.text_content.plain_text == "新卡片文字"
    assert updated_elem.text_content.paragraphs[0].runs[0].font.color == "#3B82F6"
    assert updated_elem.text_content.paragraphs[0].runs[0].font.size == 24.0


def test_update_element_radius_and_dimensions():
    """Verify that updating radius to 0 (right-angle) and resizing works."""
    pres = PresentationIR()
    history = HistoryManager()
    slide = SlideIR(id="slide_2", slide_num=1, title="Test Slide 2")
    pres.slides.append(slide)

    res = add_shape(pres, history, slide.id, shape_type="roundRect", radius=12.0)
    elem_id = res["element_id"]

    # Update radius to 0.0
    up_res = update_element(pres, history, elem_id, slide.id, radius=0.0, width=500.0, height=300.0)
    assert up_res["success"] is True
    elem = slide.get_element(elem_id)
    assert elem.style.radius == 0.0
    assert elem.width == 500.0
    assert elem.height == 300.0


def test_svg_renderer_image_clip_path():
    """Verify SVGRenderer produces clipPath when an image has a border radius."""
    pres = PresentationIR()
    slide = SlideIR(id="slide_3", slide_num=1, title="Test Image Slide")
    pres.slides.append(slide)
    img = ImageElementIR(
        id="img_123",
        src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        x=50, y=50, width=200, height=150
    )
    img.style.radius = 8.0
    slide.add_element(img)

    svg = SVGRenderer.render_slide(slide)
    assert 'clip-path="url(#clip_img_123)"' in svg
    assert '<clipPath id="clip_img_123">' in svg
    assert 'rx="8.0"' in svg
