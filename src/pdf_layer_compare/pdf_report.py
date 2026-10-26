"""Optional, offline ReportLab output. No network access during export."""
from io import BytesIO
import os
from pathlib import Path
from xml.sax.saxutils import escape

from .model import BODY
from .report import (AUTHOR_LABEL, AUTHOR_NOTE, author_change_text, author_summary,
                     matrix_headers, matrix_rows, row_details)


def to_pdf(report):
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle
    except ImportError as exc:
        raise ValueError("PDF出力にはReportLabと依存ライブラリが必要です。requirements-pdf.txt と docs/installation-guide.md のオフライン配置手順を確認してください。TXT出力も利用できます。") from exc

    root = Path(__file__).resolve().parents[2]
    configured = os.environ.get("DIFFPDF_REPORT_FONT")
    candidates = [Path(configured)] if configured else [root / "vendor" / "fonts" / "Japanese.ttf",
                 Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msgothic.ttc"]
    font_path = next((p for p in candidates if p.is_file()), None)
    if font_path is None:
        raise ValueError("日本語フォントが見つかりません。DIFFPDF_REPORT_FONT に日本語TrueTypeフォント (.ttf / .ttc) のフルパスを指定してください。")
    try:
        # A fresh registration also respects a changed font setting in this process.
        pdfmetrics.registerFont(TTFont("DiffPDFJapanese", str(font_path), subfontIndex=0))
    except Exception as exc:
        raise ValueError(f"日本語フォントを読み込めません: {font_path}: {exc}") from exc
    font = "DiffPDFJapanese"
    body = ParagraphStyle("body", fontName=font, fontSize=9, leading=14, wordWrap="CJK", splitLongWords=True,
                          spaceAfter=5, alignment=TA_LEFT)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=12, spaceAfter=0)
    heading = ParagraphStyle("heading", parent=body, fontSize=13, leading=19, spaceBefore=14, spaceAfter=9, keepWithNext=True)
    title = ParagraphStyle("title", parent=heading, fontSize=18, leading=25, spaceBefore=0)
    def para(value, style=body):
        value = str(value)
        value = "".join(c if ord(c) >= 32 or c in "\n\t" else " " for c in value)
        return Paragraph(escape(value).replace("\n", "<br/>"), style)

    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4), leftMargin=36, rightMargin=36,
                            topMargin=36, bottomMargin=36, title="PDFレイヤー比較結果", author="diffpdf-layer")
    story = [para("PDFレイヤー比較結果", title), para(f"基準PDF: {report.reference}"),
             para("一致は対応範囲内の構造比較です。業務判定は、一致必須項目から判定します。基準欄は自己比較を行いません。", small),
             para("入力ファイル情報", heading)]
    for info in report.file_info:
        story += [para(f"{info.role}: {info.path}"),
                  para(f"SHA-256 (先頭12桁): {info.short_hash} / 容量: {info.size_bytes if info.size_bytes is not None else '取得不能'} bytes"),
                  para(f"最終更新日時: {info.modified_at or '取得不能'}")]
        if info.error:
            story.append(para(info.error))
        story.append(Spacer(1, 6))
    for error in report.errors:
        story.append(para(error))

    def table(headers, rows, widths):
        values = [[para(v, small) for v in row] for row in [headers, *rows]]
        result = LongTable(values, colWidths=widths, repeatRows=1, hAlign="LEFT", splitInRow=1)
        result.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dce8f3")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7fa")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#a7b7c5")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        return result

    story += [para("基準PDFとの比較", heading)]
    if report.roles:
        story.append(table(matrix_headers(report), matrix_rows(report), [180, *[(doc.width - 180) / len(report.roles)] * len(report.roles)]))
    story += [para("全組合せの結果", heading)]
    if report.pairs:
        story.append(table(["比較元", "比較先", "PDF全体", "業務判定"],
                           [[p.left_role, p.right_role, p.overall, p.business] for p in report.pairs],
                           [doc.width / 4] * 4))
        story += [Spacer(1, 10), para(AUTHOR_LABEL + ": " + AUTHOR_NOTE, small)]
    for pair in report.pairs:
        story += [para(f"詳細: {pair.left_role} → {pair.right_role}", heading),
                  para(f"PDF全体: {pair.overall} / 業務判定: {pair.business}"),
                  para("一致必須: " + "、".join(pair.required)), para("差異許容: " + "、".join(pair.allowed))]
        for reason in pair.reasons:
            story.append(para(reason))
        details = []
        for row in report.results:
            if (row.left_role, row.right_role) != (pair.left_role, pair.right_role):
                continue
            notes = [row.detail] if row.detail else []
            if row.component != BODY:
                before, after = author_summary(row.reference_authors), author_summary(row.target_authors)
                if before == after == "注釈なし":
                    notes.append("注釈: 双方なし")
                else:
                    notes += ["作成者記録（比較元）: " + before, "作成者記録（比較先）: " + after, author_change_text(row)]
            details.append([row.component, row.status, "\n".join(notes)])
        story.append(table(["比較項目", "内容判定", "詳細・注釈の作成者記録"], details, [150, 75, doc.width - 225]))
    if not report.pairs:
        for row in report.results:
            story.append(para(row_details(row)))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#52677a"))
        canvas.drawString(doc.leftMargin, 20, "diffpdf-layer / 比較結果")
        canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 20, str(document.page))
        canvas.restoreState()
    try:
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
    except Exception as exc:
        raise ValueError(f"PDF出力を作成できません: {exc}") from exc
    return output.getvalue()
