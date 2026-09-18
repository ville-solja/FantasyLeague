# Profile Requires Login

Gates `GET /profile/{user_id}` behind an authenticated session, closing an anonymous
user-enumeration vector — the entire user base could previously be scraped by iterating the
small sequential `user_id` with no login and no trail.

*(see `markdown/plans/plan-issue-120-profile-requires-login.md`, resolves GitHub issue #120)*

---

## The report

`GET /profile/{user_id}` (`backend/routers/profile.py`) had no authentication requirement at
all. Since `user_id` is a small sequential integer, every user's username, linked-Twitch
status, tags, and season history could be scraped anonymously by iterating IDs. No emails or
password data were ever exposed, but full user-base enumeration/profiling was possible with no
account and no rate limit specific to this route (issue #121's later `RATE_LIMIT_GLOBAL`
baseline does apply here, but that's a general floor, not something that made this endpoint's
public access intentional or sufficient on its own).

## Decision

The issue asked this repo to decide between keeping the endpoint public with added rate
limiting, or requiring login. Investigation found the answer already implied by actual usage:
`frontend/app-profile.js` is the *only* caller anywhere in the codebase (checked across
`frontend/*.js` and `twitch-extension/*.js`), and it only ever fetches the logged-in user's own
profile from within an authenticated session. Nothing relies on anonymous access, so gating
behind login has no impact on any real usage and fully closes the enumeration vector (rather
than just slowing it down).

## Fix

`GET /profile/{user_id}` now requires `Depends(get_current_user)` (`backend/routers/profile.py`)
— any authenticated account can still view any user's profile (not restricted to viewing only
your own), matching the endpoint's original intent minus anonymous access. `current_user` is
resolved for the auth check only; it is not read in the handler body. An unauthenticated request
now returns 401 instead of the profile data. Response shape and content for an authenticated
request are unchanged.

## Frontend impact

None. The one real call site already always runs inside an authenticated session.
