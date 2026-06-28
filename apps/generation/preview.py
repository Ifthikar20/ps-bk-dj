"""Deterministic, no-LLM preview of a source document.

Computed from the extracted text in milliseconds so the app can show something
useful — outline, key terms, an extractive summary — in the first few seconds,
while the AI study set generates in the background. This is "our own form of
transcribing": zero model cost, instant.
"""
import re
from collections import Counter

# Small, dependency-free stopword list — enough to keep key terms / summaries
# from being dominated by filler words.
_STOPWORDS = frozenset(
    """
    a an the and or but if then else when while of to in on at by for with about
    against between into through during before after above below from up down out
    off over under again further is are was were be been being have has had do does
    did doing this that these those i you he she it we they them his her its our your
    their what which who whom whose as not no nor so than too very can will just
    should now also may might must each other some any all both few more most such
    only own same here there how why where because they're it's that's there's
    """.split()
)

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]+")


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def _content_words(text: str) -> list[str]:
    return [w for w in _words(text) if len(w) > 3 and w not in _STOPWORDS]


def _looks_heading(line: str) -> bool:
    """A short, title-like line with no terminal punctuation — e.g. a section
    heading rather than prose."""
    return (
        3 <= len(line) <= 80
        and len(line.split()) <= 10
        and line[-1] not in ".!?,:;"
        and bool(re.search(r"[A-Za-z]", line))
    )


def _sentences(text: str) -> list[str]:
    # Headings carry no terminal punctuation, so naive splitting glues them
    # onto the next sentence ("Title Title is ..."). Give heading-like lines a
    # full stop first so they stand alone (and then fall out of the summary,
    # which requires real prose). Only headings are touched, so mid-paragraph
    # line wraps from PDF extraction are still joined normally.
    lines: list[str] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if _looks_heading(s):
            s += "."
        lines.append(s)
    flat = re.sub(r"\s+", " ", " ".join(lines)).strip()
    return [s.strip() for s in _SENTENCE_RE.split(flat) if s.strip()]


def _outline(text: str, limit: int = 8) -> list[str]:
    """Heading-ish lines: short, no terminal punctuation, not too many words."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not _looks_heading(line):
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
        if len(out) >= limit:
            break
    return out


def _summary(sentences: list[str], freqs: Counter, limit: int = 3) -> list[str]:
    """Pick the highest-signal sentences (word-frequency scored, length-
    normalized, with a gentle boost for the opening sentences), then return
    them in their original order so the summary reads naturally."""
    scored: list[tuple[float, int, str]] = []
    for i, s in enumerate(sentences):
        ws = [w for w in _words(s) if w not in _STOPWORDS]
        if len(ws) < 4:
            continue
        score = sum(freqs.get(w, 0) for w in ws) / (len(ws) ** 0.5)
        if i < 3:
            score *= 1.15  # leads usually carry the thesis
        scored.append((score, i, s))
    top = sorted(scored, key=lambda t: t[0], reverse=True)[:limit]
    return [s for _, _, s in sorted(top, key=lambda t: t[1])]


def build_preview(text: str) -> dict:
    """Return a small JSON-able preview of *text*. Safe on empty/garbage input."""
    text = text or ""
    word_list = _words(text)
    word_count = len(word_list)
    freqs = Counter(_content_words(text))
    return {
        "wordCount": word_count,
        "readingMinutes": max(1, round(word_count / 200)) if word_count else 0,
        "outline": _outline(text),
        "keyTerms": [w for w, _ in freqs.most_common(12)],
        "summary": _summary(_sentences(text), freqs),
    }
