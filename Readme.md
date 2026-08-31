# GND — Getting Started

This repository contains two components that work together to run a local RAG (Retrieval-Augmented Generation) assistant called **GND (Grounded Knowledge)**. You need both.

---

## Repository Structure

```
GroundedKnowledge_dist/          ← The web app (chat UI + server)
├── app.py                       Web server (FastAPI)
├── llm.py                       LLM gateway client
├── rag.py                       Retrieval engine
├── pdf.py                       PDF export
├── settings.py                  Settings store
├── tray.py                      macOS menu bar app
├── start.sh                     ← Run this to launch the app
├── run.sh                       Low-level server launcher
├── install.sh                   launchd auto-start installer (optional)
├── com.gnd.app.plist            launchd service definition
├── static/index.html            Chat UI (single-page app)
├── requirements.txt             Python dependencies
└── index/                       ← Place your RAG index files here
    └── README.md

GroundedKnowledge-content-dist/  ← The indexing engine (builds the RAG index)
├── reference.md                 Taxonomy and grounding rules reference
└── scripts/
    ├── config.py                Corpus/index path configuration
    ├── config.json              Stored paths (set on first run)
    ├── extract.py               Text extraction (PDF, PPTX, DOCX, XLSX, video)
    ├── ingest.py                Index builder
    └── query.py                 Hybrid retrieval engine
```

---

## How It Works

```
Your documents  →  ingest.py  →  index/        →  rag.py  →  LLM  →  Chat UI
(corpus folder)    (builds)      (index.sqlite)    (queries)
```

1. **`GroundedKnowledge-content-dist`** reads your documents, chunks and embeds them, and writes a local SQLite index.
2. **`GroundedKnowledge_dist`** serves the chat UI, retrieves relevant chunks from the index on each question, and sends grounded prompts to your LLM.

---

## Step 1 — Install Python dependencies

Run once from the `GroundedKnowledge_dist/` directory:

```bash
cd GroundedKnowledge_dist
pip3 install -r requirements.txt
```

> **Linux / Windows:** `rumps` (tray icon) is macOS-only. Install everything else:
> ```bash
> pip3 install fastapi uvicorn pydantic reportlab fastembed numpy
> ```

---

## Step 2 — Install the indexing skill

Copy `GroundedKnowledge-content-dist` to the Claude skills directory:

```bash
cp -r GroundedKnowledge-content-dist ~/.claude/skills/GroundedKnowledge-content
```

---

## Step 3 — Point the skill at your documents

```bash
python3 ~/.claude/skills/GroundedKnowledge-content/scripts/config.py \
  --set /path/to/your/documents \
  --index /path/to/GroundedKnowledge_dist/index
```

This saves the paths to `config.json`. You only need to do this once.

---

## Step 4 — Build the index

```bash
# First time or full rebuild:
python3 ~/.claude/skills/GroundedKnowledge-content/scripts/ingest.py --rebuild

# Incremental update (after adding/changing documents):
python3 ~/.claude/skills/GroundedKnowledge-content/scripts/ingest.py
```

This will create `index.sqlite`, `vectors.f32`, and `chunk_ids.i64` inside the `index/` folder. Depending on corpus size this can take several minutes to hours.

---

## Step 5 — Start the app

```bash
cd GroundedKnowledge_dist
./start.sh
```

This launches a `○ GND` / `● GND` menu bar icon (macOS). The server starts automatically at `http://localhost:8787`. Open that URL in your browser.

**Linux / Windows** — run the server directly:
```bash
python3 -m uvicorn app:app --host 127.0.0.1 --port 8787
```

---

## Step 6 — Configure the app

On first launch, click **⚙ Settings** and fill in:

| Setting | What to enter |
|---------|--------------|
| **Gateway URL** | Your LLM API base URL (default: `https://api.anthropic.com`) |
| **Model** | Model ID (default: `claude-sonnet-4-5`) |
| **Authentication** | Select **Enter API key manually**, paste your `sk-…` key |
| **Corpus directory** | The same document folder you used in Step 3 |
| **Index directory** | The absolute path to `GroundedKnowledge_dist/index/` |

Click **Save changes**. The Settings panel will show the document and chunk counts confirming the index loaded correctly.

---

## Auto-start on Login (macOS, optional)

**Option A — Login Items** (recommended):
System Settings → General → Login Items → click **+** → select `start.sh`

**Option B — launchd** (runs in background, no tray):
```bash
cd GroundedKnowledge_dist
bash install.sh
```

---

## Keeping the Index Up to Date

Run this whenever you add or change documents in your corpus:

```bash
python3 ~/.claude/skills/GroundedKnowledge-content/scripts/ingest.py
```

Only new or modified files are re-processed. Then restart the app or click **Stop / Start server** in the menu bar to pick up the refreshed index.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Chat returns "no sources retrieved" | Index directory not set in Settings, or index hasn't been built yet (Step 4) |
| `ModuleNotFoundError: numpy` or `fastembed` | Run `pip3 install -r requirements.txt` again |
| API error on first message | Check that your API key is saved in Settings and the Gateway URL is correct |
| Menu bar icon doesn't appear | `rumps` not installed — run `pip3 install rumps` |
| Server won't start | Check `GroundedKnowledge_dist/server.log` for the error |
