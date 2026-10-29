"""Text helpers shared by the readers: normalising names, numbers, chunking."""

import hashlib
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

MAX_TOKENS = 400  # MedCPT reads 512; the breadcrumb and a margin take the rest
OVERLAP_WORDS = 40

_SPACE = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^a-z0-9]+")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def clean(text: str) -> str:
    """Unicode-normalised text with single spaces (newlines kept)."""
    text = unicodedata.normalize("NFKC", text or "").replace("­", "")
    lines = [_SPACE.sub(" ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def normalize(name: str) -> str:
    """Lower-case letters and digits only, for matching names across sources."""
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return _NON_WORD.sub(" ", text).strip()


def numbers(text: str) -> set[str]:
    """Every number in the text, written one way (decimal point, no trailing zeros)."""
    found = set()
    for n in _NUMBER.findall(text or ""):
        whole, _, frac = n.replace(",", ".").partition(".")
        whole = whole.lstrip("0") or "0"
        frac = frac.rstrip("0")
        found.add(f"{whole}.{frac}" if frac else whole)
    return found


def words(text: str) -> list[str]:
    return [w for w in _NON_WORD.split(normalize(text)) if w]


def content_hash(*parts: str) -> str:
    return hashlib.sha256("␞".join(parts).encode()).hexdigest()[:32]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


@lru_cache(maxsize=1)
def _tokenizer():
    path = Path(__file__).resolve().parents[2] / "data/models/medcpt/article-encoder/tokenizer.json"
    if not path.exists():
        return None
    from tokenizers import Tokenizer

    return Tokenizer.from_file(str(path))


def count_tokens(text: str) -> int:
    """MedCPT tokens when its tokenizer is present, else an estimate."""
    tok = _tokenizer()
    if tok is None:
        return int(len(text.split()) * 1.45) + 2
    return len(tok.encode(text).ids)


def chunk(body: str, breadcrumb: str, max_tokens: int = MAX_TOKENS) -> list[str]:
    """Splits a section into passages that fit MedCPT with the breadcrumb.

    Splits on blank lines, then lines, then words; a table keeps its header
    row on every piece. Consecutive pieces share a few words so a sentence
    cut at a boundary is still findable.
    """
    budget = max_tokens - count_tokens(breadcrumb)
    body = body.strip()
    if not body:
        return []
    if count_tokens(body) <= budget:
        return [body]
    lines = body.split("\n")
    header = ""
    if len(lines) > 2 and lines[0].startswith("|") and set(lines[1].replace("|", "").strip()) <= set("-: "):
        header = "\n".join(lines[:2]) + "\n"
        lines = lines[2:]
    pieces: list[str] = []
    current: list[str] = []
    for line in lines:
        trial = header + "\n".join(current + [line])
        if count_tokens(trial) <= budget:
            current.append(line)
            continue
        if current:
            pieces.append(header + "\n".join(current))
            tail = " ".join("\n".join(current).split()[-OVERLAP_WORDS:]) if not header else ""
            current = [tail] if tail else []
        if count_tokens(header + "\n".join(current + [line])) > budget:
            # one line longer than a passage: cut it by words
            ws = line.split()
            step = max(20, int(budget / 1.6))
            for i in range(0, len(ws), step - OVERLAP_WORDS // 2):
                pieces.append(header + " ".join(ws[i : i + step]))
            current = []
        else:
            current.append(line)
    if current and "\n".join(current).strip():
        pieces.append(header + "\n".join(current))
    return [p for p in pieces if p.strip()]
