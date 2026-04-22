# 2. Initial Onboarding and Starter Tokens

### 2.1 Grant Starter Tokens on Registration
**User story**
As a newly registered user, I want to receive N tokens when I sign up so that I can start building my active lineup immediately.

**Acceptance criteria**
- N tokens are granted at registration (configurable via `INITIAL_TOKENS`)

---

### 2.2 Token Visibility
**User story**
As a user, I want to know how many tokens I currently have.

**Acceptance criteria**
- Token balance is visible in the header across all tabs
- Balance updates immediately after any token-changing event (draw, redeem, weekly grant)
- Token counter on the My Team tab stays in sync with the header balance

---

### 2.3 View Cards
**User story**
As a new user, I want to see the cards I have drawn in my bench and my roster.

**Acceptance criteria**
- Each drawn card displays player identity, rarity, and current week's points
- Cards are clearly shown as benched until placed into the weekly roster
- Cards drawn should be visible in the My Team tab

---

### 2.4 View Weekly Rosters
**User story**
As a new user, I want to see the upcoming week's roster.

**Acceptance criteria**
- Upcoming week's active roster is the default view
- It is clearly visible when the roster will be locked
- Empty active slots are shown explicitly so the user knows how many cards they can still add

---

### 2.5 View Current and Season Points
**User story**
As a user, I want to see my earned points for this week and the whole season.

**Acceptance criteria**
- Should be 0 for a new user with no participation
- Clearly visible in the My Team tab
- Two separate point pools: weekly and season
- Points and past rosters visible per week via the week history selector
