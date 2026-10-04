Rewrite this entire markdown file, make it sensible to read and easy to read, the APP is called AIMV and needs heavy documentation `# 🧠 AI-mv — AI-powered File Organization Tool

`AI-mv` (Smart Move) is an intelligent file organization tool that automatically classifies, renames, and organizes your files based on their **actual contents** — not just filenames. It makes the decision process of "where should this file go?" effortless by analyzing content, context, and your existing folder structure.

## ✅ Key Features

`AI-mv` goes beyond filenames. It reasons like a human:

- **Analyzes textual and visual content** — Extracts and understands text from documents first, then falls back to visual analysis for PDFs and images when needed
- **Matches files with your folder structure** — Finds the perfect location
- **Maintains naming consistency** — Follows existing patterns in target folders
- **Removes clutter** — Identifies disposable files for trash
- **Human-in-the-loop** — Asks for input when uncertain and accepts human hints for better suggestions
- **Rules engine** — Ships with category-specific rules (receipts, bank statements, invoices, academic papers, medical records, photos) that guide the AI with naming conventions, target folders, and metadata extraction
- **Movement logging** — Every file operation is recorded in an append-only JSONL log with file hashes, timestamps, and full source/destination paths
- **Reversible moves** — Undo any operation with `aimv undo`; the system validates file integrity via SHA-256 before reverting
- **File index** — A searchable index tracks every organized file with a one-line description, category, and tags for fast lookup
- **Organization templates** — Scans your folder structure and injects it into every AI prompt so suggestions stay consistent with your existing layout
- **Dry-run mode** — Preview what the AI would do without moving anything
- **Batch processing** — Organize an entire directory of files in one command

## 📥 Installation

```bash
# Install from PyPI
pip install AI-mv

# Or install directly from GitHub
pip install git+https://github.com/geeks-sid/aimv.git
```

After installing, initialize the data directory:

```bash
aimv init
```

This creates `~/.aimv/` with the logs directory, rules directory, file index, and an initial scan of your folder structure.

## 🚀 Usage

### Organize files

```bash
# Organize a single file
aimv sort ~/Downloads/document.pdf

# Shorthand (same as 'aimv sort')
aimv ~/Downloads/document.pdf

# Preview without moving anything
aimv sort --dry-run ~/Downloads/document.pdf

# Organize all files in a directory
aimv batch ~/Downloads/
```

### Undo moves

```bash
# Undo the last move
aimv undo

# Undo a specific move by its log ID
aimv undo --id abc123def456
```

### View history

```bash
# Show the last 10 operations
aimv log

# Show the last 20 operations
aimv log --last 20

# Search the log
aimv log --search "nike receipt"
```

### Search the file index

```bash
# List all indexed files grouped by category
aimv index list

# Search by keyword
aimv index search "physics homework"
```

### Manage rules

```bash
# List all loaded rules (defaults + your custom rules)
aimv rules

# Show details of a specific rule
aimv rules --show receipts
```

### Organization template

```bash
# View the current folder structure template
aimv template show

# Regenerate the template from your filesystem
aimv template generate
```

### Other

```bash
aimv --help          # Show help
aimv -v              # Show version
```

---

## 📁 Rules Engine

`AI-mv` ships with built-in rules for common file categories. Each rule defines:

| Field | Purpose |
|---|---|
| **keywords** | Content keywords the AI uses to identify this file type |
| **filename_patterns** | Glob patterns matched against the filename |
| **target_folder** | Preferred destination (supports `{year}`, `{month}` placeholders) |
| **naming convention** | Template for renaming (e.g. `{date}_{vendor}_{description}.{ext}`) |
| **metadata_fields** | What the AI should extract from the content (date, vendor, amount...) |
| **examples** | Input/output pairs that show the AI how to rename this type of file |

### Built-in categories

| Rule | Priority | Target folder | Example rename |
|---|---|---|---|
| **bank_statements** | 12 | `~/Documents/Financial/Bank_Statements/{bank}/{year}/` | `2025-03_Chase_Statement.pdf` |
| **medical** | 11 | `~/Documents/Medical/{subcategory}/{year}/` | `2025-03-15_Quest_Diagnostics_Blood_Panel.pdf` |
| **receipts** | 10 | `~/Documents/Financial/Receipts/{year}/{month}/` | `2025-01-15_Nike_Return_Label.pdf` |
| **invoices** | 9 | `~/Documents/Financial/Invoices/{year}/{month}/` | `2025-03-01_Comcast_Internet_Bill.pdf` |
| **academic** | 8 | `~/Documents/School/{course}/{category}/` | `SolnsHmwk10_2025.pdf` |
| **photos** | 5 | `~/Pictures/{year}/{month}/` | `2025-03-15_afternoon_photo.jpg` |
| **general** | 0 | `~/Documents/{category}/` | Catch-all with sensible defaults |

### Custom rules

Add your own YAML rule files to `~/.aimv/rules/`. They follow the same format as the defaults and will override any built-in rule with the same name, or be added as a new category.

```yaml
name: tax_documents
description: "Tax forms, W-2s, 1099s, returns"
priority: 13
keywords: [tax, W-2, 1099, tax return, IRS, refund]
filename_patterns: ["*tax*", "*w2*", "*1099*"]
target_folder: "~/Documents/Financial/Taxes/{year}/"
naming:
  template: "{year}_{document_type}_{source}.{ext}"
  date_format: "%Y"
  separator: "_"
  case: title
