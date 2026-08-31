#!/usr/bin/env python3
"""Build/refresh the local GND content index.

Walks the corpus, extracts text per file (extract.py), chunks with locators +
folder-taxonomy metadata, embeds locally (fastembed multilingual MiniLM), and
writes a single SQLite index with an FTS5 keyword table and float32 vector blobs.

Incremental by (size, mtime) then sha256. Docs only in v1 (videos excluded).

Usage:
  python3 ingest.py [--corpus DIR] [--index DIR] [--rebuild] [--limit N] [--quiet]
"""
import argparse
import hashlib
import json
import os
import sqlite3
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract  # noqa: E402
import config  # noqa: E402

DEFAULT_CORPUS = config.corpus_dir()
DEFAULT_INDEX = config.index_dir()
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBED_DIM = 384
CHUNK_CHARS = 950
CHUNK_OVERLAP = 120
MAX_SLIDE_CHARS = 1200
EMBED_BATCH = 64

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  file_id INTEGER PRIMARY KEY, rel_path TEXT UNIQUE, full_path TEXT, ext TEXT,
  size_bytes INTEGER, mtime REAL, sha256 TEXT,
  division TEXT, content_type TEXT, persona TEXT, use_case_kit TEXT,
  audience TEXT, language TEXT, folder_crumbs TEXT,
  needs_ocr INTEGER DEFAULT 0, indexed_at REAL, status TEXT);
CREATE TABLE IF NOT EXISTS chunks (
  chunk_id INTEGER PRIMARY KEY, file_id INTEGER REFERENCES files(file_id),
  seq INTEGER, segment TEXT, page_number INTEGER, slide_number INTEGER,
  ts_start REAL, ts_end REAL, text TEXT, token_est INTEGER, embedding BLOB,
  rel_path TEXT, content_type TEXT, persona TEXT, use_case_kit TEXT,
  audience TEXT, language TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text, rel_path, content_type, persona, use_case_kit,
  content='chunks', content_rowid='chunk_id', tokenize='unicode61');
CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def sha256_file(path, cap=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(cap))
    h.update(str(os.path.getsize(path)).encode())
    return h.hexdigest()


def chunk_text(text, size=CHUNK_CHARS, overlap=CHUNK_OVERLAP):
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    out, start = [], 0
    while start < len(text):
        end = start + size
        piece = text[start:end]
        if end < len(text):  # prefer a clean break at whitespace
            nl = piece.rfind("\n")
            sp = piece.rfind(" ")
            cut = max(nl, sp)
            if cut > size * 0.6:
                piece = piece[:cut]
                end = start + cut
        piece = piece.strip()
        if piece:
            out.append(piece)
        start = end - overlap if end - overlap > start else end
    return out


