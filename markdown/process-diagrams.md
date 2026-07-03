# Process Diagrams

Visual overviews of the Fantasy League system. All diagrams use [Mermaid](https://mermaid.js.org/) and render natively on GitHub.

---

## Season Lifecycle

Shows the full arc of a season: pre-season admin setup, the recurring weekly loop, and how the Twitch MVP flow connects to match scoring. Admin tools are shown as a side group — they are available throughout the season, not only at a specific stage.

```mermaid
flowchart LR
    subgraph Pre["Pre-Season (Admin)"]
        direction TB
        P1[Add players to pool] --> P2[Configure league ID]
        P2 --> P3[Create weeks]
    end

    subgraph Weekly["Weekly Loop"]
        direction TB
        W1[Schedule published] --> W2[Matches played]
        W2 --> W3[Ingest from OpenDota]
        W3 --> W4[Fantasy scores calculated]
        W4 --> W5[Week locks]
        W5 --> W6[Rosters snapshotted]
        W6 --> W7{More weeks?}
        W7 -->|Yes| W1
        W7 -->|No| END[Season leaderboard finalised]
    end

    subgraph Twitch["Each Match — Twitch"]
        direction TB
        T1[Live Twitch stream] --> T2[Broadcaster selects MVP]
        T2 --> T3[MVP bonus applied]
    end

    subgraph AdminTools["Admin Tools (always available)"]
        direction TB
        A1[Player pool]
        A2[Week management]
        A3[Data ingest & enrichment]
        A4[Weights & recalculate]
    end

    Pre --> Weekly
    W2 -.->|stream running| T1
    T3 -.->|score enriched| W4
    AdminTools -.- Weekly
```

---

## Token and Card Economy

Maps every token source and spend in the system, then traces what happens to a card after it is drawn.

```mermaid
flowchart TD
    subgraph Sources["Token Sources"]
        direction LR
        S1[Registration — 5 tokens]
        S2[Promo code]
        S3[Token grant event]
        S4[Twitch drop]
        S5[Player refund]
    end

    subgraph Spends["Token Spends"]
        direction LR
        D1[Standard draw — 1 token]
        D2[Booster draw — 3 tokens]
        D3[Reroll modifiers — 1 token]
    end

    subgraph CardLife["Card Lifecycle"]
        direction TB
        C1[Card drawn] --> C2{Roster under 5?}
        C2 -->|Yes| C3[Auto-activated]
        C2 -->|No| C4[Goes to bench]
        C4 <-->|swap before lock| C3
        C3 --> C5[Scores in locked week]
        C4 -. not scored .-> C5
    end

    Sources --> Spends
    D1 --> C1
    D2 --> C1
    D3 -->|new modifiers assigned| C3
```

---

## Admin Tools Overview

All admin actions available in the admin tab. These operate independently of the weekly schedule.

```mermaid
flowchart LR
    subgraph Players["Player Pool"]
        AP1[Add by OpenDota ID] & AP2[Bulk add via CSV] --> AP3[Player active in pool]
        AP3 --> AP4[Remove player — issues refunds]
        AP4 -.->|re-add later| AP3
    end

    subgraph Weeks["Week Management"]
        WM1[Create week] --> WM2[Edit unlocked week]
        WM2 --> WM3[Delete unlocked week]
        WM3 -.->|locks at end time| WM4[Locked week]
    end

    subgraph Comms["Communications"]
        C1[Notification]
        C2[Token grant event]
        C3[Promo code]
    end

    subgraph Data["Data & Scoring"]
        D1[Manual ingest]
        D2[Enrich profiles]
        D3[Recalculate]
        D4[Sync match weeks]
        D5[Sync Toornament]
    end

    subgraph Users["User Management"]
        U1[Grant tokens]
        U2[Toggle tester]
        U3[Manage tags]
        U4[Audit log]
    end
```