metadata_fields: [year, document_type, source]
create_subfolders: true
examples:
  - input: "w2_download.pdf"
    output: "2024_W2_Employer_Name.pdf"
    reasoning: "Extracted tax year and employer from document content"
```

---

## 🔄 Movement Log & Undo

Every file operation is recorded in `~/.aimv/logs/moves.jsonl`. Each entry includes:

- Unique ID, timestamp
- Source and destination paths
- Original and new filenames
- Action type (move, rename_and_move, move_to_trash, dry_run)
- Which rule was applied
- SHA-256 file hash and file size
- One-line summary of the file
- List of any directories created during the move

The `aimv undo` command uses this log to safely reverse operations. Before moving a file back, it verifies:

1. The file still exists at the destination
2. The file hash matches (hasn't been modified since the move)
3. The original location is writable
4. No file already exists at the original path

Any empty directories that were created during the original move are cleaned up during undo.

---

## 📇 File Index

The file index at `~/.aimv/index.json` acts as a catalog of every file organized by `AI-mv`. Each entry records:

- Current file path
- One-line description (generated by the AI)
- Category (from the matched rule)
- Original filename and location
- Searchable tags extracted from the summary

Use `aimv index search <query>` to find files by keyword, or `aimv index list` to see everything grouped by category.

---

## 🗂 Organization Template

When you run `aimv init` or `aimv template generate`, `AI-mv` scans your key directories (`~/Documents`, `~/Downloads`, `~/Desktop`, `~/Pictures`) and saves a snapshot of your folder hierarchy to `~/.aimv/template.yaml`.

This template is injected into every AI prompt, so the model always knows your current organizational structure. This means suggestions stay consistent — it won't suggest creating `~/Documents/Finances/` if you already have `~/Documents/Financial/`.

---

## 📂 Data Directory

All user state lives in `~/.aimv/`:

```
~/.aimv/
├── config.yaml          # User configuration overrides
├── rules/               # Custom YAML rule files
├── logs/
│   └── moves.jsonl      # Append-only movement log
├── index.json           # File index
└── template.yaml        # Organization template snapshot
```

---

## 🧬 Real-World Example

Model: gemma3:12b

**Before**

```bash
~/Downloads/
├── label.pdf                          # Nike return instructions
├── Document_20250419_0001.pdf         # Scanned passport page
├── HttpToolkit-1.19.3.dmg             # Installer
├── HWSolutions10.2025.pdf             # Handwritten physics equations

~/Documents/Notes/Journals/
└── 2025-05-19.md                      # Markdown journal entry
```

**After:**

```bash
~/Documents/
├── Legal Documents/
│   ├── Receipts/
│   │   └── Nike_Return_Label_1ZXXXXXXXXXXXXXXX.pdf   # Renamed w/ tracking placeholder
│   └── Passport_Page_20250419.pdf                    # Archived passport scan
│
├── School/
│   └── 2025 Spring/
│       └── PHYS 311/
│           └── HW/
│               └── Homework_Solutions/
│                   ├── SolnsHmwk9_2025.pdf           # Existing solution file
│                   └── SolnsHmwk10_2025.pdf          # NEW — Renamed to match pattern
│
└── Notes/
    └── Journals/
        └── 2025-05-19.md                             # Recent journal — left in place

~/.Trash/
└── HttpToolkit-1.19.3.dmg                            # 3 months old installer — moved to Trash
```

```bash
$ aimv ~/Downloads/HWSolutions10.2025.pdf

Moved:
  From: /Users/<user>/Downloads/HWSolutions10.2025.pdf
    To: /Users/<user>/Documents/School/.../Homework_Solutions/SolnsHmwk10_2025.pdf

Move logged (ID: a3f8c1d2e456)
File indexed: SolnsHmwk10_2025.pdf
```

**Step 1:** Initial assessment notices it's a PDF in Downloads

**Step 2:** Content analysis identifies handwritten equations and diagrams — rule engine matches **academic** category

**Step 3:** Extracts keywords: "solutions, homework, physics, equations"

**Step 4:** Searches folders, finds matching homework solutions directory

**Step 5:** Examines existing files in target location for naming patterns

**Step 6:** Renames file to match pattern, maintaining consistency

**Step 7:** Logs the move and updates the file index

To undo this move later: `aimv undo --id a3f8c1d2e456`
`

Please give it a lot of thought and respond witha great working markdown file