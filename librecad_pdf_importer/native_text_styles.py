"""Preserve native LibreCAD font names across isolated DXF resource loading."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from ezdxf.xref import get_unique_table_name, get_xref_name


def _native_unicode_name(name: str) -> bool:
    name = name.lower()
    if "#" in name:
        name = name.split("_" if "_" in name else "#", 1)[0]
    return name == "unicode"


def _native_unicode_style(style: Any) -> bool:
    """Recognize the source's native LFF binding, not a substituted font.

    LibreCAD 2.2 ignores STYLE.font and looks up TEXT.style itself. Its QCAD 1
    aliases strip at the first '_' when both '#' and '_' occur, otherwise at
    the first '#'; '$' prefixes are never stripped. Keep the qualification
    narrow: a Unicode name with a conflicting font/bigfont/TTF declaration is
    not evidence of the native Unicode resource.
    """
    font = str(style.dxf.font).lower()
    # Native Save writes its STYLE name back as STYLE.font. Admit only an
    # unpathed, extension-free legacy alias of the same Unicode LFF resource;
    # a font filename/path or conflicting declaration is not that proof.
    font_ok = font in {"unicode", "unicode.lff"} or (
        not any(character in font for character in "/\\:.")
        and _native_unicode_name(font)
    )
    return (
        _native_unicode_name(str(style.dxf.name))
        and font_ok
        and not style.dxf.get("bigfont", "")
        and not (style.dxf.get("flags", 0) & 1)
        and not style.has_extended_font_data
    )


@contextmanager
def preserve_native_text_styles(
    source: Any, target: Any, *, xref_prefix: str = "",
) -> Iterator[None]:
    """Keep XREF resource isolation without breaking native LFF font lookup.

    Wrap the existing XREF_PREFIX loader; pass its exact explicit prefix, if
    any. Predict qualified STYLE names with the same pinned ezdxf functions.
    Rename only newly loaded STYLE objects in place, retaining handles and
    every property. Only new entities' name references change, including
    ezdxf's virtual DIMSTYLE name and multiline attribute content.
    """
    prefix = str(xref_prefix) if xref_prefix else get_xref_name(source)
    qualified = {
        get_unique_table_name(style.dxf.name, prefix, target.styles): {
            key: value for key, value in style.dxf.all_existing_dxf_attribs().items()
            if key not in {"name", "handle", "owner"}
        }
        for style in source.styles if _native_unicode_style(style)
    }
    before = set(target.entitydb) if qualified else set()
    yield
    renamed: dict[str, str] = {}
    alias_number = 1
    for loaded_name, source_properties in qualified.items():
        if loaded_name not in target.styles:
            continue  # Unreferenced source styles are not loaded by ezdxf.
        style = target.styles.get(loaded_name)
        loaded_properties = {
            key: value for key, value in style.dxf.all_existing_dxf_attribs().items()
            if key not in {"name", "handle", "owner"}
        }
        if style.dxf.handle in before or loaded_properties != source_properties:
            raise RuntimeError("Cannot establish the loaded native text-style binding.")
        while True:
            # No '_' anywhere: LibreCAD's alternate legacy branch would consume it.
            alias = f"unicode#bcs-{alias_number}"
            alias_number += 1
            if alias not in target.styles:
                break
        style.dxf.name = alias
        target.styles.replace(loaded_name, style)
        renamed[loaded_name.lower()] = alias
    if renamed:
        # entitydb includes nested block text, ATTDEF/ATTRIB, and MTEXT as well
        # as modelspace TEXT. DIMSTYLE exposes its serialized handle as a
        # virtual name, which must also follow the alias before set_handles().
        for handle, entity in target.entitydb.items():
            if handle not in before and entity.is_alive:
                # R2018 multiline ATTRIB/ATTDEF embeds a non-entitydb MTEXT
                # namespace. Direct access preserves every other raw field;
                # set_mtext() also rewrites the attribute's position/content.
                namespaces = [entity.dxf]
                embedded = getattr(entity, "_embedded_mtext", None)
                if embedded is not None:
                    namespaces.append(embedded.dxf)
                for namespace in namespaces:
                    for attribute in ("style", "dimtxsty"):
                        if namespace.is_supported(attribute):
                            alias = renamed.get(str(namespace.get(attribute, "")).lower())
                            if alias is not None:
                                namespace.set(attribute, alias)
