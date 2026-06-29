# Mermaid Process Documentation

Visual Mermaid flowcharts documenting the Fantasy League system, intended for contributors
and operators who need a quick structural overview without reading all the source files.

---

## Diagrams

The diagrams live in [`markdown/process-diagrams.md`](../../process-diagrams.md) and cover
three areas:

| Diagram | Purpose |
|---|---|
| Season Lifecycle | Pre-season admin setup → weekly loop → season end; Twitch MVP side-flow; admin tools overlay |
| Token and Card Economy | All five token sources, three spend types, and the full card lifecycle from draw to locked-week scoring |
| Admin Tools Overview | All admin tab capabilities grouped by domain (players, weeks, comms, data, users) |

## Maintenance

Update `markdown/process-diagrams.md` when:

- A new token source or sink is added (e.g. a new grant mechanism)
- The card lifecycle changes (e.g. card expiry, new rarity rules)
- A new admin tool is added that doesn't fit an existing group
- The season lifecycle gains a materially new stage (e.g. post-season playoffs)

The diagrams do **not** need updating for changes that are internal to an existing node —
e.g. changing the booster draw cost from 3 to 2 tokens warrants updating the label but not
the structure.

## Rendering

Mermaid renders natively in GitHub markdown and in VS Code with the Mermaid Preview extension.
No build step or external tool is required.

---

*This document describes the documentation artefact. The diagrams themselves are in [`markdown/process-diagrams.md`](../../process-diagrams.md).*
