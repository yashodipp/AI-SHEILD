from __future__ import annotations

import importlib.util
import re
from html import escape
from pathlib import Path
from xml.etree import ElementTree as ET

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Frame,
    Image,
    KeepInFrame,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.pdfgen import canvas


BASE_DIR = Path("/Users/yashodip/Documents/New project/AI-Shield/docs")
MODULE_PATH = BASE_DIR / "build_report_80.py"
OUTPUT_PDF = BASE_DIR / "AI_SHIELD_Final_Project_Report_Regenerated.pdf"


def load_module():
    spec = importlib.util.spec_from_file_location("reportmod", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def normalize_html(html: str) -> str:
    html = re.sub(r"<br>", "<br />", html)
    html = re.sub(r"<img\b([^>]*)>", r"<img\1 />", html)
    return html


def parse_page(page_html: str):
    return ET.fromstring(normalize_html(page_html))


def node_classes(node: ET.Element) -> set[str]:
    return set((node.attrib.get("class") or "").split())


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def inline_markup(node: ET.Element) -> str:
    pieces: list[str] = []
    if node.text:
        pieces.append(escape(node.text))
    for child in list(node):
        tag = child.tag.lower()
        if tag == "strong":
            pieces.append(f"<b>{inline_markup(child)}</b>")
        elif tag == "em":
            pieces.append(f"<i>{inline_markup(child)}</i>")
        elif tag == "br":
            pieces.append("<br/>")
        else:
            pieces.append(inline_markup(child))
        if child.tail:
            pieces.append(escape(child.tail))
    return "".join(pieces).strip()


def text_content(node: ET.Element) -> str:
    pieces: list[str] = []
    if node.text and clean_text(node.text):
        pieces.append(clean_text(node.text))
    for child in list(node):
        if child.tag.lower() == "br":
            pieces.append("\n")
        else:
            child_text = text_content(child)
            if child_text:
                pieces.append(child_text)
        if child.tail and clean_text(child.tail):
            pieces.append(clean_text(child.tail))
    joined = " ".join(part for part in pieces if part)
    joined = joined.replace(" \n ", "\n").replace("\n ", "\n").replace(" \n", "\n")
    return clean_text(joined) if "\n" not in joined else joined.strip()


def build_styles():
    base = getSampleStyleSheet()
    styles = {
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Times-Roman",
            fontSize=10,
            leading=13,
            alignment=TA_JUSTIFY,
            spaceAfter=5,
        ),
        "lead": ParagraphStyle(
            "Lead",
            parent=base["BodyText"],
            fontName="Times-Roman",
            fontSize=10.8,
            leading=13.5,
            textColor=colors.HexColor("#36475c"),
            alignment=TA_JUSTIFY,
            spaceAfter=6,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontName="Times-Bold",
            fontSize=24,
            leading=27,
            alignment=TA_LEFT,
            textColor=colors.black,
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName="Times-Bold",
            fontSize=15.5,
            leading=18,
            textColor=colors.HexColor("#0f3158"),
            spaceAfter=5,
        ),
        "h3": ParagraphStyle(
            "H3",
            parent=base["Heading3"],
            fontName="Times-Bold",
            fontSize=12.2,
            leading=14.5,
            textColor=colors.HexColor("#2f3f5b"),
            spaceAfter=4,
        ),
        "chapter_label": ParagraphStyle(
            "ChapterLabel",
            parent=base["BodyText"],
            fontName="Times-Bold",
            fontSize=9.5,
            leading=11.5,
            textColor=colors.HexColor("#355e96"),
            alignment=TA_LEFT,
            spaceAfter=4,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=base["BodyText"],
            fontName="Times-Roman",
            fontSize=10,
            leading=12.5,
            leftIndent=12,
            firstLineIndent=-8,
            spaceAfter=3,
            alignment=TA_JUSTIFY,
        ),
        "caption": ParagraphStyle(
            "Caption",
            parent=base["BodyText"],
            fontName="Times-Italic",
            fontSize=9,
            leading=11,
            textColor=colors.HexColor("#344458"),
            spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontName="Times-Roman",
            fontSize=8.7,
            leading=10.2,
            alignment=TA_LEFT,
            spaceAfter=2,
        ),
        "center": ParagraphStyle(
            "Center",
            parent=base["BodyText"],
            fontName="Times-Roman",
            fontSize=10,
            leading=12.5,
            alignment=TA_CENTER,
            spaceAfter=4,
        ),
        "code": ParagraphStyle(
            "Code",
            parent=base["Code"],
            fontName="Courier",
            fontSize=6.6,
            leading=7.6,
            alignment=TA_LEFT,
            leftIndent=0,
            rightIndent=0,
            spaceAfter=3,
        ),
    }
    return styles


