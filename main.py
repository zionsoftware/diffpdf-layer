"""BAT/CLI entry point; no project installation required."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))


def main():
    import argparse
    parser = argparse.ArgumentParser(description="PDFレイヤー同一性検証ツール")
    parser.add_argument("files", nargs="*", help="担当 確認 [審査 [承認]] の順。審査のみ省略する場合は役割別オプションを使用")
    parser.add_argument("--responsible", "--担当", help="担当PDF（必須）")
    parser.add_argument("--confirmation", "--確認", help="確認PDF（必須）")
    parser.add_argument("--review", "--審査", help="審査PDF（任意）")
    parser.add_argument("--approval", "--承認", help="承認PDF（任意）")
    parser.add_argument("--cli", action="store_true", help="GUI を使わず比較")
    parser.add_argument("--json", action="store_true", help="JSON を標準出力へ出力")
    parser.add_argument("--output", help="cmp.txt / cmp.pdf 等の保存先 (.txt / .pdf / .csv / .json)")
    parser.add_argument("--check", action="store_true", help="Python / Tkinter / 手動配置した pypdf を確認")
    args = parser.parse_args()
    role_inputs = {role: value for role, value in zip(("担当", "確認", "審査", "承認"),
                  (args.responsible, args.confirmation, args.review, args.approval)) if value is not None}
    if args.files and role_inputs:
        parser.error("位置引数と役割別オプションは同時に指定できません")
    inputs = role_inputs if role_inputs else args.files
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    from pdf_layer_compare.runtime import check_environment
    try:
        version = check_environment(require_tk=args.check or not (args.cli or args.json))
    except RuntimeError as exc:
        if args.json:
            from pdf_layer_compare.model import Report
            from pdf_layer_compare.report import to_json
            paths = [str(Path(p).resolve()) for p in (role_inputs.values() if role_inputs else args.files)]
            print(to_json(Report(paths, roles=list(role_inputs) if role_inputs else [], errors=[str(exc)])))
        else:
            print(str(exc), file=sys.stderr)
        return 2
    if args.check:
        print(f"環境確認 OK: Python {sys.version.split()[0]} / pypdf {version} / Tkinter")
        print(f"使用する Python: {sys.executable}")
        print("pypdf は vendor/pypdf のソースから読み込みます。")
        return 0
    if args.cli or args.json:
        from pdf_layer_compare.comparator import compare_files
        from pdf_layer_compare.report import save_report, to_json, to_text
        report = compare_files(inputs)
        if args.output:
            try:
                save_report(report, args.output)
            except (OSError, ValueError) as exc:
                report.errors.append(f"保存エラー: {exc}")
        print(to_json(report) if args.json else to_text(report))
        # Exit codes describe execution; business decisions are in the report.
        return 2 if report.errors else 0
    from pdf_layer_compare.gui import launch
    launch(inputs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
