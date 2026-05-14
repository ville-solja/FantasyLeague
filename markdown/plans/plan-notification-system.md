# Plan: Notification System

## Context
Admins need a way to broadcast a time-bounded message to all players — announcements,
rule changes, maintenance notices. Currently there is no in-app channel for this; admins
must use external comms. The notification appears as a one-time popup during the active
window: each player sees it once per login/page-load and it disappears after they
dismiss it or the window expires. The mechanism is intentionally close to the existing
Token Grant Event pattern (time-bounded, per-user claim guard). *Resolves GitHub issue #47.*

## User Stories

### View a Notification on Login
**User story**
As a logged-in player, I want to see an admin broadcast message once when I open the
app during the active window, so that I stay informed about important announcements.

**Acceptance criteria**
- A popup appears on page load if there is at least one active notification the player
  has not yet dismissed
- The popup shows the notification message and a "Dismiss" or close button
- Dismissing the popup marks the notification as seen; it does not reappear on subsequent
  page loads or logins during the same window
- Players who first open the app after the notification window has ended never see it
- Players who are not logged in do not see the popup

### Create and Manage Notifications (Admin)
**User story**
As an admin, I want to create a notification with a message, start time, and end time,
and be able to remove it before it expires, so that I can control what players see.

**Acceptance criteria**
- Admin panel shows a list of all notifications with message, window, and dismiss count
- Admin can create a notification: message (required, ≤ 500 chars), start\_time, end\_time
- `end_time` must be strictly after `start_time`; invalid input is rejected with a clear error
- Admin can delete a notification at any time; deletion stops future dismissals but does
  not undo existing ones
- Deleting a non-existent notification returns 404

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | Add `Notification` and `NotificationDismissal` models |
| `backend/routers/admin.py` | Add `GET/POST/DELETE /admin/notifications` |
| `backend/routers/auth.py` | Add `GET /notifications` (active, unseen) and `POST /notifications/{id}/dismiss` |
| `frontend/app-admin.js` | Notification management panel functions |
| `frontend/app-auth.js` | Fetch unseen notifications on load/login; show popup |
| `frontend/index.html` | Notification popup modal + admin panel section |

### Step 1 — Models

Add to `backend/models.py`:

```python
class Notification(Base):
    __tablename__ = "notifications"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    message    = Column(String)
    start_time = Column(Integer)   # Unix timestamp
    end_time   = Column(Integer)   # Unix timestamp
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(Integer)   # Unix timestamp


class NotificationDismissal(Base):
    __tablename__ = "notification_dismissals"
    __table_args__ = (UniqueConstraint("notification_id", "user_id",
                                       name="uq_dismissal_notif_user"),)

    id              = Column(Integer, primary_key=True, autoincrement=True)
    notification_id = Column(Integer, ForeignKey("notifications.id"))
    user_id         = Column(Integer, ForeignKey("users.id"))
    dismissed_at    = Column(Integer)   # Unix timestamp
```

### Step 2 — Admin endpoints

Add to `backend/routers/admin.py`:

```python
class NotificationBody(BaseModel):
    message:    str = Field(..., min_length=1, max_length=500)
    start_time: int
    end_time:   int

@router.get("/admin/notifications")
def list_notifications(db=Depends(get_db), _=Depends(require_admin)):
    rows = db.query(Notification).order_by(Notification.start_time.desc()).all()
    result = []
    for n in rows:
        count = db.query(NotificationDismissal).filter_by(notification_id=n.id).count()
        result.append({"id": n.id, "message": n.message,
                        "start_time": n.start_time, "end_time": n.end_time,
                        "dismiss_count": count})
    return result

@router.post("/admin/notifications")
def create_notification(body: NotificationBody, db=Depends(get_db),
                        admin=Depends(require_admin)):
    if body.end_time <= body.start_time:
        raise HTTPException(422, "end_time must be after start_time")
    n = Notification(message=body.message, start_time=body.start_time,
                     end_time=body.end_time, created_by=admin["user_id"],
                     created_at=int(time.time()))
    db.add(n); db.flush()
    _audit(db, "admin_notification_created", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"id={n.id}")
    db.commit()
    return {"id": n.id}

@router.delete("/admin/notifications/{notification_id}")
def delete_notification(notification_id: int, db=Depends(get_db),
                        admin=Depends(require_admin)):
    n = db.get(Notification, notification_id)
    if not n:
        raise HTTPException(404, "Notification not found")
    _audit(db, "admin_notification_deleted", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"id={n.id}")
    db.delete(n); db.commit()
    return {"ok": True}
```

