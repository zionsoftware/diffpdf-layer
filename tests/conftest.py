from pathlib import Path
import subprocess
import sys

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject, BooleanObject, DecodedStreamObject, DictionaryObject,
    FloatObject, NameObject, NumberObject, TextStringObject, PdfObject,
)


def statuses(report):
    """Test helper only: production reports have no overall judgment."""
    return {row.status for row in report.results}


@pytest.fixture(scope="session")
def runtime_app(tmp_path_factory):
    root = Path(__file__).resolve().parents[1]
    destination = tmp_path_factory.mktemp("runtime") / "source app"
    run = subprocess.run([sys.executable, str(root / "tools" / "prepare_offline.py"), str(destination)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    return destination


def pdf_value(value):
    if isinstance(value, PdfObject):
        return value
    if isinstance(value, dict):
        return DictionaryObject({NameObject(k): pdf_value(v) for k, v in value.items()})
    if isinstance(value, list):
        return ArrayObject([pdf_value(v) for v in value])
    if isinstance(value, str):
        return NameObject(value) if value.startswith("/") else TextStringObject(value)
    if isinstance(value, bool):
        return BooleanObject(value)
    if isinstance(value, int):
        return NumberObject(value)
    if isinstance(value, float):
        return FloatObject(value)
    return value


def stream(data, attrs=None):
    obj = DecodedStreamObject()
    obj.set_data(data.encode("ascii") if isinstance(data, str) else data)
    if attrs:
        obj.update(pdf_value(attrs))
    return obj


@pytest.fixture
def make_pdf(tmp_path):
    counter = 0

    def make(*, names=("担当者", "確認者"), annotations=None, content=None,
             pages=1, compressed=False, junk=False, mutate=None, text="Base"):
        nonlocal counter
        counter += 1
        writer = PdfWriter()
        if junk:
            for i in range(5):
                writer._add_object(pdf_value({"/Unused": f"unused {i}"}))
        groups = [writer._add_object(pdf_value({"/Type": "/OCG", "/Name": name})) for name in names]
        writer.root_object[NameObject("/OCProperties")] = pdf_value({
            "/OCGs": groups,
            "/D": {"/BaseState": "/ON", "/Order": groups},
        })
        for p in range(pages):
            page = writer.add_blank_page(width=600, height=800)
            font = writer._add_object(pdf_value({"/Type": "/Font", "/Subtype": "/Type1", "/BaseFont": "/Helvetica"}))
            page[NameObject("/Resources")] = pdf_value({
                "/Font": {"/F1": font},
                "/Properties": {f"/L{i}": ref for i, ref in enumerate(groups)},
            })
            data = content if content is not None else f"q BT /F1 12 Tf 20 40 Td ({text}) Tj ET Q"
            obj = stream(data)
            if compressed:
                obj = obj.flate_encode()
            page[NameObject("/Contents")] = writer._add_object(obj)
            specs = annotations if annotations is not None else [{"/Contents": "日本語の注釈"}]
            annots = []
            for spec in specs:
                spec = dict(spec)
                owner = spec.pop("owner", 0)
                attrs = {"/Type": "/Annot", "/Subtype": "/FreeText", "/Rect": [10, 20, 90, 60], "/F": 4, "/C": [1, 0, 0], "/BS": {"/W": 1}, **spec}
                if owner is not None:
                    attrs["/OC"] = groups[owner]
                annot = pdf_value(attrs)
                annot[NameObject("/P")] = page.indirect_reference
                annots.append(writer._add_object(annot))
            page[NameObject("/Annots")] = ArrayObject(annots)
        if mutate:
            mutate(writer, groups)
        path = tmp_path / f"sample-{counter}.pdf"
        writer.write(path)
        return path
    return make
