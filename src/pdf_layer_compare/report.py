import csv
from dataclasses import asdict
import io
import json
import os
from pathlib import Path

from .model import Report, Result, Status


def to_json(report):
    data = asdict(report)
    data.update(schema_version=2, reference=report.files[0] if report.files else None, targets=report.files[1:])
    return json.dumps(data, ensure_ascii=False, indent=2)


def from_json(text):
    data = json.loads(text)
    if data.pop("schema_version", None) != 2:
        raise ValueError("未対応の比較レポート形式です")
    reference = data.pop("reference")
    targets = data.pop("targets")
    if reference != (data["files"][0] if data["files"] else None) or targets != data["files"][1:]:
        raise ValueError("基準PDFと入力順の情報が一致しません")
    data["results"] = [Result(**{**r, "status": Status(r["status"])}) for r in data["results"]]
    return Report(**data)


def to_text(report):
    lines = ["PDFグループ別比較結果", "一致は対応範囲内の構造比較です。フォントのみ変更した一致は字幅・見た目の完全一致を保証しません。", "入力順:"]
    lines += [f"{i}. {'基準PDF' if i == 1 else '比較対象'}: {p}" for i, p in enumerate(report.files, 1)]
    lines += report.errors
    for row in report.results:
        lines += ["", f"基準: {row.left}\n比較: {row.right}", f"{row.component}: {row.status}", row.detail]
    return "\n".join(lines) + "\n"


def csv_cell(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def to_csv(report):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["基準PDF", "比較対象PDF", "対象", "判定", "詳細"])
    for error in report.errors:
        writer.writerow(["", "", "ファイル解析", Status.UNKNOWN, csv_cell(error)])
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