### Step 3 — Player endpoints

Add to `backend/routers/auth.py`:

```python
@router.get("/notifications")
def get_active_notifications(db=Depends(get_db),
                             current_user=Depends(get_current_user)):
    now = int(time.time())
    active = db.query(Notification).filter(
        Notification.start_time <= now,
        Notification.end_time   >= now,
    ).all()
    seen_ids = {r.notification_id for r in
                db.query(NotificationDismissal)
                  .filter(NotificationDismissal.user_id == current_user["user_id"])
                  .all()}
    unseen = [{"id": n.id, "message": n.message} for n in active
              if n.id not in seen_ids]
    return unseen

@router.post("/notifications/{notification_id}/dismiss")
def dismiss_notification(notification_id: int, db=Depends(get_db),
                         current_user=Depends(get_current_user)):
    n = db.get(Notification, notification_id)
    if not n:
        raise HTTPException(404, "Notification not found")
    existing = db.query(NotificationDismissal).filter_by(
        notification_id=notification_id, user_id=current_user["user_id"]).first()
    if not existing:
        db.add(NotificationDismissal(notification_id=notification_id,
                                     user_id=current_user["user_id"],
                                     dismissed_at=int(time.time())))
        db.commit()
    return {"ok": True}
```

### Step 4 — Frontend popup

In `frontend/app-auth.js`, add after `claimTokenEvents()`:

```js
async function checkNotifications() {
  try {
    const res = await fetch(`${API}/notifications`);
    if (!res.ok) return;
    const items = await res.json();
    if (!items.length) return;
    showNotificationPopup(items[0]);  // show one at a time
  } catch (_) {}
}

function showNotificationPopup(notif) {
  document.getElementById("notifMessage").textContent = notif.message;
  document.getElementById("notifModal").classList.remove("hidden");
  document.getElementById("notifDismissBtn").onclick = async () => {
    await fetch(`${API}/notifications/${notif.id}/dismiss`, { method: "POST" });
    document.getElementById("notifModal").classList.add("hidden");
  };
}
```

Call `checkNotifications()` after `claimTokenEvents()` in `login()`, `register()`, and `init()`.

In `frontend/index.html`, add a notification modal (similar to `revealModal`):
```html
<div id="notifModal" class="modal-overlay hidden">
  <div class="modal" style="max-width:480px;">
    <p id="notifMessage" style="margin-bottom:16px;"></p>
    <button id="notifDismissBtn">Dismiss</button>
  </div>
</div>
```

### Step 5 — Admin panel

In `frontend/app-admin.js`, add `loadNotifications()`, `createNotification()`,
`deleteNotification()` following the same pattern as the Token Grant Events functions.

In `frontend/index.html`, add a "Notifications" panel to the admin tab alongside the
Token Grant Events panel. Fields: message textarea, start/end datetime pickers, Create
button. Table: message (truncated), start, end, dismiss count, Delete button.

Add `loadNotifications()` to the admin tab init in `frontend/app-globals.js`.

---

## Verification
- Create a notification with a window of ±5 minutes from now; log in as a player — popup appears
- Dismiss the popup; reload — popup does not reappear
- Log in as a second player — popup appears again (per-user)
- Delete the notification as admin; log in as a third player — no popup
- Create a notification with `end_time` in the past; log in — no popup
- Attempt to create a notification with `end_time <= start_time` — 422 returned
- Delete a non-existent notification ID — 404 returned
