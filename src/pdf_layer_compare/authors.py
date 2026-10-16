"""Read /T in a separate pass so reference-data failures cannot taint content."""
from pypdf.generic import ArrayObject, TextStringObject

from .model import UNLAYERED, AuthorInfo, layer_key
from .normalize import array, dictionary, resolve


def initialize_authors(snapshot):
    snapshot.authors = {key: AuthorInfo() for key in (UNLAYERED, *(layer_key(n) for n in snapshot.names))}
    ocg = snapshot.ocg
    if not ocg.registry_complete:
        for info in snapshot.authors.values():
            info.incomplete("OCG 登録一覧が不完全なため所属別の集計も不完全です")
    for name in ocg.ambiguous_names:
        snapshot.authors[layer_key(name)].incomplete("レイヤー名が重複し、所属別の集計が曖昧です")


def collect_authors(snapshot, reader, warning_context):
    """Count confirmed memberships, reporting incomplete counts explicitly.

    Content parsing has already finished. In particular a broken lazy /T
    reference and its pypdf warnings are confined to this metadata pass.
    """
    infos, ocg = snapshot.authors, snapshot.ocg
    try:
        with warning_context() as warnings:
            pages = list(reader.pages)
        if warnings:
            raise ValueError(" / ".join(warnings))
    except Exception as exc:
        for info in infos.values():
            info.incomplete(f"ページ一覧の作成者集計を完了できません: {exc}")
        return
    for page_number, page in enumerate(pages, 1):
        try:
            with warning_context() as warnings:
                refs = array(page.get("/Annots", ArrayObject()), "Annots")
            if warnings:
                raise ValueError(" / ".join(warnings))
        except Exception as exc:
            for info in infos.values():
                info.incomplete(f"ページ {page_number}: 注釈一覧を取得できません ({exc})")
            continue
        for index, ref in enumerate(refs, 1):
            affected, known = list(infos), None
            try:
                with warning_context() as warnings:
                    annot = dictionary(ref, "注釈")
                    name = ocg.owner(annot.raw_get("/OC")) if "/OC" in annot else None
                    key = UNLAYERED if name is None else layer_key(name)
                    affected, known = [key], infos[key]
                    author = resolve(annot.raw_get("/T")) if "/T" in annot else None
                    missing = "/T" not in annot or isinstance(author, TextStringObject) and not author
                    if not missing and not isinstance(author, TextStringObject):
                        raise ValueError("/T の文字列を安全に取得できません")
                if warnings:
                    raise ValueError(" / ".join(warnings))
                if missing:
                    known.unset_count += 1
                else:
                    known.counts[str(author)] = known.counts.get(str(author), 0) + 1
            except Exception as exc:
                if known is not None:
                    known.unreadable_count += 1
                for key in affected:
                    infos[key].incomplete(f"ページ {page_number} 注釈 {index}: {exc}")
