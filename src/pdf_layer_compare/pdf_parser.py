from contextlib import contextmanager
from io import BytesIO
import logging
from pathlib import Path

import pypdf
from pypdf import PdfReader
from pypdf.generic import DictionaryObject, IndirectObject, StreamObject

from .annotation_analyzer import analyze_annotations
from .base_analyzer import analyze_page, validate_resource
from .model import Snapshot, Unsupported
from .normalize import Canonicalizer, check_numeric_precision, dictionary, stream_data
from .ocg_analyzer import OCGAnalyzer

MAX_FILE = 128 * 1024 * 1024
CATALOG_KEYS = {"/Type", "/Pages", "/OCProperties", "/Metadata", "/Version", "/Lang", "/PageLayout", "/PageMode", "/ViewerPreferences", "/MarkInfo"}


@contextmanager
def parser_messages():
    messages = []

    class Capture(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.WARNING:
                messages.append(record.getMessage())

    handler = Capture()
    logger = logging.getLogger("pypdf")
    logger.addHandler(handler)
    try:
        yield messages
    finally:
        logger.removeHandler(handler)


def open_document(path):
    """Read into memory without holding a writable source handle."""
    path = str(Path(path).resolve())
    snapshot = Snapshot(path)
    try:
        if pypdf.__version__ != "6.20.1":
            raise Unsupported(f"未検証の pypdf バージョン: {pypdf.__version__} (必要: 6.20.1)")
        with parser_messages() as messages:
            with open(path, "rb") as source:
                data = source.read(MAX_FILE + 1)
            if len(data) > MAX_FILE:
                raise Unsupported("ファイルサイズの上限 (128 MiB) 超過")
            check_numeric_precision(data)
            reader = PdfReader(BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise Unsupported("暗号化 PDF は未対応 (パスワードなしの場合も含む)")
            for stream_id in {entry[0] for entry in reader.xref_objStm.values()}:
                obj = reader.get_object(IndirectObject(stream_id, 0, reader))
                if not isinstance(obj, StreamObject):
                    raise Unsupported("不正なオブジェクトストリーム")
                stream_data(obj)
            root = dictionary(reader.trailer.raw_get("/Root"), "Catalog")
            ocg = OCGAnalyzer(root)
            if messages:
                raise Unsupported("PDF 解析警告: " + " / ".join(messages))
            snapshot.names = ocg.names
            snapshot.ocg = ocg
            return snapshot, reader
    except Exception as exc:
        snapshot.configuration_error = f"{type(exc).__name__}: {exc}"
        return snapshot, None


def analyze_document(snapshot, reader):
    try:
        with parser_messages() as messages:
            root = reader.root_object
            extra = set(root) - CATALOG_KEYS
            if extra:
                raise Unsupported(f"未対応の Catalog 属性: {', '.join(sorted(extra))}")
            if not 1 <= len(reader.pages) <= 2000:
                raise Unsupported("ページ数が対応範囲外 (1～2000)")
            ocg = snapshot.ocg
            attrs = DictionaryObject({k: v for k, v in root.items() if k not in {"/Pages", "/OCProperties", "/Metadata"}})
            validate_resource(attrs, reader, ocg)
            snapshot.base = [Canonicalizer(ocg).value(attrs)]
            snapshot.layers = {n: {"state": (ocg.configuration, ocg.attributes[n]), "drawings": [], "annotations": []} for n in ocg.names}
            for index, page in enumerate(reader.pages, 1):
                try:
                    base, drawings, composition = analyze_page(page, reader, ocg)
                    annotations, annotation_order = analyze_annotations(page, reader, ocg, index)
                except Exception as exc:
                    raise Unsupported(f"ページ {index}: {exc}") from exc
                snapshot.base.append(base)
                snapshot.composition.append((index, composition, annotation_order))
                for name in snapshot.names:
                    snapshot.layers[name]["drawings"].extend((index, d) for d in drawings[name])
                    snapshot.layers[name]["annotations"].extend(annotations[name])
            if messages:
                raise Unsupported("PDF 解析警告: " + " / ".join(messages))
    except Exception as exc:
        snapshot.errors.append(f"{type(exc).__name__}: {exc}")
    return snapshot
