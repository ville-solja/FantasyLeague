# 6. Scoring and Points

### 6.1 Score Active Cards
**Acceptance criteria**
- Uses Dota 2 match data
- Only active (locked) cards score
- No double counting

---

### 6.2 Card Modifier Scoring
**Acceptance criteria**
- Rarity bonus applied on top of raw fantasy points (common +0%, rare +1%, epic +2%, legendary +3% by default)
- Rarity modifiers are configurable environment variables

---

### 6.3 Track Season Points
**Acceptance criteria**
- Persistent total score per user across all locked weeks
- Visible to user on the My Team tab and leaderboard

---

### 6.4 Track Points per Card
**Acceptance criteria**
- Per-week card point contribution visible in the week snapshot view
- Historical tracking via the week selector

---

### 6.5 Prevent Duplicate Scoring
**Acceptance criteria**
- Match events uniquely tracked
- Safe to retry ingestion — already-stored records are not duplicated
