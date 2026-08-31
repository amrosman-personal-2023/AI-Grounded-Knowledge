#!/usr/bin/env python3
"""Hybrid retrieval over the Seismic index: FTS5 keyword + local embedding cosine,
fused with Reciprocal Rank Fusion, with light folder-metadata boosting.

Returns JSON hits with full provenance so the skill can cite file + page/slide.

Usage:
  python3 query.py "your question" [--k 8] [--index DIR] [--pool 40] [--pretty]
"""
import argparse
import json
import os
import re
import sqlite3
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402

DEFAULT_INDEX = config.index_dir()
EMBED_DIM = 384
RRF_K = 60
SNIPPET_CHARS = 800


def _load_vectors(index_dir, con):
    """Memory-map the vector matrix, rebuilding from SQLite blobs if stale/missing."""
    import numpy as np
    vpath = os.path.join(index_dir, "vectors.f32")
    ipath = os.path.join(index_dir, "chunk_ids.i64")
    db = os.path.join(index_dir, "index.sqlite")
    stale = (not os.path.exists(vpath) or not os.path.exists(ipath) or
             os.path.getmtime(vpath) < os.path.getmtime(db))
    if stale:
        rows = con.execute("SELECT chunk_id, embedding FROM chunks WHERE embedding IS NOT NULL "
                           "ORDER BY chunk_id").fetchall()
        ids = np.array([r[0] for r in rows], dtype=np.int64)
        mat = np.zeros((len(rows), EMBED_DIM), dtype=np.float32)
        for i, (_cid, blob) in enumerate(rows):
            mat[i] = struct.unpack(f"<{EMBED_DIM}f", blob)
        mat.tofile(vpath)
        ids.tofile(ipath)
        return mat, ids
    ids = np.fromfile(ipath, dtype=np.int64)
    mat = np.fromfile(vpath, dtype=np.float32).reshape(-1, EMBED_DIM)
    return mat, ids


def _fts_query(con, query, pool):
    # sanitize into an OR of quoted terms so punctuation never breaks FTS5 syntax
    terms = re.findall(r"[\w'-]+", query.lower())
    terms = [t for t in terms if len(t) > 1]
    if not terms:
        return []
    match = " OR ".join(f'"{t}"' for t in terms)
    try:
        rows = con.execute(
            "SELECT rowid, bm25(chunks_fts) FROM chunks_fts WHERE chunks_fts MATCH ? "
            "ORDER BY bm25(chunks_fts) LIMIT ?", (match, pool)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [r[0] for r in rows]  # ascending bm25 = best first


def _semantic_query(con, index_dir, query, pool):
    import numpy as np
    from fastembed import TextEmbedding
    model_name = con.execute("SELECT v FROM meta WHERE k='model'").fetchone()[0]
    model = TextEmbedding(model_name, cache_dir=os.path.join(index_dir, "models"))
    qv = np.asarray(list(model.embed([query]))[0], dtype=np.float32)
    n = np.linalg.norm(qv)
    if n > 0:
        qv = qv / n
    mat, ids = _load_vectors(index_dir, con)
    if len(ids) == 0:
        return []
    # float32 matmul on NumPy 2.x spuriously trips FP-exception flags on valid data;
    # rankings match float64 to 1e-8, so silence the cosmetic warning.
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        sims = mat @ qv
    top = np.argsort(-sims)[:pool]
    return [int(ids[i]) for i in top]


def _boost(query, hit):
    q = query.lower()
    b = 1.0
    for field in ("persona", "use_case_kit", "content_type"):
        val = (hit.get(field) or "").lower()
        if val and any(tok in q for tok in re.findall(r"[a-z]+", val) if len(tok) > 3):
            b *= 1.2
    if hit.get("content_type") == "Demo Video" and ("demo" in q or "video" in q):
        b *= 1.15
    if "internal" in q and hit.get("audience") == "Internal":
        b *= 1.15
    if "external" in q and hit.get("audience") == "External":
        b *= 1.15
    return b


def search(query, index_dir=DEFAULT_INDEX, k=8, pool=40):
    con = sqlite3.connect(os.path.join(index_dir, "index.sqlite"))
    con.row_factory = sqlite3.Row
    kw = _fts_query(con, query, pool)
    sem = _semantic_query(con, index_dir, query, pool)

    scores = {}
    for rank, cid in enumerate(kw):
        scores[cid] = scores.get(cid, 0) + 1.0 / (RRF_K + rank)
    for rank, cid in enumerate(sem):
        scores[cid] = scores.get(cid, 0) + 1.0 / (RRF_K + rank)
    if not scores:
        con.close()
        return []

    ids = list(scores)
    qmarks = ",".join("?" * len(ids))
    rows = {r["chunk_id"]: r for r in con.execute(
        f"SELECT * FROM chunks WHERE chunk_id IN ({qmarks})", ids)}
    con.close()

    hits = []
    for cid, base in scores.items():
        r = rows.get(cid)
        if not r:
            continue
        hit = {k2: r[k2] for k2 in ("rel_path", "content_type", "persona", "use_case_kit",
                                    "audience", "language", "segment", "page_number",
                                    "slide_number", "ts_start", "ts_end", "text")}
        hit["score"] = round(base * _boost(query, hit), 6)
        hits.append(hit)
    hits.sort(key=lambda h: -h["score"])

    # diversify: at most 2 chunks per file, never the same locator twice, cap snippet size
    per_file, seen_loc, out = {}, set(), []
    for h in hits:
        rp = h["rel_path"]
        h["locator"] = _locator(h)
        loc_key = (rp, h["locator"])
        if loc_key in seen_loc or per_file.get(rp, 0) >= 2:
            continue
        seen_loc.add(loc_key)
        per_file[rp] = per_file.get(rp, 0) + 1
        h["text"] = h["text"][:SNIPPET_CHARS]
        out.append(h)
        if len(out) >= k:
            break
    return out


def _locator(h):
    if h.get("slide_number"):
        seg = " (notes)" if h.get("segment") == "notes" else ""
        return f"slide {h['slide_number']}{seg}"
    if h.get("ts_start") is not None:
        s = int(h["ts_start"])
        return f"@{s // 60}:{s % 60:02d}"
    if h.get("page_number"):
        return f"p.{h['page_number']}"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--pool", type=int, default=40)
    ap.add_argument("--index", default=DEFAULT_INDEX)
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(os.path.join(args.index, "index.sqlite")):
        print(json.dumps({"error": "index not built", "hint": "run ingest.py first"}))
        sys.exit(2)

    hits = search(args.query, args.index, args.k, args.pool)
    print(json.dumps({"query": args.query, "count": len(hits), "hits": hits},
                     indent=2 if args.pretty else None, ensure_ascii=False))


if __name__ == "__main__":
    main()
