"""App settings — a key/value store in chat.db with env-var-backed defaults.

Saved values override env-var/built-in defaults at runtime (no restart needed).
Corpus/index paths are NOT stored here: they live in the GroundedKnowledge-content skill's
own config.json, which we read and write through so the CLI and app stay in sync.

Environment variables (all optional — configure via the Settings UI instead):
  ANTHROPIC_BASE_URL      LLM gateway base URL (default: https://api.anthropic.com)
  ANTHROPIC_API_KEY       API key (set this or use the Settings UI)
  SEISMIC_CHAT_MODEL      Model ID (default: claude-sonnet-4-5)
  SEISMIC_CHAT_MAX_TOKENS Max tokens per response (default: 1500)
  SEISMIC_CHAT_TOP_K      Sources retrieved per query (default: 8)
  SEISMIC_CHAT_HISTORY_TURNS  Conversation turns in context (default: 8)
  SEISMIC_CHAT_AUTH_MODE  'manual' (default) or 'devbar'
"""
import os
import sys
import sqlite3
import contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "chat.db")

SKILL_SCRIPTS = os.path.expanduser("~/.claude/skills/GroundedKnowledge-content/scripts")
if SKILL_SCRIPTS not in sys.path:
    sys.path.insert(0, SKILL_SCRIPTS)
import config as skill_config  # noqa: E402

# key -> (env var to fall back to, built-in default, type)
DEFAULTS = {
    "gateway_url": (
        "ANTHROPIC_BASE_URL",
        "https://api.anthropic.com",
        str,
    ),
    "model": ("SEISMIC_CHAT_MODEL", "claude-sonnet-4-5", str),
    "max_tokens": ("SEISMIC_CHAT_MAX_TOKENS", 1500, int),
    "top_k": ("SEISMIC_CHAT_TOP_K", 8, int),
    "history_turns": ("SEISMIC_CHAT_HISTORY_TURNS", 8, int),
    # "devbar": mint a short-lived key per request (Salesforce only); "manual": use the stored api_key.
    "auth_mode": ("SEISMIC_CHAT_AUTH_MODE", "manual", str),
    "api_key": ("ANTHROPIC_API_KEY", "", str),
}

# Secrets: resolved value is never echoed back to the client (masked in all_resolved).
SECRET_KEYS = {"api_key"}


def _db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init():
    with contextlib.closing(_db()) as con, con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )


def _coerce(raw, typ):
    if typ is int:
        return int(raw)
    return str(raw)


def _default(key):
    env_var, fallback, typ = DEFAULTS[key]
    env = os.environ.get(env_var)
    if env not in (None, ""):
        try:
            return _coerce(env, typ)
        except (TypeError, ValueError):
            pass
    return fallback


def get(key):
    """Resolved value: saved override if present, else env var, else built-in."""
    if key not in DEFAULTS:
        raise KeyError(key)
    _env_var, _fallback, typ = DEFAULTS[key]
    with contextlib.closing(_db()) as con:
        row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if row is not None:
        try:
            return _coerce(row["value"], typ)
        except (TypeError, ValueError):
            pass
    return _default(key)


def set_many(values):
    """Persist a subset of setting keys. Unknown keys are ignored."""
    with contextlib.closing(_db()) as con, con:
        for key, val in values.items():
            if key not in DEFAULTS:
                continue
            typ = DEFAULTS[key][2]
            con.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(_coerce(val, typ))),
            )


def all_resolved():
    """Every setting's resolved value plus whether it's an explicit override."""
    with contextlib.closing(_db()) as con:
        overridden = {
            r["key"] for r in con.execute("SELECT key FROM settings").fetchall()
        }
    out = {}
    for key in DEFAULTS:
        if key in SECRET_KEYS:
            # never echo the secret; report only whether one is set
            out[key] = {"is_set": bool(get(key)), "overridden": key in overridden}
        else:
            out[key] = {
                "value": get(key),
                "default": _default(key),
                "overridden": key in overridden,
            }
    return out


def paths():
    """Resolved corpus/index paths and index health (from GroundedKnowledge-content config)."""
    corpus = skill_config.corpus_dir()
    index = skill_config.index_dir()
    index_db = os.path.join(index, "index.sqlite") if index else ""
    stats = {
        "corpus": corpus,
        "index": index,
        "index_exists": False,
        "doc_count": None,
        "chunk_count": None,
    }
    if index_db and os.path.exists(index_db):
        stats["index_exists"] = True
        try:
            with contextlib.closing(sqlite3.connect(index_db)) as con:
                stats["chunk_count"] = con.execute(
                    "SELECT COUNT(*) FROM chunks"
                ).fetchone()[0]
                stats["doc_count"] = con.execute(
                    "SELECT COUNT(*) FROM files"
                ).fetchone()[0]
        except sqlite3.Error:
            pass
    stats["corpus_exists"] = bool(corpus) and os.path.isdir(corpus)
    return stats


def set_paths(corpus, index=None):
    """Validate and persist corpus/index to the GroundedKnowledge-content config.

    Raises ValueError if the corpus dir or the index's index.sqlite is missing.
    """
    corpus = os.path.abspath(os.path.expanduser((corpus or "").strip()))
    if not os.path.isdir(corpus):
        raise ValueError(f"corpus directory does not exist: {corpus}")
    if index:
        index = os.path.expanduser(index.strip())
        resolved = index if os.path.isabs(index) else os.path.normpath(
            os.path.join(SKILL_SCRIPTS, index)
        )
        if not os.path.exists(os.path.join(resolved, "index.sqlite")):
            raise ValueError(f"no index.sqlite found in index directory: {resolved}")
    skill_config.set_corpus(corpus, index)
    return paths()
