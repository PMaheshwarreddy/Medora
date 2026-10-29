"""Streams records out of source files without loading them into memory."""

import csv
import re
from collections.abc import Iterator
from pathlib import Path

import ijson

csv.field_size_limit(50 * 1024 * 1024)

Record = dict

# Keys every OBO term is exposed with, so a Plan can refer to them.
OBO_KEYS = ("id", "name", "definition", "synonyms")


def _repair_row(row: list[str], width: int, delimiter: str) -> list[str]:
    """Fixes the two ways rows go wrong in hand-assembled CSVs.

    1. The whole row was quoted as one field, hiding a CSV row inside it.
    2. A multi-valued last column was not quoted, so it spilled into extra
       fields; those are folded back into the last column.
    """
    if len(row) == 1 and width > 1 and delimiter in row[0]:
        row = next(csv.reader([row[0]], delimiter=delimiter))
    if len(row) > width:
        row = row[: width - 1] + [f"{delimiter} ".join(row[width - 1 :])]
    return row


def iter_csv(path: Path, delimiter: str = ",") -> Iterator[Record]:
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f, delimiter=delimiter)
        header = next(reader, None)
        if header is None:
            return
        header = _repair_row(header, len(header), delimiter)
        # An unnamed first column is usually a saved row index.
        names = [h.strip() or f"column_{i + 1}" for i, h in enumerate(header)]
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            row = _repair_row(row, len(names), delimiter)
            yield dict(zip(names, row))


def json_prefix(record_path: str) -> str:
    """`results` -> `results.item`; `graphs[].nodes` -> `graphs.item.nodes.item`."""
    parts = []
    for segment in filter(None, record_path.split(".")):
        name = re.sub(r"\[\d*\]$", "", segment)
        parts.append(name)
        if segment != name:
            parts.append("item")
    if not parts or parts[-1] != "item":
        parts.append("item")
    return ".".join(parts)


def iter_json(path: Path, record_path: str) -> Iterator[Record]:
    with path.open("rb") as f:
        for item in ijson.items(f, json_prefix(record_path)):
            if isinstance(item, dict):
                yield item


def find_json_records(path: Path, scan_events: int = 400_000) -> str | None:
    """Path of the array holding the file's records, in Plan notation.

    That is the shallowest array of objects with more than one item: a
    wrapper array with a single element (`graphs: [ {nodes: [...]} ]`) is
    stepped through, and small arrays inside each record are not mistaken
    for the records themselves.
    """
    counts: dict[str, int] = {}
    with path.open("rb") as f:
        previous_prefix = previous_event = None
        for seen, (prefix, event, _) in enumerate(ijson.parse(f)):
            if event == "start_map" and prefix.endswith("item"):
                # An item directly inside an array (not a map value).
                if prefix == "item" or prefix.endswith(".item"):
                    counts[prefix] = counts.get(prefix, 0) + 1
            previous_prefix, previous_event = prefix, event
            if seen >= scan_events:
                break
    if not counts:
        return None
    repeated = [p for p, n in counts.items() if n > 1]
    prefix = min(repeated or counts, key=lambda p: p.count("."))
    out: list[str] = []
    for part in prefix.split(".")[:-1]:
        if part == "item" and out:
            out[-1] += "[]"
        elif part != "item":
            out.append(part)
    return ".".join(out)


def iter_obo(path: Path) -> Iterator[Record]:
    """Terms of an OBO ontology, skipping obsolete ones. `synonyms` holds
    the exact synonyms only."""
    term: dict | None = None

    def finish(t: dict | None) -> Record | None:
        if t and t.get("name") and not t.get("obsolete"):
            return {k: t.get(k, [] if k == "synonyms" else "") for k in OBO_KEYS}
        return None

    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("["):
                if (done := finish(term)) is not None:
                    yield done
                term = {"synonyms": []} if line == "[Term]" else None
            elif term is not None and ": " in line:
                key, value = line.split(": ", 1)
                if key in ("id", "name"):
                    term[key] = value
                elif key == "def":
                    match = re.match(r'"((?:[^"\\]|\\.)*)"', value)
                    term["definition"] = match.group(1).replace('\\"', '"') if match else value
                elif key == "synonym":
                    # Only EXACT synonyms mean the same thing; BROAD, NARROW
                    # and RELATED ones would attach a term to the wrong row.
                    match = re.match(r'"((?:[^"\\]|\\.)*)"\s+EXACT\b', value)
                    if match:
                        term["synonyms"].append(match.group(1))
                elif key == "is_obsolete" and value.strip() == "true":
                    term["obsolete"] = True
    if (done := finish(term)) is not None:
        yield done


