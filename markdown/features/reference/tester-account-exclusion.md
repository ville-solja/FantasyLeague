# Tester Account Exclusion

Allows admins to flag user accounts as testers so they are hidden from public leaderboards while remaining fully visible in the admin panel.

---

## Concept

Some accounts are created for development and QA purposes. Without explicit exclusion, these accounts appear in season and weekly standings, polluting the rankings with artificial data. The `is_tester` flag on the `User` model marks an account as non-participating. The flag is toggled by an admin and takes effect on all leaderboard reads.

## Endpoints

### `POST /users/{user_id}/toggle-tester`
Flips `is_tester` for the given user. Admin only (`Depends(require_admin)`). Returns `{ user_id, username, is_tester }`. The action is written to the audit log as `admin_toggle_tester`.

### `GET /users` (updated)
Now includes `is_tester: bool` in each user record alongside `id`, `username`, and `tokens`.

### `GET /leaderboard/season` (updated)
Excludes tester accounts via `WHERE u.is_tester = 0` added before `GROUP BY`.

### `GET /leaderboard/weekly` (updated)
Excludes tester accounts via `WHERE u.is_tester = 0` added before `GROUP BY`.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
