"""ICD-10-CM (CDC order file) and ICD-11 MMS (WHO simple tabulation): codes and titles."""

from pathlib import Path

from ..load import Bundle
from ..sources import Source


def _icd10cm(path: Path, bundle: Bundle) -> None:
    # Fixed width: order(5) code(7) billable(1) short(60) long
    for line in open(path, encoding="utf-8"):
        code, billable, long = line[6:13].strip(), line[14:15] == "1", line[77:].strip()
        if not code or not long:
            continue
        dotted = code if len(code) <= 3 else f"{code[:3]}.{code[3:]}"
        parent = "" if len(code) <= 3 else (code[:-1] if len(code) > 4 else code[:3])
        parent = parent if len(parent) <= 3 else f"{parent[:3]}.{parent[3:]}"
        bundle.add("kb_codes", system="ICD-10-CM", code=dotted, title=long, parent=parent, billable=billable)


def _icd11(path: Path, bundle: Bundle) -> None:
    import openpyxl

    ws = openpyxl.load_workbook(path, read_only=True).active
    rows = ws.iter_rows(values_only=True)
    header = list(next(rows))
    col = {name: header.index(name) for name in ("Code", "Title", "ClassKind", "isLeaf", "Parent", "Linearization URI")}
    code_of: dict[str, str] = {}
    pending = []
    for r in rows:
        uri, code = r[col["Linearization URI"]] or "", (r[col["Code"]] or "").strip()
        if code:
            code_of[uri.rsplit("/", 1)[-1]] = code
            pending.append((code, (r[col["Title"]] or "").lstrip("- ").strip(), r[col["Parent"]] or "", r[col["isLeaf"]] == "True"))
    seen = set()
    for code, title, parent, leaf in pending:
        if code in seen or not title:
            continue
        seen.add(code)
        bundle.add("kb_codes", system="ICD-11", code=code, title=title,
                   parent=code_of.get(parent.rsplit("/", 1)[-1], ""), billable=leaf)


def read(source: Source, paths: list[Path], **_) -> Bundle:
    bundle = Bundle()
    (_icd10cm if source.key == "icd10cm" else _icd11)(paths[0], bundle)
    return bundle
