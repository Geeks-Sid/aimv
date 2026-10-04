# Domain Docs

This is a single-context repository.

## Before Exploring

- Read `CONTEXT.md` at the repository root when it exists.
- Read relevant decisions under `docs/adr/` when that directory exists.
- If either location is absent, proceed silently. Producer workflows create domain
  documentation only when terms or decisions are resolved.

## Vocabulary

Use the canonical domain terms from `CONTEXT.md` in code, tests, plans, and issues.
Do not introduce synonyms that the glossary explicitly avoids. When a necessary domain
concept is missing, record the gap or update the glossary as part of resolving it.

## Architecture Decisions

Surface any conflict with an existing ADR explicitly instead of silently overriding it.
