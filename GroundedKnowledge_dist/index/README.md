# Index Directory

This directory must contain the RAG index files before the app can answer questions.

## Expected contents

| File | Description |
|------|-------------|
| `index.sqlite` | Main index — documents, chunks, FTS5 keyword index |
| `vectors.f32` | Float32 embedding matrix (memory-mapped at query time) |
| `chunk_ids.i64` | Chunk ID array (memory-mapped at query time) |
| `models/` | Cached embedding model weights (auto-downloaded on first query) |

## Option A — Build the index yourself

1. Install the `GroundedKnowledge-content` skill under `~/.claude/skills/GroundedKnowledge-content/`
2. Point it at your document corpus:
   ```bash
   python3 ~/.claude/skills/GroundedKnowledge-content/scripts/config.py \
     --set /path/to/your/documents \
     --index /path/to/GroundedKnowledge_dist/index
   ```
3. Build the index:
   ```bash
   # Incremental (skip unchanged files)
   python3 ~/.claude/skills/GroundedKnowledge-content/scripts/ingest.py

   # Full rebuild
   python3 ~/.claude/skills/GroundedKnowledge-content/scripts/ingest.py --rebuild
   ```

## Option B — Receive a pre-built index

If you received a pre-built index, copy `index.sqlite`, `vectors.f32`, and `chunk_ids.i64`
into this directory.

## Connecting the index to the app

Once the index files are in place:

1. Open `http://localhost:8787`
2. Click **⚙ Settings → Index / Corpus DB**
3. Set **Corpus directory** to your document folder
4. Set **Index directory** to the absolute path of this `index/` folder
5. Click **Save changes** — the UI will confirm the doc and chunk counts
