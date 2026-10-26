"""Versioned reports used for saved JSON and GUI worker communication."""
from dataclasses import asdict
from itertools import combinations
import json
import re

from .business import summarize
from .model import (BODY, ROLES, AuthorInfo, BusinessStatus, FileInfo,
                    PairSummary, Report, Result, Status)


def to_json(report):
    data = asdict(report)
    data.update(schema_version=4, targets=report.files[:-1])
    return json.dumps(data, ensure_ascii=False, indent=2)


def read_author(value):
    if value is None:
        return None
    required = {"counts", "unset_count", "unreadable_count", "complete", "group_present", "errors"}
    if not isinstance(value, dict) or set(value) != required or not isinstance(value["counts"], dict) or type(value["complete"]) is not bool:
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
    return AuthorInfo(**value)


def from_json(text):
    try:
        return _from_data(json.loads(text))
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("比較レポートの形式が不完全です") from exc


def _from_data(data):
    version = data.pop("schema_version", None)
    if version not in {2, 3, 4}:
        raise ValueError("未対応の比較レポート形式です")
    reference, targets = data.pop("reference"), data.pop("targets")
    files = data["files"]
    if not isinstance(files, list) or any(not isinstance(p, str) for p in files):
        raise ValueError("入力ファイル一覧が不正です")
    expected = (files[-1] if files else "") if version == 4 else (files[0] if files else None)
    if reference != expected or targets != (files[:-1] if version == 4 else files[1:]):
        raise ValueError("基準PDFと入力順の情報が一致しません")
    results = []
    for raw in data["results"]:
        row = dict(raw)
        if row["component"] == "合成順序":
            if version == 2:
                continue
            raise ValueError("廃止された比較項目を含むレポートです")
        if version < 4:
            old_status = row["status"]
            row["status"] = Status.UNKNOWN
            row["detail"] = f"旧形式の保存結果です。元PDFで再比較してください (旧判定: {old_status})。\n" + row.get("detail", "")
        if version == 2 and row["component"] != BODY:
            info = AuthorInfo(complete=False, group_present=None, errors=["旧JSONには作成者集計がありません"])
            row.update(reference_authors=info, target_authors=info, authors_changed=None)
        else:
            for key in ("reference_authors", "target_authors"):
                row[key] = read_author(row.get(key))
            if row["component"] != BODY:
                left, right = row["reference_authors"], row["target_authors"]
                if left is None or right is None:
                    raise ValueError("作成者集計の情報が不完全です")
                expected_change = (left.counts, left.unset_count) != (right.counts, right.unset_count) if left.complete and right.complete else None
                if type(row.get("authors_changed")) is not type(expected_change) or row.get("authors_changed") != expected_change:
                    raise ValueError("作成者名の変更情報と集計が一致しません")
        row["status"] = Status(row["status"])
        results.append(Result(**row))
    data["results"] = results
    if version < 4:
        # Historical results have no role assignments, hashes, or business decisions.
        data = {k: data[k] for k in ("files", "results", "errors")}
        data["errors"].append(f"旧schema_version={version}の結果は、新仕様で元PDFを再比較する必要があります。")
        return Report(**data)
    data["reference"] = reference
    data["file_info"] = [FileInfo(**v) for v in data["file_info"]]
    for info in data["file_info"]:
        if (info.sha256 and not re.fullmatch(r"[0-9a-f]{64}", info.sha256)) or (info.size_bytes is not None and (type(info.size_bytes) is not int or info.size_bytes < 0)):
            raise ValueError("ハッシュまたはバイト数が不正です")
    pairs = []
    for raw in data["pairs"]:
        raw["overall"] = Status(raw["overall"])
        raw["business"] = BusinessStatus(raw["business"])
        pairs.append(PairSummary(**raw))
    data["pairs"] = pairs
    report = Report(**data)
    if report.file_info and report.results and not pairs:
        raise ValueError("比較組合せが不足しています")
    if pairs:
        if report.roles != [r for r in ROLES if r in report.roles] or report.roles[:2] != list(ROLES[:2]) or len(report.roles) != len(files):
            raise ValueError("役割の指定が不正です")
        if len(report.file_info) != len(files) or [(v.path, v.role) for v in report.file_info] != list(zip(files, report.roles)):
            raise ValueError("ファイル情報と役割が一致しません")
        expected_pairs = list(combinations(range(len(files)), 2))
        if len(pairs) != len(expected_pairs):
            raise ValueError("比較組合せが不足しています")
        for pair, (i, j) in zip(pairs, expected_pairs):
            rows = [r for r in results if (r.left_role, r.right_role) == (report.roles[i], report.roles[j])]
            if not rows or len({r.component for r in rows}) != len(rows) or any((r.left, r.right) != (files[i], files[j]) for r in rows):
                raise ValueError("比較組合せの明細が不正です")
            if pair != summarize(files[i], files[j], report.roles[i], report.roles[j], rows):
                raise ValueError("業務判定と比較明細が一致しません")
        if any((r.left_role, r.right_role) not in [(p.left_role, p.right_role) for p in pairs] for r in results):
            raise ValueError("比較組合せに存在しない明細です")
    return report
