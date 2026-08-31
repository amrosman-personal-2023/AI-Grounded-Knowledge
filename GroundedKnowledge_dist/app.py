"""GND — always-on local RAG assistant with per-message PDF export.

Retrieval: local GroundedKnowledge-content index (reuses the skill's query.search).
LLM:       Anthropic-compatible LLM gateway (Anthropic Messages format).
History:   SQLite (chat.db) — survives restarts.
Export:    server-side reportlab PDF, one message at a time (with citations).
"""
import os
import json
import sqlite3
import subprocess
import contextlib
from typing import Optional
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import rag
import llm
import pdf
import settings

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "chat.db")
STATIC = os.path.join(HERE, "static")


def now():
    return datetime.now(timezone.utc).isoformat()


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db():
    with contextlib.closing(db()) as con, con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL
                    REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                citations TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id);
            """
        )


app = FastAPI(title="GND")
init_db()
settings.init()


class ChatIn(BaseModel):
    message: str
    conversation_id: Optional[int] = None
    k: Optional[int] = None


def _history(con, conv_id):
    rows = con.execute(
        "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id",
        (conv_id,),
    ).fetchall()
    turns = [{"role": r["role"], "content": r["content"]} for r in rows]
    return turns[-settings.get("history_turns"):]


@app.get("/api/conversations")
def list_conversations():
    with contextlib.closing(db()) as con:
        rows = con.execute(
            "SELECT id, title, created_at, updated_at FROM conversations "
            "ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/conversations/{conv_id}")
def get_conversation(conv_id: int):
    with contextlib.closing(db()) as con:
        conv = con.execute(
            "SELECT id, title FROM conversations WHERE id=?", (conv_id,)
        ).fetchone()
        if not conv:
            raise HTTPException(404, "conversation not found")
        rows = con.execute(
            "SELECT id, role, content, citations, created_at FROM messages "
            "WHERE conversation_id=? ORDER BY id",
            (conv_id,),
        ).fetchall()
    msgs = []
    for r in rows:
        m = dict(r)
        m["citations"] = json.loads(m["citations"]) if m["citations"] else []
        msgs.append(m)
    return {"id": conv["id"], "title": conv["title"], "messages": msgs}


@app.delete("/api/conversations/{conv_id}")
def delete_conversation(conv_id: int):
    with contextlib.closing(db()) as con, con:
        con.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
    return {"ok": True}


@app.post("/api/chat")
def chat(inp: ChatIn):
    q = inp.message.strip()
    if not q:
        raise HTTPException(400, "empty message")

    with contextlib.closing(db()) as con, con:
        conv_id = inp.conversation_id
        if conv_id:
            if not con.execute(
                "SELECT 1 FROM conversations WHERE id=?", (conv_id,)
            ).fetchone():
                raise HTTPException(404, "conversation not found")
        else:
            title = (q[:60] + "…") if len(q) > 60 else q
            cur = con.execute(
                "INSERT INTO conversations(title, created_at, updated_at) VALUES(?,?,?)",
                (title, now(), now()),
            )
            conv_id = cur.lastrowid

        history = _history(con, conv_id)
        con.execute(
            "INSERT INTO messages(conversation_id, role, content, citations, created_at) "
            "VALUES(?,?,?,?,?)",
            (conv_id, "user", q, None, now()),
        )

    hits = rag.retrieve(q, k=inp.k)
    sources_block, citations = rag.build_sources(hits)
    messages = rag.build_messages(history, q, sources_block)
    answer = llm.complete(rag.SYSTEM, messages)

    with contextlib.closing(db()) as con, con:
        cur = con.execute(
            "INSERT INTO messages(conversation_id, role, content, citations, created_at) "
            "VALUES(?,?,?,?,?)",
            (conv_id, "assistant", answer, json.dumps(citations), now()),
        )
        msg_id = cur.lastrowid
        con.execute(
            "UPDATE conversations SET updated_at=? WHERE id=?", (now(), conv_id)
        )

    return {
        "conversation_id": conv_id,
        "message_id": msg_id,
        "answer": answer,
        "citations": citations,
    }


@app.get("/api/export/{message_id}")
def export_pdf(message_id: int):
    with contextlib.closing(db()) as con:
        msg = con.execute(
            "SELECT m.*, c.title AS conv_title FROM messages m "
            "JOIN conversations c ON c.id=m.conversation_id WHERE m.id=?",
            (message_id,),
        ).fetchone()
        if not msg or msg["role"] != "assistant":
            raise HTTPException(404, "assistant message not found")
        # the question is the immediately preceding user message
        prev = con.execute(
            "SELECT content FROM messages WHERE conversation_id=? AND id<? "
            "AND role='user' ORDER BY id DESC LIMIT 1",
            (msg["conversation_id"], message_id),
        ).fetchone()

    citations = json.loads(msg["citations"]) if msg["citations"] else []
    data = pdf.render_message(
        question=prev["content"] if prev else "",
        answer=msg["content"],
        citations=citations,
        conversation_title=msg["conv_title"],
    )
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="gnd-msg-{message_id}.pdf"'
        },
    )


def _page_from_url(url):
    """Extract the #page=N fragment a citation carries, or None."""
    if not url or "#page=" not in url:
        return None
    try:
        return int(url.rsplit("#page=", 1)[1])
    except (ValueError, IndexError):
        return None


