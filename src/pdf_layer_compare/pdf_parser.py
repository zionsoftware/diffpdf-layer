from contextlib import contextmanager
from io import BytesIO
import logging
from pathlib import Path

import pypdf
from pypdf import PdfReader
from pypdf.generic import DictionaryObject, IndirectObject, StreamObject

from .annotation_analyzer import analyze_annotations
from .authors import collect_authors, initialize_authors
from .base_analyzer import DrawingAnalyzer, page_attributes, validate_resource
from .model import BODY, UNLAYERED, Content, Group, Snapshot, Unsupported, combine, layer_key
from .normalize import Canonicalizer, array, check_numeric_precision, content_operations, dictionary, resolve, stream_data
from .ocg_analyzer import OCGAnalyzer

MAX_FILE = 128 * 1024 * 1024
CATALOG_KEYS = {"/Type", "/Pages", "/OCProperties", "/Metadata", "/Version", "/Lang", "/PageLayout", "/PageMode", "/ViewerPreferences", "/MarkInfo", "/AcroForm"}


def validate_page_tree(ref, active=frozenset(), depth=0):
    node = dictionary(ref, "ページツリー")
    if id(node) in active or depth > 50:
        raise Unsupported("ページツリーの循環または深度超過")
    if node.get("/Type") == "/Page":
        return 1
    if node.get("/Type") != "/Pages" or set(node) - {"/Type", "/Kids", "/Count", "/Parent", "/Resources", "/MediaBox", "/CropBox", "/Rotate"}:
        raise Unsupported("未対応または不正なページツリー属性")
    total = sum(validate_page_tree(kid, active | {id(node)}, depth+1) for kid in array(node.get("/Kids"), "Pages Kids"))
    if resolve(node.get("/Count")) != total:
        raise Unsupported("ページツリーの Count と実ページ数が不一致")
    return total


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
        snapshot.file_error = f"{type(exc).__name__}: {exc}"
        return snapshot, None


def analyze_document(snapshot, reader):
    ocg = snapshot.ocg
    snapshot.groups = {key: Group() for key in (BODY, UNLAYERED, *(layer_key(n) for n in snapshot.names))}
    initialize_authors(snapshot)
    groups = snapshot.groups

    def fail(keys, error):
        for key in keys:
            groups[key].errors.append(str(error))

    drawing_keys = [UNLAYERED, *(layer_key(n) for n in snapshot.names)]
    key_for = lambda n: UNLAYERED if n is None else layer_key(n)
    for name in snapshot.names:
        groups[layer_key(name)].errors.extend(ocg.errors.get(name, []) + ocg.global_errors)
        if name in ocg.states:
            value = ocg.states[name]
            groups[layer_key(name)].values.append(Content(value, value))
    if ocg.global_errors and not ocg.registry_complete:
        fail(groups, "OCG 登録一覧を安全に取得できません: " + " / ".join(ocg.global_errors))
    elif ocg.global_errors and not snapshot.names:
        fail([BODY], "OCG 構成が不正です: " + " / ".join(ocg.global_errors))
    try:
        with parser_messages() as messages:
            root = reader.root_object
            extra = set(root) - CATALOG_KEYS
            if extra:
                raise Unsupported(f"未対応の Catalog 属性: {', '.join(sorted(extra))}")
            if not 1 <= len(reader.pages) <= 2000:
                raise Unsupported("ページ数が対応範囲外 (1～2000)")
            if validate_page_tree(root.raw_get("/Pages")) != len(reader.pages):
                raise Unsupported("ページツリーとページ一覧が不一致")
            form_error = ""
            if "/AcroForm" in root:
                try:
                    form = dictionary(root["/AcroForm"], "AcroForm")
                    if set(form) - {"/Fields", "/DR"} or array(form.get("/Fields"), "AcroForm Fields"):
                        raise Unsupported("非空の AcroForm または未対応のフォーム属性")
                    if "/DR" in form:
                        dictionary(form["/DR"], "AcroForm DR")
                except Exception as exc:
                    form_error = str(exc)
                    fail([BODY, UNLAYERED], exc)
            attrs = DictionaryObject({k: v for k, v in root.items() if k not in {"/Pages", "/OCProperties", "/Metadata", "/AcroForm"}})
            validate_resource(attrs, reader, ocg)
            value = (len(reader.pages), Canonicalizer(ocg).value(attrs))
            groups[BODY].values.append(Content(value, value))
            for index, page in enumerate(reader.pages, 1):
                try:
                    groups[BODY].values.append(page_attributes(page, ocg))
                except Exception as exc:
                    fail(groups, f"ページ {index} の構造: {exc}")
                try:
                    resources = dictionary(page.get("/Resources", DictionaryObject()), "ページ Resources")
                    ops = content_operations(page.raw_get("/Contents"), reader) if "/Contents" in page else []
                    drawings, errors = DrawingAnalyzer(reader, ocg).partition(ops, resources)
                    for name, values in drawings.items():
                        if values:
                            # Sort complete, state-bound drawing objects, never
                            # the commands inside an object. Keep multiplicity.
                            groups[key_for(name)].values.append(combine((index, "drawings"), values, unordered=True))
                        if errors[name]:
                            fail([key_for(name)], f"ページ {index}: " + "\n".join(errors[name]))
                except Exception as exc:
                    fail(drawing_keys, f"ページ {index} 本文: {exc}")
                try:
                    annotations, errors = analyze_annotations(page, reader, ocg, form_error)
                    for name, values in annotations.items():
                        if values:
                            groups[key_for(name)].values.append(combine((index, "annotations"), values, unordered=True))
                        if errors[name]:
                            fail([key_for(name)], f"ページ {index}: " + "\n".join(errors[name]))
                except Exception as exc:
                    fail(drawing_keys, f"ページ {index} 注釈一覧: {exc}")
            if messages:
                raise Unsupported("PDF 解析警告: " + " / ".join(messages))
    except Exception as exc:
        fail(groups, f"{type(exc).__name__}: {exc}")
    collect_authors(snapshot, reader, parser_messages)
    return snapshot
