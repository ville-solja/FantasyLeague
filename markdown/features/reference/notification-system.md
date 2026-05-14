# Notification System

Admin-configurable time-bounded broadcast messages that appear as a one-time popup for
each logged-in player during the active window.

---

## Overview

An admin creates a notification with a plain-text message, start time, and end time.
When a logged-in player loads the page or logs in, the backend returns any active
notifications they have not yet dismissed. The frontend shows one popup at a time; the
player dismisses it, recording a `NotificationDismissal` row that prevents it from
reappearing. Players who load the app after the window ends never see the notification.

---

## Endpoints

### `GET /admin/notifications` Returns all notifications ordered by start time descending. Each row includes
`dismiss_count` — number of players who have dismissed.

### `POST /admin/notifications` Body: `{ message: str, start_time: int, end_time: int }`. Admin only. Validates
`end_time > start_time` and `1 ≤ len(message) ≤ 500`. Returns `{ id }`.

### `DELETE /admin/notifications/{id}` Admin only. Deletes the notification. Existing dismissals are unaffected.

### `GET /notifications` Auth required. Returns active, unseen notifications for the calling user as
`[{ id, message }]`. Empty array if none.

### `POST /notifications/{id}/dismiss` Auth required. Records that the calling user has dismissed this notification.
Idempotent — repeated calls are safe.

---

## Data model

`notifications` — one row per notification (message, start_time, end_time, created_by).

`notification_dismissals` — one row per (notification_id, user_id) pair; unique
constraint prevents duplicates at the database level.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
