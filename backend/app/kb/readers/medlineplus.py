"""MedlinePlus health topics (NLM): plain-English summaries, English only."""

from pathlib import Path

from lxml import etree
from lxml import html as lhtml

from ..load import Bundle
from ..sources import Source
from ..text import clean, normalize


def _text(fragment: str) -> str:
    if not fragment.strip():
        return ""
    root = lhtml.fragment_fromstring(fragment, create_parent="div")
    parts = []
    for el in root.iter():
        if el.tag in ("p", "li", "h3", "h4"):
            t = " ".join(el.text_content().split())
            if t:
                parts.append(("- " if el.tag == "li" else "") + t)
    return clean("\n".join(parts)) or clean(root.text_content())


def read(source: Source, paths: list[Path], **_) -> Bundle:
    bundle = Bundle()
    for _, topic in etree.iterparse(str(paths[0]), tag="health-topic"):
        if topic.get("language") != "English":
            topic.clear()
            continue
        title = topic.get("title", "").strip()
        summary = _text(topic.findtext("full-summary") or "")
        if not title or not summary:
            bundle.refuse({"title": title}, "topic without a summary")
            topic.clear()
            continue
        also = [a.text.strip() for a in topic.iterfind("also-called") if a.text]
        bundle.add("kb_patient_topics", title=title, normalized=normalize(title), also_called=also, summary=summary,
                   url=topic.get("url", ""))
        crumb = f"MedlinePlus › {title}" + (f" (also called {', '.join(also[:4])})" if also else "")
        bundle.passages(breadcrumb=crumb, body=summary, section="patient_summary", topic=title)
        topic.clear()
    return bundle
