# AIMV

AIMV is an AI-assisted file organizer that classifies files by their contents, routes
them into a stable human-readable taxonomy, applies consistent names, and records every
move for search and undo.

Its managed organization tree contains **332 leaf buckets across 16 broad areas**. AIMV
offers every bucket to Jev or Laya through a complete three-step decision tree: 16 Areas, then
5–8 Categories in the selected Area, then 4 final Buckets. No folder is silently removed
by a retrieval prefilter, and the largest choice contains only 16 options.

## What AIMV Does

- Extracts filename, type, date, and text evidence; the generative fallback can also use
  visual evidence from PDFs and images.
- Makes all 332 curated buckets reachable through bounded hierarchical decisions.
- Classifies multiple files concurrently with a configurable worker limit.
- Commits moves in a controlled stage so prompts, logs, and index writes cannot race.
- Organizes dated material by year or year/month beneath the semantic bucket.
- Writes `.aimv-folder.yaml` into every managed folder for durable identity and search.
- Uses stable bucket IDs instead of trusting model-generated filesystem paths.
- Uses Jev through OpenRouter's hosted Decisions API by default.
- Retains Laya as an optional local or self-hosted `/v1/systemone` provider.
- Retains an optional generative-provider fallback, including strict Structured Outputs
  through OpenAI's Responses API at the official endpoint.
- Logs moves, indexes organized files, supports dry runs, and can undo prior moves.

## Installation

Install AIMV and configure an OpenRouter key:

```bash
pip install AI-mv
export OPENROUTER_API_KEY="sk-or-v1-..."
```

For local development:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Jev is the default decision provider:

```bash
aimv init
```

The defaults are `OPENROUTER_DECISIONS_URL=https://openrouter.ai/api/alpha/decisions`
and `JEV_MODEL=typesafe/jev-1.13`.

To use open-weight Laya locally instead (Python 3.10+):

```bash
pip install "AI-mv[laya]"
export AIMV_DECISION_PROVIDER=laya
```

To share one Laya process among AIMV workers or machines, run its HTTP server:

```bash
pip install AI-mv "laya[serve]"
LAYA_DEVICE=cuda LAYA_PRELOAD=1 laya-serve

export LAYA_BASE_URL="http://127.0.0.1:8000"
export AIMV_DECISION_PROVIDER=laya
aimv init
```

`LAYA_MODEL` optionally pins a Laya route/model, `LAYA_API_KEY` supplies a bearer token
for a protected server, and `LAYA_PRELOAD=0` disables local eager loading.

`aimv init` creates AIMV's state directory and materializes the managed tree under
`~/AIMV` by default. Change the root before initialization when desired:

```bash
export AIMV_TAXONOMY_ROOT="$HOME/Documents/AIMV"
aimv init
```

## Everyday Commands

```bash
# Preview one classification without creating folders or moving files
aimv sort --dry-run ~/Downloads/document.pdf

# Classify and organize one file
aimv sort ~/Downloads/document.pdf

# Classify directory contents with four concurrent workers
aimv batch ~/Downloads --workers 4

# Preview an entire batch
aimv batch ~/Downloads --workers 4 --dry-run

# Search files that AIMV has organized
aimv index search "physics homework"

# Undo the most recent move
aimv undo

# Inspect recent movement history
aimv log --last 20
```

## Managed Taxonomy

The numeric prefix is a stable route and sort key. The title is the human meaning. A
typical destination is immediately readable:

```text
~/AIMV/
└── 50 Money & Finance/
    └── 50.20 Income & Spending/
        └── 50.20.03 Invoices & Bills/
            └── 2024/
                └── 2024-07/
                    └── 2024-07_vendor_invoice.pdf
```

The top-level areas are:

| Code | Area | Leaf buckets |
| ---: | --- | ---: |
| 00 | Intake & Workflow | 20 |
| 10 | Personal & Identity | 20 |
| 20 | Home & Property | 20 |
| 30 | Family & Relationships | 20 |
| 40 | Health & Wellness | 20 |
| 50 | Money & Finance | 20 |
| 60 | Career & Employment | 20 |
| 70 | Education & Research | 32 |
| 80 | Business & Operations | 20 |
| 90 | Legal & Compliance | 20 |
| 100 | Technology & Data | 20 |
| 110 | Creative & Media | 20 |
| 120 | Travel & Transportation | 20 |
| 130 | Community & Civic Life | 20 |
| 140 | Hobbies & Lifestyle | 20 |
| 150 | Archive & Reference | 20 |

