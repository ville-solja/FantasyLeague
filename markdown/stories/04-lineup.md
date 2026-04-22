# 4. Active Lineup and Reserve Management

### 4.1 Place Cards into Active Slots
**User story**
As a user, I want to assign cards to the upcoming week's roster.

**Acceptance criteria**
- Upcoming week's roster has 5 slots
- User can move a card from bench to active roster (Activate)
- User can move a card from active roster to bench (Bench)
- Only one card may be active from a single player
- Roster changes are only allowed on the editable (upcoming) week, not on locked past weeks

---

### 4.2 Lock Active Cards
**User story**
As a user, I want cards to lock before the week begins.

**Acceptance criteria**
- Auto-lock every Sunday at end of day (UTC)
- UI indicates that the week is locked and shows a locked banner
- User is informed of the upcoming lock date on the My Team tab
- Locked roster is immutable and shown as a read-only snapshot

---

### 4.3 Admin Move Series Time Manually
**User story**
As an admin, I want to correct series timing when teams play out of the regular week cycle.

**Acceptance criteria**
- Ability to see series in the Admin tab
- Ability to select a series and input a corrected match date
- Corrected start date is persisted so that future ingestions do not override it

---

### 4.4 Preserve Points
**User story**
As a user, I want my points to persist across weeks.

**Acceptance criteria**
- Once a week has passed and is scored, the points for that week are stored in the DB
- Total points are derivable from past week records

---

### 4.5 View Past Week Snapshots
**User story**
As a user, I want to review my roster and points from any past week.

**Acceptance criteria**
- Week selector dropdown on the My Team tab lists all season weeks
- Selecting a past locked week shows the immutable roster snapshot for that week
- Weekly points shown reflect only matches played during that specific week
- Current editable roster is always accessible via the selector
