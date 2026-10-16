import csv
from dataclasses import asdict
import io
import json
import os
from pathlib import Path

from .model import BODY, AuthorInfo, Report, Result, Status

AUTHOR_LABEL = "注釈の作成者名（PDF記録値）"
AUTHOR_NOTE = "作成者名は実際の操作ユーザーや最終編集者を証明する情報ではありません。"


def to_json(report):
    data = asdict(report)
    data.update(schema_version=3, reference=report.files[0] if report.files else None, targets=report.files[1:])
    return json.dumps(data, ensure_ascii=False, indent=2)


def from_json(text):
    data = json.loads(text)
    version = data.pop("schema_version", None)
    if version not in {2, 3}:
        raise ValueError("未対応の比較レポート形式です")
    reference = data.pop("reference")
    targets = data.pop("targets")
    if reference != (data["files"][0] if data["files"] else None) or targets != data["files"][1:]:
        raise ValueError("基準PDFと入力順の情報が一致しません")
    results = []
    for raw in data["results"]:
        if raw["component"] == "合成順序":
            if version == 2:
                continue
            raise ValueError("廃止された比較項目を含むレポートです")
        row = dict(raw)
        if version == 2:
            # The old judgment may have depended on /T or object order. Do
            # not present it as a judgment made under the current contract.
            old_status = row["status"]
            row["status"] = Status.UNKNOWN
            row["detail"] = f"旧形式の保存結果です。元PDFで再比較してください (旧判定: {old_status})。\n" + row.get("detail", "")
            if row["component"] != BODY:
                info = AuthorInfo(complete=False, group_present=None, errors=["旧JSONには作成者集計がありません"])
                row.update(reference_authors=info, target_authors=info, authors_changed=None)
        else:
            for key in ("reference_authors", "target_authors"):
                value = row.get(key)
                if value is not None:
                    required = {"counts", "unset_count", "unreadable_count", "complete", "group_present", "errors"}
                    if set(value) != required or not isinstance(value["counts"], dict) or not isinstance(value["complete"], bool):
                        raise ValueError("作成者集計の形式が不完全です")
                    if any(not isinstance(k, str) or not k or type(v) is not int or v <= 0 for k, v in value["counts"].items()):
                        raise ValueError("作成者ごとの件数が不正です")
                    if any(type(value[k]) is not int or value[k] < 0 for k in ("unset_count", "unreadable_count")) or (value["unreadable_count"] and value["complete"]):
                        raise ValueError("作成者集計の完全性または件数が不正です")
                    if (value["group_present"] is not None and type(value["group_present"]) is not bool) or not isinstance(value["errors"], list) or any(not isinstance(e, str) for e in value["errors"]):
                        raise ValueError("作成者集計のグループ・エラー情報が不正です")
                    if value["complete"] and (value["errors"] or value["group_present"] is None):
                        raise ValueError("不完全な作成者集計を完全とは扱えません")
                    if value["group_present"] is False and (value["counts"] or value["unset_count"] or value["unreadable_count"]):
                        raise ValueError("存在しないグループに作成者件数があります")
                    row[key] = AuthorInfo(**value)
            if row["component"] != BODY:
                left, right = row.get("reference_authors"), row.get("target_authors")
                if left is None or right is None:
                    raise ValueError("作成者集計の情報が不完全です")
                changed = row.get("authors_changed")
                expected = (left.counts, left.unset_count) != (right.counts, right.unset_count) if left.complete and right.complete else None
                if type(changed) is not type(expected) or changed != expected:
                    raise ValueError("作成者名の変更情報と集計が一致しません")
        row["status"] = Status(row["status"])
        results.append(Result(**row))
    data["results"] = results
    if version == 2:
        data["errors"].append("旧schema_version=2の結果は、新仕様で元PDFを再比較する必要があります。")
    return Report(**data)


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
    lines = [f"基準: {row.left}", f"比較: {row.right}", f"対象: {row.component}", f"内容判定: {row.status}", "", row.detail or fallback]
    if row.component != BODY:
        lines += ["", AUTHOR_LABEL, "基準PDF:", author_summary(row.reference_authors), "比較対象PDF:", author_summary(row.target_authors), author_change_text(row), AUTHOR_NOTE]
    return "\n".join(lines)


def to_text(report):
    lines = ["PDFグループ別比較結果", "一致は対応範囲内の構造比較です。フォントのみ変更した一致は字幅・見た目の完全一致を保証しません。", "入力順:"]
    lines += [f"{i}. {'基準PDF' if i == 1 else '比較対象'}: {p}" for i, p in enumerate(report.files, 1)]
    lines += report.errors
    for row in report.results:
        lines += ["", row_details(row)]
    return "\n".join(lines) + "\n"


def csv_cell(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def to_csv(report):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["基準PDF", "比較対象PDF", "対象", "内容判定", "詳細", "基準PDF " + AUTHOR_LABEL, "比較対象PDF " + AUTHOR_LABEL, "作成者名の構成の変更"])
    for error in report.errors:
        writer.writerow(["", "", "ファイル解析", Status.UNKNOWN, csv_cell(error), "", "", ""])
    for row in report.results:
        left = author_summary(row.reference_authors) if row.component != BODY else "対象外"
        right = author_summary(row.target_authors) if row.component != BODY else "対象外"
        writer.writerow([csv_cell(v) for v in (row.left, row.right, row.component, row.status, row.detail, left, right, author_change_text(row))])
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