_OWL_NS = {
    "owl": "http://www.w3.org/2002/07/owl#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "obo": "http://purl.obolibrary.org/obo/",
    "oio": "http://www.geneontology.org/formats/oboInOwl#",
}


def iter_owl(path: Path) -> Iterator[Record]:
    """Classes of an OBO-style OWL ontology (RDF/XML), read like an OBO
    file: id, name, definition and EXACT synonyms; deprecated ones skipped."""
    import xml.etree.ElementTree as ET

    owl_class = f"{{{_OWL_NS['owl']}}}Class"
    for _, element in ET.iterparse(path, events=("end",)):
        if element.tag != owl_class:
            continue
        name = element.findtext("rdfs:label", "", _OWL_NS).strip()
        deprecated = element.findtext("owl:deprecated", "", _OWL_NS).strip() == "true"
        if name and not deprecated:
            yield {
                "id": element.findtext("oio:id", "", _OWL_NS).strip(),
                "name": name,
                "definition": element.findtext("obo:IAO_0000115", "", _OWL_NS).strip(),
                "synonyms": [
                    s.text.strip()
                    for s in element.findall("oio:hasExactSynonym", _OWL_NS)
                    if s.text and s.text.strip()
                ],
            }
        element.clear()


def xml_record_tag(path: Path, scan: int = 3000) -> str | None:
    """The element that repeats directly under the root: one record each."""
    import xml.etree.ElementTree as ET

    counts: dict[str, int] = {}
    depth = 0
    seen = 0
    try:
        for event, element in ET.iterparse(path, events=("start", "end")):
            if event == "start":
                depth += 1
                if depth == 2:
                    counts[element.tag] = counts.get(element.tag, 0) + 1
                    seen += 1
                    if seen >= scan:
                        break
            else:
                depth -= 1
                if depth == 1:
                    element.clear()
    except ET.ParseError:
        if not counts:
            return None
    best = max(counts, key=counts.get, default=None)
    return best if best is not None and counts[best] >= 2 else None


def _xml_value(element) -> dict | str:
    """An element as JSON-like data: attributes as "@name", children by tag
    (a list when the tag repeats), text alone when there is nothing else."""
    children: dict = {}
    for child in element:
        value = _xml_value(child)
        if child.tag in children:
            existing = children[child.tag]
            children[child.tag] = (existing if isinstance(existing, list) else [existing]) + [value]
        else:
            children[child.tag] = value
    for key, value in element.attrib.items():
        children[f"@{key}"] = value
    text = (element.text or "").strip()
    if not children:
        return text
    if text:
        children["#text"] = text
    return children


def iter_xml(path: Path, record_tag: str) -> Iterator[Record]:
    """Each `record_tag` element under the root, as JSON-like data, streamed
    so files of hundreds of megabytes stay out of memory."""
    import xml.etree.ElementTree as ET

    depth = 0
    for event, element in ET.iterparse(path, events=("start", "end")):
        if event == "start":
            depth += 1
            continue
        depth -= 1
        if depth == 1:
            if element.tag == record_tag:
                value = _xml_value(element)
                if isinstance(value, dict):
                    yield value
            element.clear()


def get_values(record: Record, path: str) -> list[str]:
    """Every string found at `path`, e.g. `openfda.generic_name[0]` or
    `meta.synonyms[].val`. A plain CSV column name is a path of one step."""
    if path in record:  # column names may themselves contain dots or brackets
        current: list = [record[path]]
    else:
        current = [record]
        for segment in path.split("."):
            match = re.match(r"^(.*?)(?:\[(\d*)\])?$", segment)
            name, index = match.group(1), match.group(2)
            following: list = []
            for value in current:
                if not isinstance(value, dict) or name not in value:
                    continue
                value = value[name]
                # XML gives a single child as a value and several as a list:
                # an indexed path treats a single one as a list of one.
                if index is not None and isinstance(value, dict):
                    value = [value]
                if index is None:
                    following.append(value)
                elif not isinstance(value, list):
                    continue
                elif index == "":
                    following.extend(value)
                elif int(index) < len(value):
                    following.append(value[int(index)])
            current = following
    out: list[str] = []
    for value in current:
        for item in value if isinstance(value, list) else [value]:
            if item is not None and not isinstance(item, (dict, list)):
                text = str(item).strip()
                if text:
                    out.append(text)
    return out
