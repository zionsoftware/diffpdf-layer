import csv
from dataclasses import asdict
import io
import json
import os
from pathlib import Path

from .model import Report, Result, Status


def to_json(report):
    return json.dumps(asdict(report), ensure_ascii=False, indent=2)


def from_json(text):
    data = json.loads(text)
    data["results"] = [Result(**{**r, "status": Status(r["status"])}) for r in data["results"]]
    return Report(**data)


def to_text(report):
    lines = ["PDFレイヤー同一性検証結果", f"総合: {report.status}", "一致は対応範囲内の構造比較の結果です。業務上の承認判定ではありません。", "入力順:"]
    lines += [f"{i}. {p}" for i, p in enumerate(report.files, 1)]
    lines += [f"構成検査: {'正常' if report.configuration_ok else 'エラー (内容比較なし)'}"]
    lines += report.errors
    for row in report.results:
        lines += ["", f"{row.left} ↔ {row.right}", f"{row.component}: {row.status}", row.detail]
    return "\n".join(lines) + "\n"


def csv_cell(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def to_csv(report):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["左ファイル", "右ファイル", "対象", "判定", "詳細"])
    writer.writerow(["", "", "総合", report.status, "対応範囲内の構造比較"])
    for error in report.errors:
        writer.writerow(["", "", "構成検査", Status.UNKNOWN, csv_cell(error)])
    for row in report.results:
        writer.writerow([csv_cell(v) for v in (row.left, row.right, row.component, row.status, row.detail)])
    return stream.getvalue()


def save_report(report, destination):
    dest = Path(destination).resolve()
    if dest.suffix.lower() not in {".txt", ".csv", ".json"}:
        raise ValueError("保存先の拡張子は .txt / .csv / .json にしてください")
    for source in report.files:
        src = Path(source).resolve()
        if os.path.normcase(str(dest)) == os.path.normcase(str(src)) or (dest.exists() and src.exists() and os.path.samefile(dest, src)):
            raise ValueError("入力 PDF への上書きは禁止です")
    content = to_csv(report) if dest.suffix.lower() == ".csv" else to_json(report) if dest.suffix.lower() == ".json" else to_text(report)
    dest.write_text(content, encoding="utf-8-sig" if dest.suffix.lower() == ".csv" else "utf-8")
