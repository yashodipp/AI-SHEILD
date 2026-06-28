from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def _format_percent_value(value: object) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)

    if 0 <= numeric <= 1:
        numeric *= 100
    return f"{int(round(numeric))}%"


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _normalize_report_metric_line(label: str, value: str) -> str:
    return f"{label}{_format_percent_value(value)}"


def get_normalized_report_content(file_path: str, file_format: str) -> bytes:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)

    raw_bytes = path.read_bytes()
    if file_format == "csv":
        raw_text = raw_bytes.decode("utf-8", errors="ignore")
        updated_text = raw_text
        for field in ("fake_probability", "real_probability", "confidence"):
            updated_text = re.sub(
                rf"(^({field}),)([0-9]*\.?[0-9]+)\s*$",
                lambda match: f"{match.group(1)}{_format_percent_value(match.group(3))}",
                updated_text,
                flags=re.MULTILINE,
            )
        return updated_text.encode("utf-8")

    raw_text = raw_bytes.decode("latin-1", errors="ignore")
    updated_text = raw_text
    for label in ("Fake Probability: ", "Real Probability: ", "Confidence: "):
        updated_text = re.sub(
            rf"(\({re.escape(label)})([0-9]*\.?[0-9]+)(\) Tj)",
            lambda match: f"{match.group(1)}{_format_percent_value(match.group(2))}{match.group(3)}",
            updated_text,
        )
    return updated_text.encode("latin-1")


def normalize_legacy_report_file(file_path: str, file_format: str) -> None:
    path = Path(file_path)
    if not path.exists():
        return

    normalized = get_normalized_report_content(file_path, file_format)
    if normalized != path.read_bytes():
        path.write_bytes(normalized)


def normalize_all_reports(reports_dir: str) -> None:
    report_root = Path(reports_dir)
    if not report_root.exists():
        return

    for pdf_path in report_root.glob("*.pdf"):
        normalize_legacy_report_file(str(pdf_path), "pdf")

    for csv_path in report_root.glob("*.csv"):
        normalize_legacy_report_file(str(csv_path), "csv")


def _build_pdf(lines: list[str]) -> bytes:
    content_lines = ["BT", "/F1 12 Tf", "72 770 Td"]
    for index, line in enumerate(lines):
        if index:
            content_lines.append("0 -18 Td")
        content_lines.append(f"({_escape_pdf_text(line)}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", "replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
    ]

    document = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{index} 0 obj\n".encode("ascii"))
        document.extend(obj)
        document.extend(b"\nendobj\n")

    xref_start = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

    document.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode("ascii"))
    document.extend(f"startxref\n{xref_start}\n%%EOF\n".encode("ascii"))
    return bytes(document)


def create_report_bundle(result: dict[str, object], reports_dir: str) -> dict[str, str]:
    report_id = uuid4().hex
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    analysis_type = str(result["analysis_type"])
    report_name = f"{analysis_type}_analysis_{timestamp}"
    report_root = Path(reports_dir)
    report_root.mkdir(parents=True, exist_ok=True)

    csv_path = report_root / f"{report_id}.csv"
    pdf_path = report_root / f"{report_id}.pdf"

    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["field", "value"])
        writer.writerow(["analysis_id", result["analysis_id"]])
        writer.writerow(["analysis_type", analysis_type])
        writer.writerow(["status", result["status"]])
        writer.writerow(["fake_probability", _format_percent_value(result["fake_probability"])])
        writer.writerow(["real_probability", _format_percent_value(result["real_probability"])])
        writer.writerow(["confidence", _format_percent_value(result["confidence"])])
        writer.writerow(["summary", result["summary"]])

    pdf_lines = [
        "AI Shield Analysis Report",
        f"Analysis ID: {result['analysis_id']}",
        f"Type: {analysis_type}",
        f"Status: {result['status']}",
        f"Fake Probability: {_format_percent_value(result['fake_probability'])}",
        f"Real Probability: {_format_percent_value(result['real_probability'])}",
        f"Confidence: {_format_percent_value(result['confidence'])}",
        f"Summary: {result['summary']}",
    ]
    pdf_path.write_bytes(_build_pdf(pdf_lines))

    return {
        "id": report_id,
        "report_name": report_name,
        "analysis_type": analysis_type,
        "pdf_path": str(pdf_path),
        "csv_path": str(csv_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
