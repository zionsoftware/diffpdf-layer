import csv
import io
import json
import os
from pathlib import Path
import tempfile
import unicodedata

from .model import BODY, UNLAYERED, Status, layer_key
from .serialization import from_json, to_json

AUTHOR_LABEL = "注釈の作成者名（PDF記録値）"
AUTHOR_NOTE = "作成者名は実際の操作ユーザーや最終編集者を証明する情報ではありません。"


def author_summary(info):
    if info is None:
        return "未取得（集計の完全性を確認できません）"
    lines = [] if info.complete else ["集計未完了：以下は取得できた範囲です。"]
    if info.group_present is False:
        lines.append("このPDFに該当グループなし")
    elif not info.counts and not info.unset_count and not info.unreadable_count:
        lines.append("注釈なし" if info.complete else "取得できた作成者情報なし")
    for name, count in sorted(info.counts.items()):
        lines.append(f"{json.dumps(name, ensure_ascii=False)}: {count}件")
    if info.unset_count:
        lines.append(f"作成者名未設定: {info.unset_count}件")
    if info.unreadable_count:
        lines.append(f"作成者名取得不能: {info.unreadable_count}件")
    lines.extend(info.errors)
    return "\n".join(lines)


def author_change_text(row):
    if row.component == BODY:
        return "対象外"
    if row.authors_changed is None:
        return "作成者名の構成の変更有無は判定不能（集計未完了・未取得）"
    return "注釈の作成者名の構成に変更があります。" if row.authors_changed else "注釈の作成者名の構成に変更はありません。"


def row_details(row):
    fallback = "対応範囲内で同一です。" if row.status == Status.MATCH else ""
    lines = [f"比較元 ({row.left_role}): {row.left}", f"比較先 ({row.right_role}): {row.right}", f"対象: {row.component}", f"内容判定: {row.status}", "", row.detail or fallback]
    if row.component != BODY:
        lines += ["", AUTHOR_LABEL, "比較元PDF:", author_summary(row.reference_authors), "比較先PDF:", author_summary(row.target_authors), author_change_text(row), AUTHOR_NOTE]
    return "\n".join(lines)


def to_text(report):
    lines = ["PDFレイヤー比較結果", "一致は対応範囲内の構造比較です。業務判定は変更を許容するレイヤーを除いて判定します。",
             f"基準PDF: {report.reference}", "", "入力ファイル情報:"]
    for info in report.file_info:
        lines += [f"{info.role}: {info.path}", f"  SHA-256 (先頭12桁): {info.short_hash}",
                  f"  最終更新日時: {info.modified_at or '取得不能'}", f"  容量: {info.size_bytes if info.size_bytes is not None else '取得不能'} bytes"]
        if info.error:
            lines.append(f"  エラー: {info.error}")
    if not report.file_info:
        lines += report.files
    lines += report.errors
    lines += ["", "基準PDFとの比較（基準欄は自己比較を行いません）:", text_table(matrix_headers(report), matrix_rows(report))]
    lines += ["", "全組合せの結果:", text_table(["比較元", "比較先", "PDF全体", "業務判定"],
              [[p.left_role, p.right_role, p.overall, p.business] for p in report.pairs])]
    for pair in report.pairs:
        lines += ["", pair_details(report, pair)]
    if not report.pairs:
        for row in report.results:
            lines += ["", row_details(row)]
    return "\n".join(lines) + "\n"


def find_pair(report, role):
    reference_role = report.roles[-1] if report.roles else ""
    return next((p for p in report.pairs if (p.left_role, p.right_role) == (role, reference_role)), None)


def find_row(report, pair, component):
    return next((r for r in report.results if (r.left_role, r.right_role, r.component) ==
                 (pair.left_role, pair.right_role, component)), None)


def matrix_headers(report):
    return ["比較項目", *[f"{role}〈基準〉" if i == len(report.roles) - 1 else role for i, role in enumerate(report.roles)]]


