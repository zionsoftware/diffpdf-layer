"""BAT/CLI entry point; no project installation required."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))


def main():
    import argparse
    parser = argparse.ArgumentParser(description="PDFレイヤー同一性検証ツール")
    parser.add_argument("files", nargs="*")
    parser.add_argument("--cli", action="store_true", help="GUI を使わず比較")
    parser.add_argument("--json", action="store_true", help="JSON を標準出力へ出力")
    parser.add_argument("--output", help=".txt / .csv / .json 保存先")
    parser.add_argument("--check", action="store_true", help="Python / Tkinter / 手動配置した pypdf を確認")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    from pdf_layer_compare.runtime import check_environment
    try:
        version = check_environment(require_tk=args.check or not (args.cli or args.json))
    except RuntimeError as exc:
        if args.json:
            from pdf_layer_compare.model import Report
            from pdf_layer_compare.report import to_json
            print(to_json(Report([str(Path(p).resolve()) for p in args.files], errors=[str(exc)])))
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
        from pdf_layer_compare.model import Status
        from pdf_layer_compare.report import save_report, to_json, to_text
        report = compare_files(args.files)
        if args.output:
            save_report(report, args.output)
        print(to_json(report) if args.json else to_text(report))
        return {Status.MATCH: 0, Status.DIFFERENT: 1, Status.UNKNOWN: 2}[report.status]
    from pdf_layer_compare.gui import launch
    launch(args.files)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
