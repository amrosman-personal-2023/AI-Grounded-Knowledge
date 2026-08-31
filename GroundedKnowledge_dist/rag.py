"""Retrieval + grounded-prompt assembly over the local GroundedKnowledge-content index.

Reuses the skill's own retrieval engine (scripts/query.py) so ranking stays
identical to the CLI. Nothing leaves the machine at retrieval time.
"""
import os
import sys
import urllib.parse

SKILL_SCRIPTS = os.path.expanduser("~/.claude/skills/GroundedKnowledge-content/scripts")
sys.path.insert(0, SKILL_SCRIPTS)

import config  # noqa: E402
import query  # noqa: E402

import settings  # noqa: E402

SYSTEM = (
    "You are a GND knowledge assistant. "
    "Answer ONLY from the provided sources. Cite every claim inline as [n] matching the "
    "numbered sources. If the sources do not support an answer, say so plainly and suggest "
    "adjacent search terms — never fabricate. Be concise and technical, no filler. "
    "Pricing/licensing content marked Internal is quote-gated — flag it and keep list "
    "prices/SKUs out of anything customer-facing."
)


def _basename(rel_path):
    return os.path.basename(rel_path or "")


def retrieve(question, k=None):
    if k is None:
        k = settings.get("top_k")
    idx = config.index_dir()
    if not os.path.exists(os.path.join(idx, "index.sqlite")):
        return []
    return query.search(question, idx, k=k)


def _abs_path(rel_path):
    """Absolute path to the source doc on disk, or None if it can't be resolved."""
    if not rel_path:
        return None
    corpus = config.corpus_dir()
    if not corpus:
        return None
    p = os.path.join(corpus, rel_path)
    return p if os.path.exists(p) else None


def _file_url(abs_path, page_number=None):
    """file:// URL to open the source; append #page=N for PDFs (viewers honor it)."""
    if not abs_path:
        return None
    url = "file://" + urllib.parse.quote(abs_path)
    if page_number and abs_path.lower().endswith(".pdf"):
        url += f"#page={int(page_number)}"
    return url


def build_sources(hits):
    """Return (sources_block_text, citations_list) for the prompt and for storage."""
    lines, cites = [], []
    for i, h in enumerate(hits, 1):
        name = _basename(h.get("rel_path"))
        loc = h.get("locator") or ""
        label = f"{name} — {loc}".strip(" —")
        meta = []
        if h.get("audience"):
            meta.append(h["audience"])
        if h.get("content_type"):
            meta.append(h["content_type"])
        meta_s = f" ({', '.join(meta)})" if meta else ""
        lines.append(f"[{i}] {label}{meta_s}\n{(h.get('text') or '').strip()}")
        abs_path = _abs_path(h.get("rel_path"))
        cites.append(
            {
                "n": i,
                "label": label,
                "rel_path": h.get("rel_path"),
                "abs_path": abs_path,
                "url": _file_url(abs_path, h.get("page_number")),
                "audience": h.get("audience"),
                "content_type": h.get("content_type"),
            }
        )
    return "\n\n".join(lines), cites


def build_messages(history, question, sources_block):
    """history = prior [{role,content}] turns; append the grounded current turn."""
    grounded = (
        f"Question:\n{question}\n\n"
        f"Sources (cite as [n]):\n{sources_block if sources_block else '(no sources retrieved)'}"
    )
    msgs = list(history) + [{"role": "user", "content": grounded}]
    return msgs
