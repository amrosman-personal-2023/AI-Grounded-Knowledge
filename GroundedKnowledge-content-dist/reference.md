# GroundedKnowledge-content — reference

## Folder taxonomy → metadata
The corpus has no metadata layer; all context is derived from the folder path by
`extract.parse_taxonomy`. Fields attached to every chunk:

| Field | Source in path | Example values |
|---|---|---|
| `division` | first segment under `All Sales/` (or `Pricing Center`) | All Technical Sales Content · Content by Type · Content by Product · Sales & Marketing Content · **Pricing Center** |
| `content_type` | deepest known type segment | Demo Video · Learning Material · Presentation · eBook · Data Sheet · Solution Brief · Reference Architecture · Executive Brief · Infographic · CPDS · Pricebook · Measurement Guide · Scalar Worksheet |
| `audience` | `Internal`/`External` split; **Pricing Center → always Internal** | Internal · External · Unknown |

**Pricing Center pack** (`Pricing Center - Release Resources/...`):
`parse_taxonomy` special-cases this subtree → `division=Pricing Center`, `audience=Internal`,
`content_type` = the subfolder (CPDS, Pricebook, Measurement Guide, Scalar Worksheet, FAQ, …).
Quote-gated licensing/pricing content — flag as Internal and keep list prices/SKUs out of
customer-facing assets.
| `persona` | under `6. Personas/<persona>` | Office of the CDO · Cloud Modernization · Cloud Only IT · ERP_SAP Modernization |
| `use_case_kit` | under `7. On Demand Prospecting Kits/<kit>` | Agentic AI Strategy · Analytics and BI · Application Modernization · Gen AI · Regulatory Compliance · SAP ERP Modernization |
| `language` | heuristic on extracted text | en · de · ja · it · unknown |

These fields are returned by `query.py` on every hit and lightly boost ranking when the
query mentions a matching value.

## Citation format
Cite inline as `[<file basename> — <locator>]`.
- PDF/DOCX: `p.N` (DOCX N = synthesized section index, not a printed page)
- PPTX body: `slide N`; PPTX speaker notes: `slide N (notes)`
- XLSX: `p.N` = Nth sheet
Always keep the full `rel_path` available when the user wants to open/send the file.

## Mode decision
- **Q&A** — user asks a question or to *find* something → retrieve, answer with citations, or state
  the gap. Never answer from model priors.
- **Asset** — user says create/build/draft/make → read this file, run scoped retrievals per section,
  ground every fact, then hand off (deck → `solution-blueprint-deck`; one-pager/battlecard/email →
  self-contained artifact in `work-os`).

## solution-blueprint-deck handoff contract
When building a deck, invoke the `solution-blueprint-deck` skill and pass it:
- **Client / engagement context** the user gave.
- **Verified facts, each with its corpus citation** — grouped by the deck's 5 tabs where possible:
  Architecture, Business Use Cases, Analyst Recognition, Customer References, Cost of Inaction.
- Let that skill own layout, theming, and its standing accuracy rules. Do not duplicate its work here;
  this skill's job is to supply grounded, cited source material.

## Standing accuracy rules
- Every number, product claim, and customer reference must trace to a retrieved hit. Flag gaps; do not
  invent. Prefer External-audience sources for customer-facing assets; mark Internal-only material.

## Re-indexing
- Corpus path comes from `scripts/config.json` (set via `config.py --set <dir>`); index = `<corpus>/.index`.
- Incremental (default): `python3 scripts/ingest.py` — only new/changed files re-embedded.
- Clean rebuild: `python3 scripts/ingest.py --rebuild`.
- Index lives at `<index_dir>/`: `index.sqlite`, `vectors.f32`, `chunk_ids.i64`, `models/`.
  Safe to delete the whole index directory to force a from-scratch rebuild.
- Videos are excluded in this version. Re-adding them means wiring `transcribe.py` (faster-whisper via
  PyAV) into `ingest.py` — not part of the current build.