# Neither Preview nor Acrobat honor a #page=N fragment passed to `open`, so we
# open the file with the default handler and then drive the now-frontmost viewer
# to the page via its "Go to Page…" menu item. Best-effort: needs Accessibility
# permission for the launching process; silently no-ops if the menu isn't found.
_GOTO_PAGE_APPLESCRIPT = """
on run argv
  set thePage to item 1 of argv
  delay 1.5
  tell application "System Events"
    set frontApp to name of first process whose frontmost is true
    tell process frontApp
      try
        click menu item "Go to Page…" of menu "Go" of menu bar 1
        delay 0.4
        keystroke thePage
        key code 36
      end try
    end tell
  end tell
end run
"""


@app.get("/api/source/{message_id}/{n}")
def open_source(message_id: int, n: int):
    """Open the cited source file (macOS), jumping to its page for PDFs.

    Local-only server. Opens in the default handler; for a PDF with a known
    page, best-effort drives the viewer to that page via AppleScript.
    """
    with contextlib.closing(db()) as con:
        msg = con.execute(
            "SELECT citations FROM messages WHERE id=?", (message_id,)
        ).fetchone()
    if not msg or not msg["citations"]:
        raise HTTPException(404, "no citations")
    cites = json.loads(msg["citations"])
    cite = next((c for c in cites if c.get("n") == n), None)
    if not cite or not cite.get("abs_path"):
        raise HTTPException(404, "source file not available on disk")

    path = cite["abs_path"]
    subprocess.run(["/usr/bin/open", path], check=False)

    page = _page_from_url(cite.get("url"))
    if page and path.lower().endswith(".pdf"):
        subprocess.run(
            ["/usr/bin/osascript", "-", str(page)],
            input=_GOTO_PAGE_APPLESCRIPT,
            text=True,
            timeout=8,
            check=False,
        )
    return {"ok": True, "opened": path, "page": page}


class SettingsIn(BaseModel):
    gateway_url: Optional[str] = None
    model: Optional[str] = None
    max_tokens: Optional[int] = None
    top_k: Optional[int] = None
    history_turns: Optional[int] = None
    auth_mode: Optional[str] = None
    api_key: Optional[str] = None  # "" clears the stored key; absent leaves it unchanged


class PathsIn(BaseModel):
    corpus: str
    index: Optional[str] = None


@app.get("/api/settings")
def get_settings():
    return {
        "settings": settings.all_resolved(),
        "paths": settings.paths(),
        "devbar_available": llm.devbar_available(),
    }


@app.put("/api/settings")
def save_settings(inp: SettingsIn):
    values = {k: v for k, v in inp.model_dump().items() if v is not None}
    for key in ("max_tokens", "top_k", "history_turns"):
        if key in values and values[key] < 1:
            raise HTTPException(400, f"{key} must be >= 1")
    if "gateway_url" in values and not values["gateway_url"].strip():
        raise HTTPException(400, "gateway_url cannot be empty")
    if "auth_mode" in values:
        if values["auth_mode"] not in ("devbar", "manual"):
            raise HTTPException(400, "auth_mode must be 'devbar' or 'manual'")
        if values["auth_mode"] == "devbar" and not llm.devbar_available():
            raise HTTPException(400, "devbar is not installed on this machine")
    # switching to manual requires a key present (either being set now or already stored)
    effective_mode = values.get("auth_mode", settings.get("auth_mode"))
    if effective_mode == "manual":
        key_now = values.get("api_key", None)
        has_key = (key_now.strip() if key_now is not None else settings.get("api_key").strip())
        if not has_key:
            raise HTTPException(400, "manual auth requires an API key")
    settings.set_many(values)
    return {"settings": settings.all_resolved()}


@app.put("/api/settings/paths")
def save_paths(inp: PathsIn):
    try:
        stats = settings.set_paths(inp.corpus, inp.index)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"paths": stats}


@app.get("/healthz")
def healthz():
    return {"ok": True}


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
