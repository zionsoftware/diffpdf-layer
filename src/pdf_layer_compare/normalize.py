"""Resolve object identity; retain exact values, decode lossless stream filters.

No coordinate tolerance or text normalization is used. Unknown/cyclic structures
raise Unsupported rather than being replaced with a constant fingerprint.
"""
from decimal import Decimal
from hashlib import sha256
import math
import re

from pypdf.generic import (
    ArrayObject, BooleanObject, ByteStringObject, ContentStream, DictionaryObject,
    FloatObject, IndirectObject, NameObject, NullObject, NumberObject,
    StreamObject, TextStringObject,
)

from .model import Unsupported

MAX_DEPTH = 70
MAX_STREAM = 32 * 1024 * 1024
MAX_NODES = 250_000
LOSSLESS = {"/FlateDecode", "/ASCIIHexDecode", "/ASCII85Decode", "/LZWDecode", "/RunLengthDecode"}
DECIMALS = re.compile(rb"(?<![A-Za-z0-9_.])[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?![A-Za-z0-9_.])")


def check_numeric_precision(data):
    # pypdf stores PDF real numbers as binary floats. Refuse lexical values
    # whose distinctions might be lost. Scanning also strings/binary data can
    # conservatively reject a file; it must never turn a difference into MATCH.
    for match in DECIMALS.finditer(data):
        token = match.group().decode("ascii")
        digits = token.lstrip("+-").replace(".", "").lstrip("0").rstrip("0")
        if len(digits) > 15 or (Decimal(token) and abs(Decimal(token)) < Decimal("1e-100")):
            raise Unsupported("安全に比較できる実数精度の上限超過 (有効数字15桁)")


def resolve(obj):
    seen = set()
    while isinstance(obj, IndirectObject):
        key = (id(obj.pdf), obj.idnum, obj.generation)
        if key in seen:
            raise Unsupported("循環する間接参照")
        seen.add(key)
        obj = obj.get_object()
        if obj is None:
            raise Unsupported("解決できない間接参照")
    return obj


def dictionary(obj, label="辞書"):
    obj = resolve(obj)
    if not isinstance(obj, DictionaryObject):
        raise Unsupported(f"{label}: 辞書ではありません")
    return obj


def array(obj, label="配列"):
    obj = resolve(obj)
    if not isinstance(obj, ArrayObject):
        raise Unsupported(f"{label}: 配列ではありません")
    return obj


def stream_data(obj):
    if "/F" in obj:
        raise Unsupported("外部ファイルのストリーム")
    filters = resolve(obj.get("/Filter", ArrayObject()))
    if isinstance(filters, NameObject):
        filters = [filters]
    if not isinstance(filters, (list, ArrayObject)):
        raise Unsupported("不正なストリーム Filter")
    # DCT/JPX are retained as encoded bytes by pypdf; preserve their parameters.
    opaque = any(str(resolve(f)) in {"/DCTDecode", "/JPXDecode"} for f in filters)
    if any(str(resolve(f)) not in LOSSLESS | {"/DCTDecode", "/JPXDecode"} for f in filters):
        raise Unsupported("未対応のストリーム圧縮方式")
    data = obj.get_data()
    if len(data) > MAX_STREAM:
        raise Unsupported("展開後ストリームの上限 (32 MiB) 超過")
    check_numeric_precision(data)
    return data, opaque


class Canonicalizer:
    def __init__(self, ocg=None):
        self.ocg = ocg
        self.nodes = 0
        # Keep strong references: temporary PDF dictionaries must not alias a
        # recycled id. Only complete, successfully traversed values are cached.
        self.cache = {}

    def value(self, obj, active=frozenset(), depth=0):
        self.nodes += 1
        if self.nodes > MAX_NODES or depth > MAX_DEPTH:
            raise Unsupported("解析量または参照深度の上限超過")
        obj = resolve(obj)
        if self.ocg and isinstance(obj, DictionaryObject) and obj.get("/Type") == "/OCG":
            return ("OCG", self.ocg.owner(obj))
        if isinstance(obj, NullObject) or obj is None:
            return ("null",)
        if isinstance(obj, BooleanObject):
            return ("bool", obj.value)
        if isinstance(obj, (NumberObject, FloatObject, int, float)):
            if not math.isfinite(obj):
                raise Unsupported("非有限数値")
            # FloatObject.__repr__ rounds for PDF serialization; use the
            # underlying Python float representation, never that serializer.
            value = Decimal(str(int(obj)) if isinstance(obj, (NumberObject, int)) else repr(float(obj)))
            text = format(value, "f")
            if "." in text:
                text = text.rstrip("0").rstrip(".")
            return ("number", "0" if not value else text)
        if isinstance(obj, NameObject):
            return ("name", str(obj))
        if isinstance(obj, TextStringObject):
            return ("text", str(obj))
        if isinstance(obj, (ByteStringObject, bytes)):
            return ("bytes", bytes(obj).hex())
        if id(obj) in active:
            raise Unsupported("循環するオブジェクト参照")
        if isinstance(obj, DictionaryObject) and id(obj) in self.cache:
            return self.cache[id(obj)][1]
        active = active | {id(obj)}
        sub = lambda x: self.value(x, active, depth + 1)
        if isinstance(obj, (ArrayObject, list, tuple)):
            return tuple(sub(x) for x in obj)
        if isinstance(obj, DictionaryObject):
            if obj.get("/Type") == "/OCMD":
                raise Unsupported("OCMD (複数条件の所属) は未対応")
            if any(k in obj for k in ("/Ref", "/OPI", "/PS")):
                raise Unsupported("外部参照または PostScript")
            if "/OC" in obj and self.ocg:
                self.ocg.owner(obj.raw_get("/OC"))
            skip = set()
            data = None
            if isinstance(obj, StreamObject):
                data, opaque = stream_data(obj)
                skip = {"/Length"}
                if not opaque:
                    skip |= {"/Filter", "/DecodeParms"}
            def item(key, value):
                # A six-letter subset tag is a storage identifier. Keep the
                # actual family and every other font attribute/program byte.
                if key in {"/BaseFont", "/FontName"} and isinstance(resolve(value), NameObject):
                    value = NameObject(re.sub(r"^/[A-Z]{6}\+", "/", str(resolve(value))))
                return sub(value)
            if obj.get("/Type") == "/Font":
                skip.add("/Name")  # obsolete font resource identifier
            items = tuple((str(k), item(k, v)) for k, v in sorted(obj.items()) if k not in skip)
            result = ("stream", items, sha256(data).hexdigest()) if data is not None else items
            self.cache[id(obj)] = (obj, result)
            return result
        raise Unsupported(f"未対応オブジェクト型: {type(obj).__name__}")


def content_operations(stream, reader):
    stream = resolve(stream)
    if isinstance(stream, ArrayObject):
        for item in stream:
            item = resolve(item)
            if not isinstance(item, StreamObject):
                raise Unsupported("Contents 配列にストリーム以外が存在")
            stream_data(item)
    elif isinstance(stream, StreamObject):
        stream_data(stream)
    else:
        raise Unsupported("Contents がストリームではありません")
    content = ContentStream(stream, reader, forced_encoding="bytes")
    if len(content.get_data()) > MAX_STREAM:
        raise Unsupported("コンテンツストリームの上限超過")
    ops = content.operations
    if len(ops) > 100_000:
        raise Unsupported("描画命令数の上限超過")
    return ops
