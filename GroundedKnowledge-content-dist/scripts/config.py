#!/usr/bin/env python3
"""Resolve where the Seismic corpus and its index live.

Resolution order (first hit wins):
  1. explicit --corpus / --index CLI args (handled by the caller)
  2. $SEISMIC_CORPUS environment variable
  3. config.json next to this file  ->  {"corpus": "...", "index": "..."}
  4. built-in fallback

Paths in config.json may be RELATIVE — they are resolved against the scripts dir,
so a `index/` bundled inside the skill folder travels with it (self-contained
package). The index defaults to a bundled `../index` if present, else <corpus>/.index.
`set_corpus()` persists the choice so the path is asked for once and reused after.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
BUNDLED_INDEX = os.path.normpath(os.path.join(HERE, "..", "index"))
# No machine-specific default: each user sets their own corpus (the "files folder"
# holding the source docs) on first run via `config.py --set <dir>`. The retrieval
# index is bundled at ../index and resolves automatically, so Q&A works out of the box.
FALLBACK_CORPUS = ""


def _load():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except (ValueError, OSError):
            return {}
    return {}


def _resolve(path):
    """Expand ~ and resolve relative paths against the scripts dir."""
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.normpath(os.path.join(HERE, path))
    return path


def corpus_dir():
    env = os.environ.get("SEISMIC_CORPUS")
    if env:
        return _resolve(env)
    cfg = _load()
    if cfg.get("corpus"):
        return _resolve(cfg["corpus"])
    return FALLBACK_CORPUS


def index_dir():
    env = os.environ.get("SEISMIC_INDEX")
    if env:
        return _resolve(env)
    cfg = _load()
    if cfg.get("index"):
        return _resolve(cfg["index"])
    if os.path.exists(os.path.join(BUNDLED_INDEX, "index.sqlite")):
        return BUNDLED_INDEX
    return os.path.join(corpus_dir(), ".index")


def set_corpus(corpus, index=None):
    """Persist the corpus (and optional index) path to config.json.

    A relative `index` (e.g. "../index") is stored verbatim so a bundled index
    stays portable; only absolute/`~` forms are normalized.
    """
    corpus = os.path.abspath(os.path.expanduser(corpus))
    cfg = _load()
    cfg["corpus"] = corpus
    if index is None:
        # keep the bundled index if it's present; else default to <corpus>/.index
        cfg["index"] = "../index" if os.path.exists(
            os.path.join(BUNDLED_INDEX, "index.sqlite")) else os.path.join(corpus, ".index")
    elif os.path.isabs(os.path.expanduser(index)):
        cfg["index"] = os.path.abspath(os.path.expanduser(index))
    else:
        cfg["index"] = index  # relative — keep verbatim, resolved against scripts dir at read time
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    return cfg


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="View or set the Seismic corpus path.")
    ap.add_argument("--set", metavar="DIR", help="persist this corpus path to config.json")
    ap.add_argument("--index", metavar="DIR", help="optional explicit index path (with --set)")
    args = ap.parse_args()
    if args.set:
        cfg = set_corpus(args.set, args.index)
        print(json.dumps(cfg, indent=2))
    else:
        print(json.dumps({"corpus": corpus_dir(), "index": index_dir(),
                          "config_file": CONFIG_PATH,
                          "config_exists": os.path.exists(CONFIG_PATH)}, indent=2))
