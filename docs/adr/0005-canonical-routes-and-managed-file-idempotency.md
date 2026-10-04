# Canonical routes are space-free and managed files are idempotent

Generated Area, Category, and Bucket directory names use lowercase, code-prefixed
kebab-case segments with no whitespace. Typed decision providers select these Canonical
Routes directly. Their Adapters validate each route against the Taxonomy and translate it
to a stable Bucket ID before returning a Classification Decision.

Any resolved path equal to or below the Managed Root is a Managed File. Classification
returns a local high-confidence `stay` without calling a provider. Organization Commit
repeats the ownership check before any prompt or mutation so stale or forged plans cannot
move a Managed File again. Resolved-path containment uses `commonpath`, not string prefixes,
and therefore handles symlink aliases without treating sibling names as managed.

Installed Folder Metadata may customize semantic fields—purpose, aliases, tags, include,
and exclude—but cannot replace structural identity or Canonical Routes. Legacy spaced
folders remain owned by the Managed Root and are not moved automatically; fresh
materialization uses Canonical Routes without deleting existing data.

For dated Buckets, Organization Commit deterministically appends `_YYYY` or `_YYYY-MM` to
the basename when its subject year is absent. This keeps naming consistent across Jev,
Laya, and generative providers while preserving extensions and existing dated names.
