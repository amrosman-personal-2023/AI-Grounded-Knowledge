# GND — Grounded Knowledge Assistant

Local RAG assistant. Retrieves answers from a local document index and calls an Anthropic-compatible LLM API. Runs as a local web server at `http://localhost:8787`.

---

## Requirements

- macOS (tray icon requires `rumps` / PyObjC — see note below for Linux/Windows)
- Python 3.10+
- An Anthropic API key (or any Anthropic-compatible LLM gateway)
- A local document corpus indexed with the `GroundedKnowledge-content` skill

---

## Installation

### 1. Install Python dependencies

```bash
pip3 install -r requirements.txt
```

> **Linux / Windows**: `rumps` is macOS-only. Skip it and run the server directly:
> ```bash
> pip3 install fastapi uvicorn pydantic reportlab fastembed numpy
> ```

### 2. Install the GroundedKnowledge-content skill

The retrieval engine lives in a companion skill. Install it under:
```
~/.claude/skills/GroundedKnowledge-content/scripts/
```
Required files: `config.py`, `query.py`, `ingest.py`, `extract.py`

### 3. Build the document index

```bash
# Point the skill at your corpus directory (one-time setup)
python3 ~/.claude/skills/GroundedKnowledge-content/scripts/config.py --set /path/to/your/documents

# Build the index (incremental — only processes new/changed files)
python3 ~/.claude/skills/GroundedKnowledge-content/scripts/ingest.py

# Or force a full rebuild
python3 ~/.claude/skills/GroundedKnowledge-content/scripts/ingest.py --rebuild
```

---

## Starting the App

### macOS (with tray icon)

```bash
./start.sh
```

This places a `○ GND` / `● GND` icon in the menu bar. The server starts automatically. Open `http://localhost:8787` in your browser.

To start automatically at login: **System Settings → General → Login Items → + → select `start.sh`**

### Linux / Windows (server only)

```bash
python3 -m uvicorn app:app --host 127.0.0.1 --port 8787
```

---

## First-time Configuration

Open `http://localhost:8787`, click **⚙ Settings**, and configure:

| Setting | Description |
|---------|-------------|
| **Gateway URL** | Your LLM gateway base URL (default: `https://api.anthropic.com`) |
| **Model** | Model ID (default: `claude-sonnet-4-5`) |
| **Authentication** | Select **Enter API key manually**, paste your `sk-…` key |
| **Corpus directory** | Absolute path to your document folder |
| **Index directory** | Path containing `index.sqlite` (built in step 3 above) |

Settings are persisted in `chat.db` across restarts.

---

## Environment Variables

All settings can also be set via environment variables (override Settings UI values):

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | LLM gateway base URL |
| `ANTHROPIC_API_KEY` | _(empty)_ | API key |
| `SEISMIC_CHAT_MODEL` | `claude-sonnet-4-5` | Model ID |
| `SEISMIC_CHAT_MAX_TOKENS` | `1500` | Max tokens per response |
| `SEISMIC_CHAT_TOP_K` | `8` | Sources retrieved per query |
| `SEISMIC_CHAT_HISTORY_TURNS` | `8` | Conversation turns in context |

---

## Menu Bar Controls (macOS)

| Icon | Meaning |
|------|---------|
| `● GND` | Server is running |
| `○ GND` | Server is stopped |

Menu options: **Open GND**, **Start / Stop server**, **Quit**

---

## File Overview

| File | Purpose |
|------|---------|
| `app.py` | FastAPI server — REST API and static file serving |
| `llm.py` | LLM client — calls the gateway with the Anthropic Messages format |
| `rag.py` | Retrieval — queries the local index, builds grounded prompts |
| `pdf.py` | PDF export — renders an answer with citations to a downloadable PDF |
| `settings.py` | Settings persistence — SQLite-backed key/value store |
| `tray.py` | macOS menu bar app — manages the server process |
| `start.sh` | Launch script — run this to start everything |
| `run.sh` | Low-level server launcher (used by `start.sh` and launchd) |
| `install.sh` | Install as a launchd LaunchAgent (alternative to Login Items) |
| `static/` | Single-page frontend |
| `requirements.txt` | Python dependencies |
| `chat.db` | Runtime database — auto-created on first run (not included) |

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/conversations` | List conversations |
| GET | `/api/conversations/{id}` | Get conversation with messages |
| DELETE | `/api/conversations/{id}` | Delete conversation |
| POST | `/api/chat` | Send message, get RAG-grounded answer |
| GET | `/api/export/{message_id}` | Download answer as PDF |
| GET | `/api/source/{message_id}/{n}` | Open cited source file (macOS) |
| GET | `/api/settings` | Get all settings |
| PUT | `/api/settings` | Update settings |
| PUT | `/api/settings/paths` | Update corpus/index paths |
| GET | `/healthz` | Health check |
