# Parallel classification with serialized commits

AIMV prepares evidence and requests Classification Decisions through a bounded worker
pool, then applies Organization Commits in original input order. Model and extraction
latency therefore overlap, while confirmation prompts, destination collision handling,
movement logs, and the file index remain deterministic and race-free. Filesystem commits
can be parallelized later only behind destination reservation and transactional persistence.
