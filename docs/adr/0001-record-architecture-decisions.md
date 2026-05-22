# 0001. Record Architecture Decisions

## Status

Accepted

## Context and Problem Statement

The Python Symphony implementation will make several foundational choices around language,
tooling, tracker bootstrap strategy, runner modes, and operational behavior. These decisions should
be visible in the repository so future contributors can understand why the project is shaped the way
it is.

## Decision Drivers

- Keep project history understandable without relying on chat context.
- Make implementation tradeoffs explicit.
- Allow decisions to evolve through superseding records.
- Use a lightweight format that works well in Markdown.

## Considered Options

- No ADRs.
- Free-form decision notes.
- MADR-format Architecture Decision Records.

## Decision Outcome

Use MADR-format ADRs under `docs/adr/`, numbered with four digits and a short kebab-case title.

## Consequences

- Important architecture decisions should be recorded before or alongside implementation.
- Superseded decisions should be replaced by new ADRs rather than silently rewritten.
- The repository gets a small amount of documentation overhead in exchange for clearer context.

## Links

- https://adr.github.io/madr/
