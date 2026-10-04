# AIMV File Organization

AIMV classifies unorganized files into a stable, human-readable managed taxonomy while
keeping model decisions separate from filesystem mutation.

## Language

### Organization

**Managed Root**:
The configured directory beneath which AIMV may create taxonomy folders and organize files.
_Avoid_: Destination root, output directory

**Managed File**:
A file whose resolved current path is the Managed Root or any descendant. A Managed File is never classified or moved again unless a future explicit reclassification workflow is requested.

**Taxonomy**:
The versioned hierarchy of Areas, Categories, and Buckets available beneath the Managed Root.
_Avoid_: Template, folder dump

**Area**:
A broad top-level division of the Taxonomy identified by a stable numeric code.

**Category**:
A navigational grouping of related Buckets inside one Area.
_Avoid_: Rule category, final destination

**Bucket**:
A leaf destination with a stable Bucket ID, readable path, semantic metadata, and time policy.
_Avoid_: Folder option, category

**Bucket ID**:
The stable identifier used in Classification Decisions independently of a Bucket's display title or filesystem path.
_Avoid_: Folder path

**Canonical Route**:
The validated, space-free relative path shown to a typed decision provider and resolved beneath the Managed Root. Provider Adapters convert it back to a Bucket ID before producing a Classification Decision.
_Avoid_: Suggested folder, absolute destination

**Folder Metadata**:
The hidden `.aimv-folder.yaml` record that makes a managed folder self-describing and searchable.

**Time Partition**:
A year or year/month folder derived beneath a Bucket from the subject date of a file.
_Avoid_: Model-generated subfolder

### Classification

**Evidence**:
The locally extracted filename, type, dates, content, image, archive state, and Rule hints for one file.

**Rule**:
Legacy category-specific guidance used to improve matching, naming, and metadata extraction.
_Avoid_: Bucket, Category

**Candidate Set**:
The small ranked selection of Buckets sent only to a generative fallback provider for one file.

**Decision Path**:
The complete Area → Category → Bucket sequence a typed decision provider traverses so every Bucket remains reachable without a flat 332-option choice.

**Classification Decision**:
A validated action, Bucket ID, filename, subject year/month, tags, confidence, and reasoning returned by a provider.
_Avoid_: Destination path

**Classification Plan**:
The immutable pairing of Evidence and a Classification Decision passed from a worker to the commit stage.

**Organization Commit**:
The controlled review, path resolution, filesystem move, log update, and index update for one Classification Plan.

## Relationships

- A **Taxonomy** contains sixteen **Areas**.
- An **Area** contains five to eight **Categories**.
- A **Category** contains four leaf **Buckets**.
- A **Bucket** has exactly one **Bucket ID** and one **Folder Metadata** record.
- A **Bucket** has one space-free **Canonical Route** made of code-prefixed kebab-case segments.
- A **Bucket** may contain many **Time Partitions**.
- A **Managed File** produces a local `stay` decision without crossing a provider Seam.
- Jev or Laya receives **Evidence** and traverses one **Decision Path** covering the complete **Taxonomy**.
- A generative fallback receives **Evidence** and one locally ranked **Candidate Set**.
- A typed provider chooses at most one **Canonical Route**; its Adapter validates that route and records the corresponding **Bucket ID** in a **Classification Decision**.
- A **Classification Plan** contains one file's **Evidence** and **Classification Decision**.
- An **Organization Commit** consumes one **Classification Plan**.

## Example Dialogue

> **Developer:** "Can Jev suggest an arbitrary destination?"
> **Domain expert:** "No. Jev selects one supplied **Canonical Route**. The provider Adapter validates it to a **Bucket ID**, and the **Organization Commit** resolves the final path and **Time Partition** beneath the **Managed Root**."

## Flagged Ambiguities

- "Category" previously meant both a Rule name and a destination. Resolved: **Rule** is
  legacy classification guidance; **Category** is a middle taxonomy level; **Bucket** is
  the destination.
- "Batch" can mean OpenAI's deferred Batch API or AIMV's interactive directory command.
  Resolved: AIMV uses **parallel classification** for the command and does not call the
  deferred provider Batch API.
