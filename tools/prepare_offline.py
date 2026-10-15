"""Build a source-only runtime directory from the reviewed installed pypdf.

No downloads, wheels, DLLs, EXEs, .pyc files or developer venv are copied.
"""
import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def build_bundle(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("出力先は存在しない新しいフォルダーを指定してください")
    if destination == ROOT or ROOT.is_relative_to(destination):
        raise ValueError("プロジェクトの親フォルダーには出力できません")
    if any(destination.is_relative_to(ROOT / folder) for folder in ("src", "tests", "tools", "docs", "vendor", ".git", ".agents", ".codex")):
        raise ValueError("ソースまたは管理フォルダーの内部には出力できません")
    distribution = metadata.distribution("pypdf")
    if distribution.version != "6.20.1":
        raise ValueError(f"pypdf 6.20.1 が必要です: {distribution.version}")
    source_files = [p for p in distribution.files or () if p.parts[0] == "pypdf" and (p.suffix == ".py" or p.name == "py.typed")]
    licenses = [p for p in distribution.files or () if "licenses" in p.parts and p.name.lower().startswith("license")]
    if not source_files or not licenses:
        raise ValueError("pypdf のソースまたはライセンスを見つけられません")
    destination.mkdir(parents=True)
    for name in ("main.py", "start.bat", "README.md", "LICENSE", "requirements.txt", "requirements-dev.txt", "pyproject.toml"):
        shutil.copyfile(ROOT / name, destination / name)
    for folder in ("src", "tests", "tools", "docs"):
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and path.suffix in {".py", ".md", ".txt", ".bat"}:
                target = destination / path.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
    for path in source_files:
        target = destination / "vendor" / Path(str(path))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(distribution.locate_file(path), target)
    for index, path in enumerate(licenses):
        shutil.copyfile(distribution.locate_file(path), destination / "vendor" / f"pypdf-LICENSE-{index}.txt")
    files = {str(p.relative_to(destination)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(destination.rglob("*")) if p.is_file()}
    (destination / "source-manifest.json").write_text(json.dumps({"pypdf": distribution.version, "files": files}, indent=2), encoding="utf-8")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="オフライン環境用のソース一式を作成")
    parser.add_argument("destination", nargs="?", default=str(ROOT / "dist" / "offline-source"))
    args = parser.parse_args()
    print(build_bundle(args.destination))
