"""Check manually copied source dependencies without installing anything."""
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[2]
PYPDF_VERSION = "6.20.1"


def copy_instructions():
    return (
        f"pypdf {PYPDF_VERSION} のソース ZIP をオフライン環境で展開し、\n"
        "展開先 pypdf-6.20.1 内の pypdf フォルダー全体を、\n"
        f"{PROJECT / 'vendor' / 'pypdf'}\n"
        "へコピーしてください。__init__.py だけでなく、サブフォルダーもすべて必要です。\n"
        f"同じ展開先の LICENSE は {PROJECT / 'vendor' / 'pypdf-LICENSE.txt'} にコピーしてください。\n"
        f"詳しい配置例: {PROJECT / 'README.md'}"
    )


def check_environment(require_tk=True):
    source = PROJECT / "vendor" / "pypdf" / "__init__.py"
    if not source.is_file():
        raise RuntimeError("pypdf のソースが見つかりません。\n" + copy_instructions())
    if sys.version_info[:2] != (3, 14):
        raise RuntimeError("Python 3.14 を使用してください (検証環境: 3.14.8)。")
    try:
        import pypdf
        if Path(pypdf.__file__).resolve() != source.resolve():
            raise ImportError("vendor/pypdf 以外のパッケージが読み込まれました")
        if pypdf.__version__ != PYPDF_VERSION:
            raise ImportError(f"必要なバージョン: {PYPDF_VERSION} / 配置されたバージョン: {pypdf.__version__}")
    except Exception as exc:
        raise RuntimeError(f"pypdf の読み込みに失敗しました: {exc}\n" + copy_instructions()) from exc
    if require_tk:
        try:
            import tkinter  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("Tkinter が利用できません。Python のインストールで Tcl/Tk を有効にしてください。") from exc
    return pypdf.__version__
