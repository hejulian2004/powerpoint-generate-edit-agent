"""Programmatic generator for PR6 benchmark PPTX decks."""

import io
import base64
from pathlib import Path
from PIL import Image
from backend.ir.models import (
    PresentationIR, SlideIR, ShapeElementIR, TextElementIR,
    ConnectorElementIR, ImageElementIR, GroupElementIR,
    ElementStyleIR, FillStyle, BorderStyle, ShadowStyle,
    TextContentIR, ParagraphIR, RunIR, FontIR
)
from backend.ir.converter import export_pptx


def _create_synthetic_image_b64(width=100, height=100, color=(59, 130, 246)) -> str:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def build_academic_deck() -> PresentationIR:
    pres = PresentationIR(title="Academic Research Presentation")
    slide = SlideIR(id="academic_slide_1", slide_num=1, title="Quantum Computing Advances")

    # 1. Slide Title
    title = TextElementIR(
        id="elem_acad_title",
        name="Slide Title",
        x=80.0,
        y=40.0,
        width=800.0,
        height=60.0,
        text_content=TextContentIR.from_plain_text(
            "Quantum Error Correction in Neutral Atom Arrays",
            font=FontIR(name="Segoe UI", size=28.0, bold=True, color="#0F172A")
        )
    )
    slide.add_element(title)

    # 2. Subtitle
    subtitle = TextElementIR(
        id="elem_acad_sub",
        name="Subtitle",
        x=80.0,
        y=105.0,
        width=800.0,
        height=35.0,
        text_content=TextContentIR.from_plain_text(
            "Experimental Implementation and Scalability Analysis",
            font=FontIR(name="Segoe UI", size=18.0, color="#475569")
        )
    )
    slide.add_element(subtitle)

    # 3. Two-column Layout: Left column
    left_col = TextElementIR(
        id="elem_acad_left_col",
        name="Left Column Text",
        x=80.0,
        y=170.0,
        width=500.0,
        height=280.0,
        text_content=TextContentIR.from_plain_text(
            "Fault-tolerant quantum computing requires quantum error correction (QEC)\n"
            "to achieve logical failure rates below physical error thresholds.\n\n"
            "• Scalable architecture with dual-species Rydberg atoms\n"
            "• Real-time syndrome decoding with FPGA pipeline\n"
            "• Demonstrated transversal non-Clifford gate teleportation",
            font=FontIR(name="Segoe UI", size=15.0, color="#1E293B")
        )
    )
    slide.add_element(left_col)

    # 4. Right column: Callout Card
    card_bg = ShapeElementIR(
        id="elem_acad_card_bg",
        name="Callout Card",
        shape_type="roundRect",
        x=620.0,
        y=170.0,
        width=300.0,
        height=260.0,
        style=ElementStyleIR(
            fill=FillStyle(type="solid", color="#F8FAFC"),
            border=BorderStyle(style="solid", color="#CBD5E1", width=1.5),
            radius=8.0
        )
    )
    slide.add_element(card_bg)

    card_text = TextElementIR(
        id="elem_acad_card_txt",
        name="Callout Text",
        x=640.0,
        y=190.0,
        width=260.0,
        height=220.0,
        text_content=TextContentIR.from_plain_text(
            "Key Breakthrough:\n\n"
            "Physical qubit coherence times extended by 3.8x under dynamic dynamical decoupling.",
            font=FontIR(name="Segoe UI", size=14.0, color="#0369A1")
        )
    )
    slide.add_element(card_text)

    # 5. Footnote
    footer = TextElementIR(
        id="elem_acad_footer",
        name="Footer Note",
        x=80.0,
        y=660.0,
        width=800.0,
        height=30.0,
        text_content=TextContentIR.from_plain_text(
            "Nature Physics 2026; DOI: 10.1038/s41567-026-0001",
            font=FontIR(name="Segoe UI", size=10.0, color="#94A3B8")
        )
    )
    slide.add_element(footer)

    pres.slides.append(slide)
    return pres


