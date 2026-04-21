# 5. Token System

### 5.1 Free Weekly Token
**User story**
As a user, I want a free weekly token.

**Acceptance criteria**
- When the week is locked all users are granted 1 additional token

---

### 5.2 Token Log *(admin)*
**User story**
As an admin, I want visibility into events that have granted tokens.

**Acceptance criteria**
- Weekly free token grants are shown with the total number of users affected
- Admin token grants are listed with time, granting admin, target user, and amount
- Other methods of obtaining tokens (draws, code redemptions) are logged as well

---

### 5.3 Spend Token to Draw Card
**User story**
As a user, I want to draw a card using a token.

**Acceptance criteria**
- 1 token deducted
- Card marked as owned by the user
- User cannot receive a card for a player they already have, unless they have cards from all players
- Card shown to user immediately in a reveal modal

---

### 5.4 Redeem Code
**User story**
As a user, I want to redeem a code.

**Acceptance criteria**
- Valid code grants tokens
- Invalid code shows an error
- One use per user
- Logged in the audit log

---

### 5.5 Re-roll Modifiers
**User story**
As a user, I want to spend a token to re-roll a card's stat modifiers so that I can try for a more useful modifier combination.

**Acceptance criteria**
- Costs 1 token per reroll; returns 409 if the user has no tokens
- All existing modifiers on the card are replaced with a freshly randomised set (same count and bonus rules as draw time)
- Card rarity, player, and league are unchanged — only modifiers are replaced
- Action is recorded in the audit log
- Frontend shows a confirmation prompt before spending the token
- Updated modifier list and remaining token balance are returned in the response
