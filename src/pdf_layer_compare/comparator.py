from pathlib import Path

from .model import BODY, COMPOSITION, UNLAYERED, Report, Result, Status, layer_key
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
    snapshots = [analyze_document(s, reader) if reader is not None else s for s, reader in opened]
    for s in snapshots:
        if s.file_error:
            report.errors.append(f"{s.path}: ファイル解析エラー: {s.file_error}")
    all_names = sorted(set().union(*(s.names for s in snapshots)))
    a = snapshots[0]
    for b in snapshots[1:]:
        for component in [BODY, UNLAYERED, *(layer_key(n) for n in all_names), COMPOSITION]:
            left, right = a.groups.get(component), b.groups.get(component)
            is_layer = component.startswith("レイヤー: ")
            unknown_registry = any(s.ocg and not s.ocg.registry_complete for s in (a, b))
            if is_layer and left is None and right is None and not (a.file_error or b.file_error or unknown_registry):
                continue
            errors = [f"{s.path}: {s.file_error}" for s in (a, b) if s.file_error]
            for snapshot, group in ((a, left), (b, right)):
                if group:
                    errors.extend(f"{snapshot.path}: {e}" for e in group.errors)
                elif is_layer and snapshot.ocg and snapshot.ocg.global_errors:
                    errors.extend(f"{snapshot.path}: {e}" for e in snapshot.ocg.global_errors)
            row = Result(a.path, b.path, component, Status.UNKNOWN)
            if errors:
                row.detail = "\n".join(dict.fromkeys(errors))
            elif is_layer and left is None:
                row.status, row.detail = Status.ADDED, "基準PDFには存在しないレイヤーです。"
            elif is_layer and right is None:
                row.status, row.detail = Status.REMOVED, "比較対象PDFには存在しないレイヤーです。"
            elif left is None or right is None:
                row.detail = "グループ構造を取得できません。"
            else:
                lval, rval = left.content(), right.content()
                if lval.exact == rval.exact:
                    row.status = Status.MATCH
                elif lval.font_errors or rval.font_errors:
                    row.detail = "フォント差と文字内容の差を安全に分離できません。\n" + "\n".join(dict.fromkeys((*lval.font_errors, *rval.font_errors)))
                elif lval.semantic == rval.semantic and set(lval.fonts) != set(rval.fonts):
                    row.status = Status.FONT_ONLY
                    before, after = set(lval.fonts), set(rval.fonts)
                    removed, added = before - after, after - before
                    row.font_changes = [{"before": sorted({name for name, _ in removed}), "after": sorted({name for name, _ in added}),
                                         "source": "PDF内部名/CSSの申告名",
                                         "before_fingerprints": sorted(digest for _, digest in removed),
                                         "after_fingerprints": sorted(digest for _, digest in added)}]
                    names_before = ", ".join(row.font_changes[0]["before"]) or "不明"
                    names_after = ", ".join(row.font_changes[0]["after"]) or "不明"
                    change = f"{names_before} → {names_after}" if names_before != names_after else f"フォント辞書・埋め込みデータ・文字マッピング等の差異 (内部名: {names_before})"
                    row.detail = f"フォントのみ変更: {change}。PDF内部名等であり、正式名称の保証はありません。文字内容と明示した配置等の構造比較です。字幅や見た目の完全一致は保証しません。"
                else:
                    row.status = Status.DIFFERENT
                    row.detail = first_difference(lval.semantic, rval.semantic, component)
                    if not row.detail:
                        row.detail = first_difference(lval.exact, rval.exact, component)
            report.results.append(row)
    return report