def build_business_deck() -> PresentationIR:
    pres = PresentationIR(title="Quarterly Business Review")
    slide = SlideIR(id="biz_slide_1", slide_num=1, title="Q3 Performance Highlights")

    # Header banner
    banner = ShapeElementIR(
        id="elem_biz_banner",
        name="Top Header Banner",
        shape_type="rect",
        x=0.0,
        y=0.0,
        width=1280.0,
        height=16.0,
        style=ElementStyleIR(
            fill=FillStyle(type="solid", color="#2563EB")
        )
    )
    slide.add_element(banner)

    # Title & Subtitle
    title = TextElementIR(
        id="elem_biz_title",
        name="Slide Title",
        x=70.0,
        y=50.0,
        width=700.0,
        height=50.0,
        text_content=TextContentIR.from_plain_text(
            "Q3 2026 Executive Financial Summary",
            font=FontIR(name="Segoe UI", size=26.0, bold=True, color="#0F172A")
        )
    )
    slide.add_element(title)

    # 3 Metric Cards
    metrics_data = [
        ("elem_biz_m1", "$14.8M", "ARR Growth", 70.0, "#2563EB"),
        ("elem_biz_m2", "142%", "Net Dollar Retention", 440.0, "#059669"),
        ("elem_biz_m3", "99.98%", "Platform Availability", 810.0, "#7C3AED"),
    ]

    for eid, stat, label, x_pos, accent_color in metrics_data:
        card = ShapeElementIR(
            id=f"{eid}_card",
            name=f"Metric Card {stat}",
            shape_type="roundRect",
            x=x_pos,
            y=130.0,
            width=340.0,
            height=140.0,
            style=ElementStyleIR(
                fill=FillStyle(type="solid", color="#FFFFFF"),
                border=BorderStyle(style="solid", color=accent_color, width=2.0),
                radius=10.0
            )
        )
        slide.add_element(card)

        stat_txt = TextElementIR(
            id=f"{eid}_stat",
            name=f"Metric Value {stat}",
            x=x_pos + 20.0,
            y=145.0,
            width=300.0,
            height=60.0,
            text_content=TextContentIR.from_plain_text(
                stat,
                font=FontIR(name="Segoe UI", size=32.0, bold=True, color=accent_color)
            )
        )
        slide.add_element(stat_txt)

        lbl_txt = TextElementIR(
            id=f"{eid}_lbl",
            name=f"Metric Label {label}",
            x=x_pos + 20.0,
            y=215.0,
            width=300.0,
            height=30.0,
            text_content=TextContentIR.from_plain_text(
                label,
                font=FontIR(name="Segoe UI", size=14.0, color="#64748B")
            )
        )
        slide.add_element(lbl_txt)

    # Bullet points body
    body = TextElementIR(
        id="elem_biz_body",
        name="Key Drivers",
        x=70.0,
        y=320.0,
        width=1000.0,
        height=220.0,
        text_content=TextContentIR.from_plain_text(
            "Key Strategic Drivers:\n\n"
            "• Enterprise expansion accelerated, adding 24 Fortune 500 customers.\n"
            "• Gross margins expanded to 81.2% driven by inference cost optimizations.\n"
            "• Positive operating cash flow achieved two quarters ahead of plan.",
            font=FontIR(name="Segoe UI", size=16.0, color="#1E293B")
        )
    )
    slide.add_element(body)

    pres.slides.append(slide)
    return pres


def build_dashboard_deck() -> PresentationIR:
    pres = PresentationIR(title="Operations Dashboard")
    slide = SlideIR(id="dash_slide_1", slide_num=1, title="Infrastructure Health Dashboard")

    title = TextElementIR(
        id="elem_dash_title",
        name="Dashboard Header",
        x=60.0,
        y=40.0,
        width=600.0,
        height=50.0,
        text_content=TextContentIR.from_plain_text(
            "Global Infrastructure Mesh Topology",
            font=FontIR(name="Segoe UI", size=24.0, bold=True, color="#0F172A")
        )
    )
    slide.add_element(title)

    # 4-card grid: 2x2
    cards = [
        ("elem_dcard_1", "Cluster Alpha (US-East)", "Optimal", 60.0, 120.0, "#10B981"),
        ("elem_dcard_2", "Cluster Beta (EU-West)", "Active", 500.0, 120.0, "#3B82F6"),
        ("elem_dcard_3", "Cluster Gamma (AP-North)", "Syncing", 60.0, 320.0, "#F59E0B"),
        ("elem_dcard_4", "Cluster Delta (SA-East)", "Optimal", 500.0, 320.0, "#10B981"),
    ]

    for cid, name, status, x, y, status_color in cards:
        card = ShapeElementIR(
            id=cid,
            name=name,
            shape_type="roundRect",
            x=x,
            y=y,
            width=380.0,
            height=150.0,
            style=ElementStyleIR(
                fill=FillStyle(type="solid", color="#F8FAFC"),
                border=BorderStyle(style="solid", color="#E2E8F0", width=1.5),
                radius=8.0
            )
        )
        slide.add_element(card)

        txt = TextElementIR(
            id=f"{cid}_txt",
            name=f"{name} Label",
            x=x + 20.0,
            y=y + 20.0,
            width=340.0,
            height=40.0,
            text_content=TextContentIR.from_plain_text(
                name,
                font=FontIR(name="Segoe UI", size=16.0, bold=True, color="#1E293B")
            )
        )
        slide.add_element(txt)

        badge = ShapeElementIR(
            id=f"{cid}_badge",
            name=f"Status Badge",
            shape_type="roundRect",
            x=x + 20.0,
            y=y + 80.0,
            width=90.0,
            height=30.0,
            style=ElementStyleIR(
                fill=FillStyle(type="solid", color=status_color),
                radius=15.0
            )
        )
        slide.add_element(badge)

    # Connector between Card 1 and Card 2
    conn = ConnectorElementIR(
        id="elem_dconn_1_2",
        name="Mesh Link 1-2",
        x=440.0,
        y=195.0,
        width=60.0,
        height=1.0,
        start_x=440.0,
        start_y=195.0,
        end_x=500.0,
        end_y=195.0,
        style=ElementStyleIR(
            border=BorderStyle(style="dashed", color="#64748B", width=2.0)
        )
    )
    slide.add_element(conn)

    pres.slides.append(slide)
    return pres


