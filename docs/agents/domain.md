# Domain docs

## Layout

Single-context: root `GLOSSARY.md` and `docs/adr/`.

## Consumer rules

Before exploring a domain area, read `GLOSSARY.md` and any relevant ADRs
under `docs/adr/`. If absent, proceed silently; create documentation lazily
through domain-modeling when terminology or decisions are resolved.

Use glossary terms consistently in issues, proposals, hypotheses and tests.
If a needed term is missing, reconsider the wording or note the gap for
domain-modeling.

Explicitly identify any proposal that contradicts an existing ADR and
explain why the decision should be revisited.