def matrix_rows(report):
    components = ["PDF全体", BODY, UNLAYERED, *(layer_key(n) for n in report.layer_names), "業務判定",
                  *(layer_key(n) for n in report.extra_names)]
    rows = []
    for component in components:
        cells = []
        for index, role in enumerate(report.roles):
            if index == len(report.roles) - 1:
                cells.append("―" if component == "業務判定" else "基準" if component not in [layer_key(n) for n in report.extra_names] else "該当なし")
                continue
            pair = find_pair(report, role)
            if pair is None:
                cells.append("UNVERIFIABLE" if component == "業務判定" else Status.UNKNOWN)
            elif component == "PDF全体":
                cells.append(pair.overall)
            elif component == "業務判定":
                cells.append(pair.business)
            else:
                row = find_row(report, pair, component)
                cells.append(row.status if row else "双方に該当なし")
        label = component.removeprefix("レイヤー: ")
        if component in [layer_key(n) for n in report.extra_names]:
            label += "（基準PDF外）"
        rows.append([label, *cells])
    return rows


def pair_details(report, pair):
    lines = [f"{pair.left_role} → {pair.right_role}", f"比較元: {pair.left}", f"比較先: {pair.right}",
             f"PDF全体: {pair.overall}", f"業務判定: {pair.business}",
             "一致必須: " + "、".join(pair.required), "差異許容: " + "、".join(pair.allowed)]
    lines += pair.reasons
    for row in report.results:
        if (row.left_role, row.right_role) == (pair.left_role, pair.right_role):
            lines += ["", row_details(row)]
    return "\n".join(lines)


def text_table(headers, rows):
    def clean(value):
        return str(value).replace("\r", " ").replace("\n", " / ").replace("\t", " ")
    def width(value):
        return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in value)
    values = [[clean(v) for v in row] for row in [headers, *rows]]
    sizes = [max(width(row[i]) for row in values) for i in range(len(headers))]
    lines = [" | ".join(v + " " * (sizes[i] - width(v)) for i, v in enumerate(row)) for row in values]
    lines.insert(1, "-+-".join("-" * size for size in sizes))
    return "\n".join(lines)


def csv_cell(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def to_csv(report):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["役割", "フルパス", "SHA-256 (先頭12桁)", "最終更新日時", "容量 (bytes)", "取得エラー"])
    for info in report.file_info:
        writer.writerow([csv_cell(v) for v in (info.role, info.path, info.short_hash, info.modified_at, info.size_bytes, info.error)])
    writer.writerow([])
    writer.writerow(matrix_headers(report))
    for row in matrix_rows(report):
        writer.writerow([csv_cell(v) for v in row])
    writer.writerow([])
    writer.writerow(["比較元役割", "比較先役割", "PDF全体", "業務判定", "理由"])
    for pair in report.pairs:
        writer.writerow([csv_cell(v) for v in (pair.left_role, pair.right_role, pair.overall, pair.business, "\n".join(pair.reasons))])
    writer.writerow([])
    writer.writerow(["比較元PDF", "比較先PDF", "対象", "内容判定", "詳細", "比較元PDF " + AUTHOR_LABEL, "比較先PDF " + AUTHOR_LABEL, "作成者名の構成の変更", "比較元役割", "比較先役割"])
    for error in report.errors:
        writer.writerow(["", "", "ファイル解析", Status.UNKNOWN, csv_cell(error), "", "", ""])
    for row in report.results:
        left = author_summary(row.reference_authors) if row.component != BODY else "対象外"
        right = author_summary(row.target_authors) if row.component != BODY else "対象外"
        writer.writerow([csv_cell(v) for v in (row.left, row.right, row.component, row.status, row.detail, left, right, author_change_text(row), row.left_role, row.right_role)])
    return stream.getvalue()


def save_report(report, destination):
    dest = Path(destination).resolve()
    if dest.suffix.lower() not in {".txt", ".pdf", ".csv", ".json"}:
        raise ValueError("保存先の拡張子は .txt / .pdf / .csv / .json にしてください")
    def protect_input():
        for source in report.files:
            src = Path(source).resolve()
            if os.path.normcase(str(dest)) == os.path.normcase(str(src)) or (dest.exists() and src.exists() and os.path.samefile(dest, src)):
                raise ValueError("入力 PDF への上書きは禁止です")
    protect_input()
    if dest.suffix.lower() == ".pdf":
        from .pdf_report import to_pdf
        content = to_pdf(report)
    else:
        text = to_csv(report) if dest.suffix.lower() == ".csv" else to_json(report) if dest.suffix.lower() == ".json" else to_text(report)
        content = text.encode("utf-8-sig" if dest.suffix.lower() == ".csv" else "utf-8")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=dest.parent, prefix=".cmp-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        protect_input()
        os.replace(temporary, dest)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