Each area contains five to eight categories and each category contains four focused leaf
buckets. The research branch includes grants and funding, letters, academic service,
research governance, and collaboration. The full source taxonomy is in
`aimv/taxonomy/defaults/personal.yaml`.

Research-focused routes include:

```text
70 Education & Research/
├── 70.30 Research/
│   ├── 70.30.01 Research Papers
│   ├── 70.30.02 Datasets
│   ├── 70.30.03 Literature Reviews
│   └── 70.30.04 Methods & Protocols
├── 70.60 Grants & Research Funding/
│   ├── 70.60.01 Opportunities & Solicitations
│   ├── 70.60.02 Proposals & Applications
│   ├── 70.60.03 Budgets, Biosketches & Support Documents
│   └── 70.60.04 Awards, Reports & Closeout
├── 70.70 Academic Career & Service/
│   ├── 70.70.01 Recommendation Letters
│   └── 70.70.02 Letters of Support & Collaboration
└── 70.80 Research Governance & Collaboration/
    ├── 70.80.01 Ethics, IRB & Consent
    ├── 70.80.02 Data Management & Sharing Plans
    ├── 70.80.03 Collaborator & Subaward Agreements
    └── 70.80.04 Disclosures, COI & Compliance
```

### Inspect, Search, and Install

```bash
# Show the broad areas
aimv taxonomy list

# Search semantic routes without calling a model
aimv taxonomy search "monthly Chase statement"
aimv taxonomy search "blood panel laboratory result" --limit 5

# Validate IDs, parents, paths, time policies, and minimum breadth
aimv taxonomy validate

# Install missing folders and metadata
aimv taxonomy install

# Refresh AIMV-owned metadata after a taxonomy update
aimv taxonomy install --force
```

Use `--root PATH` with taxonomy commands to inspect or install another managed root.

## Hidden Folder Metadata

Every managed directory has a hidden `.aimv-folder.yaml`. Normal file browsing stays
clean, while AIMV and other agents get a machine-readable description:

```yaml
schema_version: 1
id: bucket.50.20.03
code: 50.20.03
title: Invoices & Bills
kind: bucket
relative_path: 50 Money & Finance/50.20 Income & Spending/50.20.03 Invoices & Bills
parent_id: category.50.20
purpose: Invoices & Bills within Income & Spending.
aliases:
  - vendor invoice
  - utility bill
  - amount due
tags:
  - money
  - finance
  - income
  - spending
  - invoices
  - bills
include: []
exclude: []
partition: year_month
```

Installed metadata is loaded back into the catalog. Editing aliases, tags, purpose,
include, or exclude fields therefore changes local route search without rewriting code.
The `--force` installation option intentionally replaces those edits with bundled
defaults, so use it only when a reset is wanted.

Year and month folders also receive metadata. Their IDs are derived from the parent
bucket and time value, keeping generated routes searchable and self-describing.

## Classification Pipeline

```text
enumerate files
  -> prepare evidence in parallel
  -> choose action and one of all 16 Areas
  -> choose one of 5–8 Categories, then one of 4 Buckets
  -> run those hosted or local decision paths concurrently across files
  -> validate typed decisions
  -> review medium-confidence decisions in input order
  -> commit filesystem moves sequentially
  -> update movement log and file index
```

The expensive stages—content extraction and model calls—run concurrently. Filesystem
mutation and shared persistence remain ordered. This provides most of the speedup while
avoiding duplicate destinations, interleaved questions, or corrupted JSON state.

Set the default concurrency with `AIMV_BATCH_WORKERS`; override it per invocation with
`--workers`.

## Jev/Laya Decisions and Folder Routes

Every final Bucket is an available outcome. AIMV does not flatten all 332 Buckets into
one low-quality choice or discard possibilities with a top-K filter. Instead, each file
follows the complete Taxonomy hierarchy:

```text
16 Areas -> 5–8 Categories in the chosen Area -> 4 Buckets in the chosen Category
```

Stable IDs are the machine choices. The final choice criteria also contain the complete
human-readable route, for example:

```text
bucket.50.20.03
50 Money & Finance/50.20 Income & Spending/50.20.03 Invoices & Bills
```

The validated decision contains:

- `action`: `move`, `trash`, or `stay`
- `bucket_id`: the selected final hierarchical option, or null for trash/stay
- `year` and `month`: the document's subject date when one exists
- `tags`, `confidence`, and short reasoning

