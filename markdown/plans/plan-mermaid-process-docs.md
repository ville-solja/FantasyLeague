# Plan: Mermaid Process Documentation

## Context
Contributors and operators currently have no visual overview of how the Fantasy League system
fits together — the lifecycle of a season, how tokens flow, or which admin actions happen at
which stage. Mermaid diagrams embedded in Markdown render natively on GitHub and are
maintainable alongside the code. This plan creates a single reference page
(`markdown/process-diagrams.md`) containing three diagrams: the season lifecycle, the token
and card economy, and an admin tools overview. The page is then linked from
`markdown/features/README.md` and the main `README.md`. *Resolves GitHub issue #72.*

## User Stories

### View a Season Lifecycle Diagram
**User story**
As a new contributor or operator, I want to see a single visual diagram of the season
lifecycle so that I can understand the pre-season setup and the recurring weekly loop without
reading all the source files.

**Acceptance criteria**
- A Mermaid `flowchart LR` diagram exists in `markdown/process-diagrams.md`
- It shows a distinct pre-season phase (player pool setup, league configuration, week creation)
- It shows the during-season weekly loop (ingest → score → lock → roster snapshot → repeat)
- It shows the MVP flow from Twitch stream through bonus application
- Admin tools are shown as a side group, not inline with the main flow

---

### View the Token and Card Economy Diagram
**User story**
As a developer working on scoring or draw logic, I want a visual map of all token sources and
sinks and the card lifecycle so that I can trace how tokens move through the system.

**Acceptance criteria**
- A second Mermaid diagram on the same page shows all token sources (initial allocation,
  promo code, token grant event, Twitch drop, player refund)
- It shows all token sinks (standard draw, booster draw, reroll)
- It shows the card lifecycle after a draw (activate vs bench, weekly scoring, swap window)
- The diagram is accurate — all sources and sinks match the current implementation

---

### Find Process Diagrams from the Documentation Index
**User story**
As any reader of the docs, I want the process diagrams to be discoverable from the main
documentation entry points so that I do not have to know they exist to find them.

**Acceptance criteria**
- `markdown/features/README.md` includes a link to `process-diagrams.md`
- The main `README.md` documentation section also links to `markdown/process-diagrams.md`
- The page title and file name are descriptive enough to be findable by search

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `markdown/process-diagrams.md` | New file — contains all three Mermaid diagrams |
| `markdown/features/README.md` | Add link to process-diagrams in the Reference table |
| `README.md` | Add link in the documentation section |

### Step 1 — Create `markdown/process-diagrams.md`

The file contains three sections with embedded Mermaid diagrams.

#### Diagram 1: Season Lifecycle

```mermaid
flowchart LR
    subgraph Pre["Pre-Season (Admin)"]
        direction TB
        P1[Add players to pool\nbulk CSV or one-by-one] --> P2[Configure league ID]
        P2 --> P3[Create weeks\nwith start/end times]
    end

    subgraph Weekly["Weekly Loop"]
        direction TB
        W1[Schedule published] --> W2[Matches played]
        W2 --> W3[Ingest from OpenDota\nauto every 15 min or manual]
        W3 --> W4[Fantasy scores calculated]
        W4 --> W5[Week locks\nat configured end time]
        W5 --> W6[Rosters snapshotted\nfor this week's scoring]
        W6 --> W7{More weeks?}
        W7 -->|Yes| W1
        W7 -->|No| END[Season leaderboard finalised]
    end

    subgraph Twitch["Each Match — Twitch"]
        direction TB
        T1[Live Twitch stream] --> T2[Broadcaster selects MVP]
        T2 --> T3[MVP bonus added\nto match fantasy score]
    end

    subgraph AdminTools["Admin Tools (always available)"]
        direction TB
        A1[Player pool:\nadd · bulk-add · remove]
        A2[Week management:\ncreate · edit · delete]
        A3[Data:\ningest · enrich profiles]
        A4[Weights:\nconfigure · recalculate]
    end

    Pre --> Weekly
    W2 -.->|stream running| T1
    T3 -.->|score enriched| W4
    AdminTools -.- Weekly
```

#### Diagram 2: Token and Card Economy

```mermaid
flowchart TD
    subgraph Sources["Token Sources"]
        direction LR
        S1[Registration\n5 tokens]
        S2[Promo code\nvariable]
        S3[Token grant event\nadmin-configured]
        S4[Twitch drop\nbroadcaster-triggered]
        S5[Player refund\n1 per deactivated card]
    end

    subgraph Spends["Token Spends"]
        direction LR
        D1[Standard draw\n1 token]
        D2[Booster draw\n3 tokens — team-locked]
        D3[Reroll modifiers\n1 token]
    end

    subgraph CardLife["Card Lifecycle"]
        direction TB
        C1[Card drawn] --> C2{Roster has\nfewer than 5?}
        C2 -->|Yes| C3[Auto-activated\nin lineup]
        C2 -->|No| C4[Goes to bench]
        C4 <-->|swap before lock| C3
        C3 --> C5[Scores in locked week\nfantasy points applied]
        C4 -. not scored .-> C5
    end

    Sources --> Spends
    D1 --> C1
    D2 --> C1
    D3 -->|new modifiers assigned| C3
```

### Step 2 — Update `markdown/features/README.md`

Add a row at the top of the Reference tier table:

```markdown
| [Process Diagrams](../process-diagrams.md) | Mermaid flowcharts: season lifecycle, token/card economy, admin tools overview |
```

### Step 3 — Update `README.md`

Add a link in the documentation section alongside the existing `markdown/features/` link:

```markdown
- [Process Diagrams](markdown/process-diagrams.md) — visual flowcharts of the season lifecycle and token/card economy
```

---

## Verification
- Open `markdown/process-diagrams.md` on GitHub — all three diagrams render without syntax errors
- The season lifecycle diagram shows pre-season → weekly loop → season end, with admin tools and Twitch as side groups
- The token diagram correctly lists all five token sources and three spend types from the current implementation
- Both `markdown/features/README.md` and `README.md` link to the file
- Running `grep -r "process-diagrams" markdown/` returns at least two files (README and features/README)
