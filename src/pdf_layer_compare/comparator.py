from itertools import combinations
from pathlib import Path

from .model import Report, Result, Status
from .pdf_parser import analyze_document, open_document


def first_difference(left, right, path="値", depth=0):
    if left == right:
        return ""
    if depth > 12:
        return f"{path}: 内容が異なります"
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                return f"{path}/{key}: 項目の有無が異なります"
            if left[key] != right[key]:
                return first_difference(left[key], right[key], f"{path}/{key}", depth + 1)
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        if len(left) != len(right):
            return f"{path}: 要素数 {len(left)} → {len(right)}"
        for index, (a, b) in enumerate(zip(left, right), 1):
            if a != b:
                return first_difference(a, b, f"{path}[{index}]", depth + 1)
    return f"{path}: {str(left)[:180]!r} → {str(right)[:180]!r}"


def compare_files(paths):
    paths = [str(Path(p).resolve()) for p in paths]
    report = Report(paths)
    if not 2 <= len(paths) <= 4:
        report.errors.append("PDF は 2～4 ファイル指定してください")
        return report
    opened = [open_document(p) for p in paths]
    for snapshot, _ in opened:
        if snapshot.configuration_error:
            report.errors.append(f"{snapshot.path}: 構成検査エラー: {snapshot.configuration_error}")
    if report.errors:
        return report
    all_names = set().union(*(s.names for s, _ in opened))
    for snapshot, _ in opened:
        missing = all_names - set(snapshot.names)
        if missing:
            report.errors.append(f"{snapshot.path}: 不足レイヤー: {', '.join(sorted(missing))}")
    if report.errors:
        return report
    report.configuration_ok = True
    snapshots = [analyze_document(s, reader) for s, reader in opened]
    for a, b in combinations(snapshots, 2):
        parts = [("ベースPDF", a.base, b.base), ("合成順序", a.composition, b.composition)]
        parts += [(f"レイヤー: {n}", a.layers.get(n), b.layers.get(n)) for n in sorted(all_names)]
        for component, left, right in parts:
            if a.errors or b.errors:
                detail = "\n".join(f"{s.path}: {e}" for s in (a, b) for e in s.errors)
                status = Status.UNKNOWN
            else:
                status = Status.MATCH if left == right else Status.DIFFERENT
                detail = first_difference(left, right, component)
            report.results.append(Result(a.path, b.path, component, status, detail))
    return report