def build_image_heavy_deck() -> PresentationIR:
    pres = PresentationIR(title="Product Showcase Deck")
    slide = SlideIR(id="img_slide_1", slide_num=1, title="Hardware Architecture")

    title = TextElementIR(
        id="elem_img_title",
        name="Slide Title",
        x=80.0,
        y=40.0,
        width=700.0,
        height=50.0,
        text_content=TextContentIR.from_plain_text(
            "Autonomous Edge Sensor Module",
            font=FontIR(name="Segoe UI", size=24.0, bold=True, color="#0F172A")
        )
    )
    slide.add_element(title)

    # Image 1 (Primary visual)
    b64_img1 = _create_synthetic_image_b64(240, 180, color=(37, 99, 235))
    img1 = ImageElementIR(
        id="elem_img_hero",
        name="Primary Sensor Module Photo",
        x=80.0,
        y=120.0,
        width=360.0,
        height=270.0,
        src=b64_img1
    )
    slide.add_element(img1)

    # Image 2 (Secondary visual)
    b64_img2 = _create_synthetic_image_b64(240, 180, color=(16, 185, 129))
    img2 = ImageElementIR(
        id="elem_img_pcb",
        name="PCB Layout Detail",
        x=480.0,
        y=120.0,
        width=360.0,
        height=270.0,
        src=b64_img2
    )
    slide.add_element(img2)

    # Captions
    caption1 = TextElementIR(
        id="elem_img_cap1",
        name="Caption 1",
        x=80.0,
        y=405.0,
        width=360.0,
        height=40.0,
        text_content=TextContentIR.from_plain_text(
            "Figure 1: IP68 Enclosed Sensor Unit",
            font=FontIR(name="Segoe UI", size=12.0, color="#64748B")
        )
    )
    slide.add_element(caption1)

    caption2 = TextElementIR(
        id="elem_img_cap2",
        name="Caption 2",
        x=480.0,
        y=405.0,
        width=360.0,
        height=40.0,
        text_content=TextContentIR.from_plain_text(
            "Figure 2: Custom RISC-V SoC Architecture",
            font=FontIR(name="Segoe UI", size=12.0, color="#64748B")
        )
    )
    slide.add_element(caption2)

    pres.slides.append(slide)
    return pres


def build_complex_group_deck() -> PresentationIR:
    pres = PresentationIR(title="Hierarchical Group Diagram")
    slide = SlideIR(id="grp_slide_1", slide_num=1, title="Distributed System Hierarchy")

    title = TextElementIR(
        id="elem_grp_title",
        name="Slide Title",
        x=80.0,
        y=40.0,
        width=700.0,
        height=50.0,
        text_content=TextContentIR.from_plain_text(
            "Microservices Fabric Cluster",
            font=FontIR(name="Segoe UI", size=24.0, bold=True, color="#0F172A")
        )
    )
    slide.add_element(title)

    # Nested Group 1
    c1 = ShapeElementIR(
        id="elem_leaf_shape1",
        name="Leaf Node 1",
        shape_type="roundRect",
        x=100.0,
        y=150.0,
        width=150.0,
        height=80.0,
        style=ElementStyleIR(fill=FillStyle(type="solid", color="#38BDF8"), radius=6.0)
    )
    c2 = ShapeElementIR(
        id="elem_leaf_shape2",
        name="Leaf Node 2",
        shape_type="roundRect",
        x=280.0,
        y=150.0,
        width=150.0,
        height=80.0,
        style=ElementStyleIR(fill=FillStyle(type="solid", color="#818CF8"), radius=6.0)
    )

    inner_grp = GroupElementIR(
        id="elem_inner_grp",
        name="Inner Worker Group",
        x=100.0,
        y=150.0,
        width=330.0,
        height=80.0,
        children=[c1, c2]
    )

    master_box = ShapeElementIR(
        id="elem_master_box",
        name="Coordinator Node",
        shape_type="rect",
        x=100.0,
        y=270.0,
        width=330.0,
        height=70.0,
        style=ElementStyleIR(fill=FillStyle(type="solid", color="#0F172A"))
    )

    outer_grp = GroupElementIR(
        id="elem_outer_cluster_grp",
        name="Fabric Outer Cluster",
        x=100.0,
        y=150.0,
        width=330.0,
        height=190.0,
        children=[inner_grp, master_box]
    )
    slide.add_element(outer_grp)

    pres.slides.append(slide)
    return pres


def generate_all_decks(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    decks = {
        "academic.pptx": build_academic_deck(),
        "business.pptx": build_business_deck(),
        "dashboard.pptx": build_dashboard_deck(),
        "image_heavy.pptx": build_image_heavy_deck(),
        "complex_group.pptx": build_complex_group_deck(),
    }
    for filename, pres in decks.items():
        out_path = output_dir / filename
        export_pptx(pres, str(out_path))
        print(f"Generated benchmark deck: {out_path}")


if __name__ == "__main__":
    out = Path(__file__).resolve().parent
    generate_all_decks(out)