def make_table(data: list[list[str]], body_width: float, header_rows: int = 0, col_widths: list[float] | None = None):
    if not data:
        return None
    col_count = max(len(row) for row in data)
    normalized = [row + [""] * (col_count - len(row)) for row in data]
    if col_widths is None:
        col_width = body_width / max(col_count, 1)
        col_widths = [col_width] * col_count
    tbl = Table(normalized, colWidths=col_widths, repeatRows=header_rows)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#cfd7e2")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("FONTNAME", (0, 0), (-1, -1), "Times-Roman"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.4),
    ]
    if header_rows:
        style.extend(
            [
                ("BACKGROUND", (0, 0), (-1, header_rows - 1), colors.HexColor("#edf4fc")),
                ("FONTNAME", (0, 0), (-1, header_rows - 1), "Times-Bold"),
                ("TEXTCOLOR", (0, 0), (-1, header_rows - 1), colors.HexColor("#173a63")),
            ]
        )
    tbl.setStyle(TableStyle(style))
    return tbl


def make_callout(flowables, body_width):
    box = Table([[flowables]], colWidths=[body_width])
    box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5f9ff")),
                ("BOX", (0, 0), (-1, -1), 0.9, colors.HexColor("#cadbf0")),
                ("LINEBEFORE", (0, 0), (0, 0), 3, colors.HexColor("#2f67a7")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return box


def image_flowable(src: str, body_width: float):
    path = (BASE_DIR / src).resolve()
    if not path.exists():
        return Paragraph(f"Image: {escape(src)}", STYLES["small"])
    img = Image(str(path))
    max_width = body_width
    max_height = 200
    scale = min(max_width / img.imageWidth, max_height / img.imageHeight, 1)
    img.drawWidth = img.imageWidth * scale
    img.drawHeight = img.imageHeight * scale
    return img


def div_grid_as_table(node: ET.Element, body_width: float):
    cls = node_classes(node)
    texts = []
    for child in list(node):
        txt = text_content(child)
        if txt:
            texts.append(txt.replace("\n", "<br/>"))
    if not texts:
        return []
    if "meta-grid" in cls or "signature-grid" in cls:
        cols = 2
    elif "summary-strip" in cls:
        cols = 2
    elif "flow-row" in cls:
        cols = len(texts)
    elif "grid-cards" in cls:
        m = re.search(r"repeat\((\d+)", node.attrib.get("style", ""))
        cols = int(m.group(1)) if m else 2
    else:
        cols = 1
    rows = []
    row = []
    for text in texts:
        markup = escape(text).replace("&lt;br/&gt;", "<br/>").replace("\n", "<br/>")
        row.append(Paragraph(markup, STYLES["small"]))
        if len(row) == cols:
            rows.append(row)
            row = []
    if row:
        row.extend([""] * (cols - len(row)))
        rows.append(row)
    tbl = Table(rows, colWidths=[body_width / cols] * cols)
    tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#c8d8ea")),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d6dfeb")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f9fbff")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return [tbl, Spacer(1, 6)]


def parse_table_wrap(node: ET.Element, body_width: float):
    flows = []
    caption = node.find("./div[@class='table-caption']")
    caption_text = text_content(caption) if caption is not None else ""
    if caption is not None:
        flows.append(Paragraph(escape(caption_text), STYLES["caption"]))
    table_node = node.find("./table")
    if table_node is not None:
        rows = []
        for tr in table_node.findall(".//tr"):
            row = []
            for cell in list(tr):
                row.append(text_content(cell))
            if row:
                rows.append(row)
        col_widths = None
        if caption_text == "Table of Contents":
            col_widths = [0.11 * body_width, 0.71 * body_width, 0.18 * body_width]
        elif caption_text in {"List of Figures", "List of Tables"}:
            col_widths = [0.08 * body_width, 0.17 * body_width, 0.59 * body_width, 0.16 * body_width]
        elif caption_text == "Table 13.1: Project structure and module responsibility map":
            col_widths = [0.22 * body_width, 0.37 * body_width, 0.41 * body_width]
        tbl = make_table(rows, body_width, header_rows=1 if rows else 0, col_widths=col_widths)
        if tbl:
            flows.append(tbl)
            flows.append(Spacer(1, 6))
    note = node.find("./div[@class='table-note']")
    if note is not None:
        flows.append(Paragraph(escape(text_content(note)), STYLES["small"]))
    return flows


def parse_figure(node: ET.Element, body_width: float):
    flows = []
    frame = node.find("./div[@class='figure-frame']")
    if frame is not None:
        img = frame.find(".//img")
        if img is not None and img.attrib.get("src"):
            flows.append(image_flowable(img.attrib["src"], body_width))
        else:
            parts = []
            for div in frame.findall(".//div"):
                txt = text_content(div)
                if txt:
                    parts.append(txt)
            if not parts:
                txt = text_content(frame)
                if txt:
                    parts.append(txt)
            if parts:
                flows.append(Paragraph(escape(" | ".join(parts)), STYLES["small"]))
        flows.append(Spacer(1, 4))
    caption = node.find("./figcaption")
    if caption is not None:
        flows.append(Paragraph(escape(text_content(caption)), STYLES["caption"]))
    note = node.find("./div[@class='figure-note']")
    if note is not None:
        flows.append(Paragraph(escape(text_content(note)), STYLES["small"]))
    return flows


def parse_line_list(node: ET.Element):
    flows = []
    for line in list(node):
        parts = [clean_text("".join(span.itertext())) for span in list(line)]
        if len(parts) >= 2:
            flows.append(Paragraph(f"{escape(parts[0])} ....... {escape(parts[-1])}", STYLES["small"]))
        else:
            txt = text_content(line)
            if txt:
                flows.append(Paragraph(escape(txt), STYLES["small"]))
    flows.append(Spacer(1, 6))
    return flows


def flowables_from_node(node: ET.Element, body_width: float):
    tag = node.tag.lower()
    cls = node_classes(node)
    flows = []

    if tag == "h1":
        return [Paragraph(inline_markup(node), STYLES["h1"])]
    if tag == "h2":
        return [Paragraph(inline_markup(node), STYLES["h2"])]
    if tag == "h3":
        return [Paragraph(inline_markup(node), STYLES["h3"])]
    if tag == "p":
        style = STYLES["lead"] if "lead" in cls else STYLES["body"]
        return [Paragraph(inline_markup(node), style)]
    if tag == "ul":
        for li in node.findall("./li"):
            flows.append(Paragraph("&#8226; " + escape(text_content(li)), STYLES["bullet"]))
        return flows
    if tag == "ol":
        for idx, li in enumerate(node.findall("./li"), start=1):
            flows.append(Paragraph(f"{idx}. " + escape(text_content(li)), STYLES["bullet"]))
        return flows
    if tag == "pre":
        raw_text = "".join(node.itertext()).rstrip()
        return [Preformatted(raw_text, STYLES["code"]), Spacer(1, 4)]
    if tag == "figure":
        return parse_figure(node, body_width)

    if tag == "div":
        if "chapter-banner" in cls:
            for child in list(node):
                child_tag = child.tag.lower()
                if child_tag == "div" and "chapter-label" in node_classes(child):
                    txt = text_content(child)
                    if txt:
                        flows.append(Paragraph(escape(txt), STYLES["chapter_label"]))
                elif child_tag == "h1":
                    flows.append(Paragraph(inline_markup(child), STYLES["h1"]))
                elif child_tag == "p":
                    flows.append(Paragraph(inline_markup(child), STYLES["lead"]))
            return flows
        if "callout" in cls:
            title = node.find("./div[@class='callout-title']")
            body = node.find("./div[@class='callout-body']")
            inner = []
            if title is not None:
                inner.append(Paragraph(f"<b>{escape(text_content(title))}</b>", STYLES["body"]))
            if body is not None:
                inner.append(Paragraph(escape(text_content(body)), STYLES["body"]))
            return [make_callout(inner, body_width), Spacer(1, 6)]
        if "table-wrap" in cls:
            return parse_table_wrap(node, body_width)
        if "figure-frame" in cls:
            return []
        if "index-list" in cls or "toc-list" in cls:
            return parse_line_list(node)
        if cls & {"meta-grid", "signature-grid", "summary-strip", "grid-cards", "flow-row", "layer-stack"}:
            return div_grid_as_table(node, body_width)
        if "cover-title" in cls:
            for child in list(node):
                flows.extend(flowables_from_node(child, body_width))
            return flows
        for child in list(node):
            flows.extend(flowables_from_node(child, body_width))
        return flows

    if tag == "img" and node.attrib.get("src"):
        return [image_flowable(node.attrib["src"], body_width)]

    for child in list(node):
        flows.extend(flowables_from_node(child, body_width))
    return flows


def build_page_flowables(page_root: ET.Element, body_width: float):
    body = page_root.find("./div[@class='page-body']")
    flows = []
    if body is None:
        return flows
    for child in list(body):
        flows.extend(flowables_from_node(child, body_width))
    return flows


def extract_header_section(page_root: ET.Element):
    header = page_root.find("./div[@class='page-header']")
    if header is None:
        return "", ""
    spans = header.findall("./span")
    left = clean_text("".join(spans[0].itertext())) if len(spans) > 0 else ""
    right = clean_text("".join(spans[1].itertext())) if len(spans) > 1 else ""
    return left, right


def draw_header_footer(pdf: canvas.Canvas, left: str, right: str, page_num: int, cover: bool = False):
    page_w, page_h = A4
    margin_x = 14 * mm
    if not cover:
        pdf.setFont("Times-Roman", 9)
        pdf.setFillColor(colors.HexColor("#404040"))
        pdf.drawString(margin_x, page_h - 10 * mm, left)
        right_w = pdf.stringWidth(right, "Times-Roman", 9)
        pdf.drawString(page_w - margin_x - right_w, page_h - 10 * mm, right)
        pdf.setStrokeColor(colors.HexColor("#d8d8d8"))
        pdf.line(margin_x, page_h - 11.8 * mm, page_w - margin_x, page_h - 11.8 * mm)
    pdf.setFont("Times-Roman", 9)
    pdf.setFillColor(colors.HexColor("#444444"))
    pdf.setStrokeColor(colors.HexColor("#d8d8d8"))
    pdf.line(margin_x, 8.8 * mm, page_w - margin_x, 8.8 * mm)
    if cover:
        pdf.drawString(page_w - 22 * mm, 5.5 * mm, f"Page {page_num}")
    else:
        pdf.drawString(margin_x, 5.5 * mm, "Mittal Institute of Technology, Bhopal")
        right_w = pdf.stringWidth(f"Page {page_num}", "Times-Roman", 9)
        pdf.drawString(page_w - margin_x - right_w, 5.5 * mm, f"Page {page_num}")


def export():
    mod = load_module()
    pdf = canvas.Canvas(str(OUTPUT_PDF), pagesize=A4)
    page_w, page_h = A4
    left = 14 * mm
    right = 14 * mm
    top = 17 * mm
    bottom = 25 * mm
    body_width = page_w - left - right
    body_height = page_h - top - bottom

    for idx, page_html in enumerate(mod.pages, start=1):
        root = parse_page(page_html)
        classes = node_classes(root)
        cover = "cover-page" in classes
        header_left, header_right = extract_header_section(root)
        draw_header_footer(pdf, header_left or mod.REPORT_TITLE, header_right, idx, cover=cover)
        frame_top = page_h - (18 * mm if cover else 16 * mm)
        frame = Frame(left, bottom, body_width, frame_top - bottom, showBoundary=0, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        flows = build_page_flowables(root, body_width)
        kit = KeepInFrame(body_width, frame_top - bottom, flows, mode="shrink")
        frame.addFromList([kit], pdf)
        pdf.showPage()
    pdf.save()
    print(f"WROTE={OUTPUT_PDF}")


STYLES = build_styles()


if __name__ == "__main__":
    export()
