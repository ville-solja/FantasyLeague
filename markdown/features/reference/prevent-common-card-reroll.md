# Prevent Common Card Reroll

Blocks the Reroll Modifiers action for common-rarity cards, which carry no modifier stats
and would waste a token with no effect.

---

## Behaviour

Common cards (`card_type == "common"`) cannot be rerolled. The rule is enforced at two
layers:

**Backend** — `POST /roster/{card_id}/reroll` returns HTTP 400 with
`"Common cards cannot be rerolled"` before any token is deducted.

**Frontend** — The Reroll Modifiers button is hidden (`display: none`) when the card draw
modal opens for a common card. For rare, epic, and legendary cards the button behaves as
before: visible and enabled when the user has tokens, disabled otherwise.

---

## Endpoints

### `POST /roster/{card_id}/reroll`
Returns `400 Bad Request` with `{"detail": "Common cards cannot be rerolled"}` when
`card.card_type == "common"`. No token is deducted.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