Jev and Laya perform typed classification rather than free-form text generation, so AIMV keeps
the original basename. It derives year/month locally from the filename or extracted
content, then falls back to file modification time. The model never chooses an arbitrary
absolute destination. These providers also do not inspect image pixels; image-only files are
classified from filename, type, dates, and other local metadata unless the visual-capable
generative fallback is selected. AIMV resolves the selected bucket ID locally, applies
its time-partition policy, confines it to the managed root, and produces a collision-free
destination.

### Provider Behavior

- **OpenRouter Jev (default):** three hosted Decisions API calls per moved file using
  `typesafe/jev-1.13` and the complete hierarchy.
- **Local Laya:** one lazily initialized `laya.Router`, shared by classification
  workers. The first call can preload model routes.
- **Self-hosted Laya HTTP:** three `POST /v1/systemone` decisions per moved file,
  using the same complete hierarchy and typed choice keys.
- **Generative fallback:** set `AIMV_DECISION_PROVIDER=generative`. Official OpenAI uses
  the Responses API with a strict Structured Outputs schema; Google uses native
  `generateContent`; compatible endpoints use Chat Completions.

Example fallback configuration:

```bash
export AIMV_DECISION_PROVIDER=generative
export OPENAI_API_KEY="..."
export OPENAI_API_BASE_URL="https://api.openai.com/v1"
export MODEL_NAME="<supported-model>"
```

OpenAI's asynchronous Batch API is not used for interactive sorting because it is
designed for deferred jobs. AIMV instead sends ordinary classification requests through
a bounded local worker pool.

## Time Organization

Most buckets create a year directory. Categories where month-level browsing is useful,
such as receipts, invoices, photos, videos, and reservations, create `YYYY/YYYY-MM`.

AIMV recognizes numeric and named subject dates in filenames and extracted content.
When content does not provide a meaningful date, it falls back to the file modification
year and month. Time partitioning is a Bucket policy stored in metadata, not a
model-generated path.

## Rules Engine

The existing YAML rules still contribute content hints, naming examples, and metadata
expectations. Built-in rules cover academic files, bank statements, invoices, medical
records, photos, receipts, and a general fallback.

```bash
aimv rules
aimv rules --show receipts
aimv sort --rule receipts ~/Downloads/purchase.pdf
aimv sort --no-rules ~/Downloads/unknown.dat
```

The taxonomy is authoritative for destinations. Legacy Rule target paths are guidance;
the decision provider must still reach one managed Bucket ID through the complete hierarchy.

## Safety Model

- Dry runs do not create directories, metadata, log records, or index entries.
- Model-generated names cannot contain paths or change the file extension.
- Destinations must remain under the configured managed root.
- Existing destination names receive a numeric suffix instead of being overwritten.
- Low-confidence moves are skipped; medium-confidence moves require confirmation.
- Trash decisions always require confirmation outside dry-run mode.
- If persistence fails after a move, AIMV attempts to move the file back.
- API usage claims are atomic across classification threads.

## State Directory

User state lives under `~/.aimv/`:

```text
~/.aimv/
├── config.yaml
├── api_usage.json
├── index.json
├── template.yaml
├── logs/
│   └── moves.jsonl
└── rules/
```

The managed files themselves live under `~/AIMV` unless `AIMV_TAXONOMY_ROOT` or the
equivalent user configuration value changes the root.

## Architecture

The public `SmartMover` remains available for compatibility. Internally, work is split
into deep modules with small interfaces:

- `aimv.taxonomy` owns bucket identity, search, validation, paths, and metadata.
- `aimv.classification` owns evidence preparation, hierarchical decisions, provider
  schemas, and typed plans.
- `aimv.batch` owns bounded scheduling and stable result ordering.
- `aimv.organization` owns review policy, path safety, time routing, moves, logs, and
  indexing.
- `aimv.utils.llm_utils` is the provider adapter at the model seam.

See `CONTEXT.md`, `docs/adr/`, and `docs/architecture/audit-2026-10-04.md` for domain
language and the reasoning behind this structure.

## Development

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q aimv tests
```

The test suite covers the legacy rules/index/tracking behavior plus taxonomy breadth,
semantic search, metadata round-trips, strict decision validation, time routing,
non-mutating dry runs, path safety, and concurrent classification.

## License

GNU General Public License v3.0. See `LICENSE`.