def build_chunks_for_file(segments):
    """segments -> list of chunk dicts (locators preserved)."""
    chunks = []
    for seg in segments:
        txt = (seg.get("text") or "").strip()
        if not txt:
            continue
        slide = seg.get("slide_number")
        page = seg.get("page_number")
        segtype = seg.get("segment", "body")
        ts_start = seg.get("ts_start")
        ts_end = seg.get("ts_end")
        # one chunk per slide unless oversized; prose gets windowed
        # for video segments with timestamps, keep them intact
        if ts_start is not None or segtype in ("transcript", "transcript_segment"):
            chunks.append({
                "segment": segtype, "page_number": page, "slide_number": slide,
                "ts_start": ts_start, "ts_end": ts_end, "text": txt,
                "token_est": max(1, len(txt) // 4),
            })
        else:
            pieces = [txt] if (slide is not None and len(txt) <= MAX_SLIDE_CHARS) else chunk_text(txt)
            for piece in pieces:
                chunks.append({
                    "segment": segtype, "page_number": page, "slide_number": slide,
                    "ts_start": None, "ts_end": None, "text": piece,
                    "token_est": max(1, len(piece) // 4),
                })
    return chunks


def connect(index_dir):
    os.makedirs(index_dir, exist_ok=True)
    con = sqlite3.connect(os.path.join(index_dir, "index.sqlite"))
    con.executescript(SCHEMA)
    return con


def iter_corpus(corpus_root):
    for dirpath, _dirs, names in os.walk(corpus_root):
        if ".index" in dirpath.split(os.sep):
            continue
        for n in names:
            if n.startswith(".") or n == "Icon\r" or n == "Icon":
                continue
            ext = os.path.splitext(n)[1].lower()
            if ext in extract.SUPPORTED_EXTS:
                yield os.path.join(dirpath, n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--index", default=DEFAULT_INDEX)
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="process at most N files (debug)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    def log(*a):
        if not args.quiet:
            print(*a, flush=True)

    con = connect(args.index)
    if args.rebuild:
        con.executescript("DROP TABLE IF EXISTS files; DROP TABLE IF EXISTS chunks; "
                          "DROP TABLE IF EXISTS chunks_fts; DROP TABLE IF EXISTS meta;")
        con.executescript(SCHEMA)

    known = {r[0]: (r[1], r[2]) for r in con.execute("SELECT rel_path, size_bytes, mtime FROM files")}

    files = list(iter_corpus(args.corpus))
    if args.limit:
        files = files[:args.limit]
    log(f"scanning {len(files)} candidate files under {args.corpus}")

    todo = []
    for fp in files:
        rp = extract.rel_path(fp, args.corpus)
        st = os.stat(fp)
        if rp in known and abs(known[rp][1] - st.st_mtime) < 1 and known[rp][0] == st.st_size:
            continue
        todo.append(fp)
    log(f"{len(todo)} new/changed files to (re)index; {len(files) - len(todo)} unchanged")
    if not todo:
        _finalize(con, args, log)
        return

    log(f"loading embedding model {MODEL_NAME} ...")
    from fastembed import TextEmbedding
    import numpy as np
    model = TextEmbedding(MODEL_NAME, cache_dir=os.path.join(args.index, "models"))

    t0 = time.time()
    n_files = n_chunks = n_ocr = n_err = 0
    for fp in todo:
        rp = extract.rel_path(fp, args.corpus)
        ext = os.path.splitext(fp)[1].lower()
        st = os.stat(fp)
        try:
            segments = extract.extract(fp)
        except Exception as e:  # corrupt/locked file — record and move on
            _record_error(con, fp, rp, ext, st, str(e))
            n_err += 1
            log(f"  ERROR {rp}: {e}")
            continue

        tax = extract.parse_taxonomy(fp, args.corpus)
        all_text = "\n".join(s.get("text", "") for s in segments)[:1500]
        lang = extract.detect_language(all_text)
        needs_ocr = 1 if any(s.get("needs_ocr") for s in segments) else 0
        n_ocr += needs_ocr

        chunks = build_chunks_for_file(segments)

        # replace any prior rows for this file
        old = con.execute("SELECT file_id FROM files WHERE rel_path=?", (rp,)).fetchone()
        if old:
            con.execute("DELETE FROM chunks WHERE file_id=?", (old[0],))
            con.execute("DELETE FROM files WHERE file_id=?", (old[0],))

        cur = con.execute(
            "INSERT INTO files (rel_path,full_path,ext,size_bytes,mtime,sha256,division,"
            "content_type,persona,use_case_kit,audience,language,folder_crumbs,needs_ocr,"
            "indexed_at,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rp, fp, ext, st.st_size, st.st_mtime, sha256_file(fp), tax["division"],
             tax["content_type"], tax["persona"], tax["use_case_kit"], tax["audience"],
             lang, json.dumps(tax["folder_crumbs"]), needs_ocr, time.time(),
             "embedded" if chunks else "empty"))
        file_id = cur.lastrowid

        if chunks:
            embeds = list(model.embed([c["text"] for c in chunks], batch_size=EMBED_BATCH))
            for seq, (c, vec) in enumerate(zip(chunks, embeds)):
                v = np.asarray(vec, dtype=np.float32)
                nrm = np.linalg.norm(v)
                if nrm > 0:
                    v = v / nrm
                blob = struct.pack(f"<{EMBED_DIM}f", *v.tolist())
                cid = con.execute(
                    "INSERT INTO chunks (file_id,seq,segment,page_number,slide_number,ts_start,"
                    "ts_end,text,token_est,embedding,rel_path,content_type,persona,use_case_kit,"
                    "audience,language) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (file_id, seq, c["segment"], c["page_number"], c["slide_number"],
                     c["ts_start"], c["ts_end"], c["text"], c["token_est"], blob, rp,
                     tax["content_type"], tax["persona"], tax["use_case_kit"],
                     tax["audience"], lang)).lastrowid
                con.execute("INSERT INTO chunks_fts (rowid,text,rel_path,content_type,persona,"
                            "use_case_kit) VALUES (?,?,?,?,?,?)",
                            (cid, c["text"], rp, tax["content_type"] or "",
                             tax["persona"] or "", tax["use_case_kit"] or ""))
            n_chunks += len(chunks)
        n_files += 1
        con.commit()
        if n_files % 25 == 0:
            log(f"  {n_files}/{len(todo)} files, {n_chunks} chunks, {time.time()-t0:.0f}s")

    log(f"done: {n_files} files, {n_chunks} chunks, {n_ocr} needing OCR, {n_err} errors, "
        f"{time.time()-t0:.0f}s")
    _finalize(con, args, log)


def _record_error(con, fp, rp, ext, st, msg):
    con.execute("DELETE FROM files WHERE rel_path=?", (rp,))
    con.execute("INSERT INTO files (rel_path,full_path,ext,size_bytes,mtime,indexed_at,status) "
                "VALUES (?,?,?,?,?,?,?)", (rp, fp, ext, st.st_size, st.st_mtime, time.time(),
                                          "error:" + msg[:120]))
    con.commit()


def _finalize(con, args, log):
    con.execute("INSERT OR REPLACE INTO meta VALUES ('model',?)", (MODEL_NAME,))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('dim',?)", (str(EMBED_DIM),))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('schema_ver','1')")
    con.execute("INSERT OR REPLACE INTO meta VALUES ('build_time',?)", (str(time.time()),))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('corpus',?)", (args.corpus,))
    con.commit()
    # rebuild the mmap vector cache lazily on next query (delete stale)
    for f in ("vectors.f32", "chunk_ids.i64"):
        p = os.path.join(args.index, f)
        if os.path.exists(p):
            os.remove(p)
    nfiles = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    nchunks = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    log(f"index ready: {nfiles} files, {nchunks} chunks at {args.index}/index.sqlite")
    con.close()


if __name__ == "__main__":
    main()
