"""Works out what a file really is from its content, never from its name."""

import csv
import itertools
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import records

SAMPLE_ROWS = 8
PROFILE_ROWS = 20_000
_CODE = re.compile(r"^\s*(import |from \S+ import |def |class |#!|<\?php|function |const |package )", re.M)


@dataclass
class Sniffed:
    # csv | json | obo | owl | xml | text | code | binary | empty
    format: str
    size_bytes: int
    delimiter: str = ","
    # JSON: where the array of records lives, in Plan notation.
    record_path: str = ""
    columns: list[str] = field(default_factory=list)
    sample: list[dict] = field(default_factory=list)
    # Per-column facts from the first PROFILE_ROWS rows.
    profile: dict = field(default_factory=dict)
    text_head: str = ""
    headings: list[str] = field(default_factory=list)

    def describe(self) -> str:
        """The description handed to the planning model."""
        lines = [f"Detected format: {self.format}", f"Size: {self.size_bytes:,} bytes"]
        if self.format in ("csv", "obo", "owl", "json", "xml"):
            if self.record_path and self.format == "json":
                lines.append(f"Records are at JSON path: {self.record_path!r}")
            if self.format == "xml":
                lines.append(
                    f"Each record is one <{self.record_path}> element, given as JSON-like data: "
                    "child elements by tag (a list when repeated, so use [] or [0] in paths), "
                    "attributes as @name."
                )
            if self.format == "owl":
                lines.append("An OWL ontology, read like OBO: synonyms are EXACT synonyms only.")
            if self.columns:
                lines.append("Fields available: " + json.dumps(self.columns))
            if self.profile:
                lines.append("Profile of the first rows: " + json.dumps(self.profile))
            lines.append("Sample records:")
            lines += [json.dumps(r, ensure_ascii=False) for r in self.sample]
        elif self.format == "text":
            if self.headings:
                lines.append("Section headings: " + json.dumps(self.headings[:40]))
            lines.append("Beginning of the text:\n" + self.text_head)
        return "\n".join(lines)


def _shorten(value, text_limit: int = 220, list_limit: int = 3, depth: int = 0):
    """Trims a sample record so long documents do not flood the prompt."""
    if isinstance(value, str):
        return value if len(value) <= text_limit else value[:text_limit] + "…"
    if isinstance(value, list):
        return [_shorten(v, text_limit, list_limit, depth + 1) for v in value[:list_limit]]
    if isinstance(value, dict):
        if depth >= 3:
            return "{…}"
        return {k: _shorten(v, text_limit, list_limit, depth + 1) for k, v in value.items()}
    return value if isinstance(value, (int, float, bool)) or value is None else str(value)


def _profile(rows: list[dict], columns: list[str]) -> dict:
    out: dict = {"rows_profiled": len(rows)}
    if not rows:
        return out
    out["distinct_whole_rows"] = len({tuple(r.get(c, "") for c in columns) for r in rows})
    per_column = {}
    for column in columns:
        values = [str(r.get(column) or "").strip() for r in rows]
        filled = [v for v in values if v]
        per_column[column] = {
            "filled": len(filled),
            "distinct": len(set(filled)),
            "avg_chars": round(sum(map(len, filled)) / len(filled)) if filled else 0,
        }
    out["columns"] = per_column
    return out


def _json_paths(record, prefix: str = "", depth: int = 0) -> list[str]:
    """Paths to every scalar or list-of-scalars in a record, in Plan notation."""
    paths: list[str] = []
    if isinstance(record, dict) and depth < 6:
        for key, value in record.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                paths += _json_paths(value, path, depth + 1)
            elif isinstance(value, list) and value and isinstance(value[0], dict):
                paths += _json_paths(value[0], path + "[]", depth + 1)
            elif isinstance(value, list):
                paths.append(path + "[]")
            else:
                paths.append(path)
    return paths


def sniff(path: Path) -> Sniffed:
    size = path.stat().st_size
    if size == 0:
        return Sniffed("empty", 0)
    with path.open("rb") as f:
        head_bytes = f.read(64 * 1024)
    if b"\x00" in head_bytes:
        return Sniffed("binary", size)
    head = head_bytes.decode("utf-8-sig", errors="replace")
    stripped = head.lstrip()

    if stripped[:1] in "{[":
        record_path = records.find_json_records(path)
        if record_path is not None:
            # Fields vary between records, so look at more than the few shown.
            sample = list(itertools.islice(records.iter_json(path, record_path), 300))
            filled: dict[str, int] = {}
            for record in sample:
                for field_path in _json_paths(record):
                    if records.get_values(record, field_path):
                        filled[field_path] = filled.get(field_path, 0) + 1
            return Sniffed(
                "json",
                size,
                record_path=record_path,
                columns=sorted(filled),
                sample=[_shorten(r) for r in sample[:3]],
                profile={"records_profiled": len(sample), "records_with_value": filled},
            )

    if stripped.startswith("format-version:") or "\n[Term]\n" in head:
        sample = list(itertools.islice(records.iter_obo(path), SAMPLE_ROWS))
        return Sniffed(
            "obo", size, columns=list(records.OBO_KEYS), sample=[_shorten(r) for r in sample]
        )

    if stripped.startswith("<"):
        if "owl:Class" in head or "<owl:Ontology" in head:
            sample = list(itertools.islice(records.iter_owl(path), SAMPLE_ROWS))
            return Sniffed(
                "owl", size, columns=list(records.OBO_KEYS), sample=[_shorten(r) for r in sample]
            )
        record_tag = records.xml_record_tag(path)
        if record_tag is not None:
            sample = list(itertools.islice(records.iter_xml(path, record_tag), 300))
            filled: dict[str, int] = {}
            for record in sample:
                for field_path in _json_paths(record):
                    if records.get_values(record, field_path):
                        filled[field_path] = filled.get(field_path, 0) + 1
            return Sniffed(
                "xml",
                size,
                record_path=record_tag,
                columns=sorted(filled),
                sample=[_shorten(r) for r in sample[:3]],
                profile={"records_profiled": len(sample), "records_with_value": filled},
            )

    first_lines = [line for line in head.splitlines()[:30] if line.strip()]
    if _CODE.search("\n".join(first_lines)):
        return Sniffed("code", size)

    delimiter = _delimiter(first_lines)
    if delimiter:
        rows = list(itertools.islice(records.iter_csv(path, delimiter), PROFILE_ROWS))
        if rows:
            columns = list(rows[0].keys())
            return Sniffed(
                "csv",
                size,
                delimiter=delimiter,
                columns=columns,
                sample=[_shorten(r) for r in rows[:SAMPLE_ROWS]],
                profile=_profile(rows, columns),
            )

    text = path.read_text(encoding="utf-8", errors="replace")
    return Sniffed(
        "text",
        size,
        text_head=text[:3000],
        headings=re.findall(r"^=+ *(.+?) *=+$", text, re.M),
    )


def _delimiter(lines: list[str]) -> str | None:
    """A delimiter that splits the header and most rows into the same width."""
    if len(lines) < 2:
        return None
    for delimiter in (",", "\t", ";", "|"):
        header = next(csv.reader([lines[0]], delimiter=delimiter))
        if len(header) < 2 or any(len(h) > 80 for h in header):
            continue
        consistent = 0
        for line in lines[1:]:
            row = records._repair_row(
                next(csv.reader([line], delimiter=delimiter)), len(header), delimiter
            )
            consistent += len(row) == len(header)
        if consistent >= 0.8 * (len(lines) - 1):
            return delimiter
    return None
