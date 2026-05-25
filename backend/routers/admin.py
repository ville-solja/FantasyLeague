import os
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, text

from database import get_db
from deps import get_current_user, require_admin, _audit
from enrich import run_enrichment, run_profile_enrichment
from ingest import ingest_league
from models import Match, PlayerMatchStats, PromoCode, CodeRedemption, User, Week, WeeklyRosterEntry, Weight, TokenGrantEvent, TokenGrantClaim, Notification, NotificationDismissal, TagDefinition, UserTag
from schedule import get_schedule, bust_cache, SCHEDULE_SHEET_URL
from scoring import fantasy_score
from toornament import sync_toornament_results

router = APIRouter()


class GrantTokensBody(BaseModel):
    target_user_id: int
    amount: int


class CreateCodeBody(BaseModel):
    code:         str = Field(min_length=1, max_length=64)
    token_amount: int


class RedeemCodeBody(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class MatchWeekBody(BaseModel):
    week_id: int | None = None


@router.post("/ingest/league/{league_id}")
def ingest_league_endpoint(league_id: int, db=Depends(get_db), admin: dict = Depends(require_admin)):
    ingest_league(league_id)
    run_enrichment()
    _audit(db, "admin_ingest", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"league_id={league_id}")
    db.commit()
    return {"status": "ok", "league_id": league_id}


@router.get("/users")
def list_users(db=Depends(get_db), _: dict = Depends(require_admin)):
    users = db.query(User).order_by(User.username).all()
    user_ids = [u.id for u in users]
    # Fetch all UserTag rows for these users in one query (avoid N+1)
    user_tags_rows = (
        db.query(UserTag, TagDefinition)
        .join(TagDefinition, TagDefinition.id == UserTag.tag_id)
        .filter(UserTag.user_id.in_(user_ids))
        .all()
    ) if user_ids else []
    tags_by_user: dict = {}
    for ut, td in user_tags_rows:
        tags_by_user.setdefault(ut.user_id, []).append(
            {"id": td.id, "key": td.key, "label": td.label}
        )
    return [
        {
            "id": u.id,
            "username": u.username,
            "tokens": u.tokens if u.tokens is not None else 0,
            "is_tester": bool(u.is_tester),
            "tags": tags_by_user.get(u.id, []),
        }
        for u in users
    ]


@router.post("/users/{user_id}/toggle-tester")
def toggle_tester(user_id: int, admin: dict = Depends(require_admin), db=Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_tester = not bool(user.is_tester)
    _audit(db, "admin_toggle_tester", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"{user.username} is_tester={user.is_tester}")
    db.commit()
    return {"user_id": user.id, "username": user.username, "is_tester": user.is_tester}


@router.post("/grant-tokens")
def grant_tokens(body: GrantTokensBody, db=Depends(get_db), admin: dict = Depends(require_admin)):
    target = db.get(User, body.target_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if body.amount < 1:
        raise HTTPException(status_code=422, detail="Amount must be at least 1")
    target.tokens = (target.tokens or 0) + body.amount
    _audit(db, "admin_grant_tokens", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"target={target.username} amount={body.amount}")
    db.commit()
    return {"username": target.username, "tokens": target.tokens}


@router.post("/recalculate")
def recalculate(db=Depends(get_db), admin: dict = Depends(require_admin)):
    weights = {w.key: w.value for w in db.query(Weight).all()}
    stats = db.query(PlayerMatchStats).all()
    for stat in stats:
        p = {
            "kills": stat.kills or 0,
            "deaths": stat.deaths or 0,
            "gold_per_min": stat.gold_per_min or 0,
            "obs_placed": stat.obs_placed or 0,
            "last_hits": stat.last_hits or 0,
            "denies": stat.denies or 0,
            "towers_killed": stat.towers_killed or 0,
            "roshan_kills": stat.roshan_kills or 0,
            "teamfight_participation": stat.teamfight_participation or 0.0,
            "camps_stacked": stat.camps_stacked or 0,
            "rune_pickups": stat.rune_pickups or 0,
            "firstblood_claimed": stat.firstblood_claimed or 0,
            "stuns": stat.stuns or 0.0,
        }
        stat.fantasy_points = fantasy_score(p, weights)
    bonus_pct = weights.get("mvp_bonus_pct", 10.0)
    for stat in stats:
        if stat.is_mvp:
            stat.fantasy_points = round(stat.fantasy_points * (1 + bonus_pct / 100), 4)
    _audit(db, "admin_recalculate", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"records={len(stats)}")
    db.commit()
    return {"status": "ok", "recalculated": len(stats)}


@router.get("/schedule")
def schedule_endpoint(db=Depends(get_db)):
    return get_schedule(db)


@router.post("/schedule/refresh")
def schedule_refresh(db=Depends(get_db), admin: dict = Depends(require_admin)):
    bust_cache()
    _audit(db, "admin_schedule_refresh", actor_id=admin["user_id"], actor_username=admin["username"])
    db.commit()
    return get_schedule(db)


@router.get("/schedule/debug")
def schedule_debug(_: dict = Depends(require_admin)):
    url = os.getenv("SCHEDULE_SHEET_URL", SCHEDULE_SHEET_URL)
    result = {"url_set": bool(url), "url_prefix": url[:60] + "..." if len(url) > 60 else url}

    if not url:
        result["error"] = "SCHEDULE_SHEET_URL is not set"
        return result

    try:
        import requests as req
        res = req.get(url, timeout=15, allow_redirects=True)
        result["status_code"] = res.status_code
        result["content_type"] = res.headers.get("content-type", "")
        result["response_length"] = len(res.text)
        result["first_200_chars"] = res.text[:200]
    except Exception as e:
        result["error"] = str(e)

    return result


@router.put("/matches/{match_id}/week")
def set_match_week(match_id: int, body: MatchWeekBody, db=Depends(get_db), admin: dict = Depends(require_admin)):
    """Manually override which fantasy week a match counts for.
    Set week_id to null to clear the override and revert to time-based assignment."""
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if body.week_id is not None:
        week = db.get(Week, body.week_id)
        if not week:
            raise HTTPException(status_code=404, detail="Week not found")
    old_override = match.week_override_id
    match.week_override_id = body.week_id
    _audit(db, "admin_set_match_week", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"match_id={match_id} old_override={old_override} new_override={body.week_id}")
    db.commit()
    return {"match_id": match_id, "week_override_id": body.week_id}


@router.post("/admin/sync-match-weeks")
def sync_match_weeks(db=Depends(get_db), admin: dict = Depends(require_admin)):
    """Auto-assign week_override_id on matches whose actual play date differs from their
    scheduled week in the Google Sheet."""
    db_weeks = db.query(Week).all()
    week_by_label = {w.label.lower().strip(): w for w in db_weeks}

    schedule_data = get_schedule(db)

    changes = []
    errors = []

    for sheet_week in schedule_data.get("weeks", []):
        week_label = (sheet_week.get("label") or "").lower().strip()
        target_week = week_by_label.get(week_label)
        if not target_week:
            errors.append(f"No DB week found for sheet label '{sheet_week.get('label')}'")
            continue

        for series in sheet_week["div1"] + sheet_week["div2"]:
            team1_id = series.get("team1_id")
            team2_id = series.get("team2_id")
            if not team1_id or not team2_id:
                continue

            series_ts = None
            dt_iso = series.get("datetime_iso")
            if dt_iso:
                try:
                    from datetime import datetime
                    series_ts = int(datetime.fromisoformat(dt_iso).timestamp())
                except (ValueError, OSError):
                    pass

            rows = db.execute(text("""
                SELECT match_id, start_time, week_override_id FROM matches
                WHERE (radiant_team_id = :a AND dire_team_id = :b)
                   OR (radiant_team_id = :b AND dire_team_id = :a)
            """), {"a": team1_id, "b": team2_id}).fetchall()

            for row in rows:
                if series_ts and row.start_time:
                    if abs(row.start_time - series_ts) > 3 * 86400:
                        continue

                in_target_by_time = (
                    row.start_time is not None
                    and target_week.start_time <= row.start_time <= target_week.end_time
                )
                new_override = None if in_target_by_time else target_week.id

                if new_override == row.week_override_id:
                    continue

                match_obj = db.get(Match, row.match_id)
                old = match_obj.week_override_id
                match_obj.week_override_id = new_override
                changes.append({
                    "match_id": row.match_id,
                    "old_override": old,
                    "new_override": new_override,
                    "target_week": target_week.label,
                    "teams": f"{series.get('team1')} vs {series.get('team2')}",
                })

    if changes:
        _audit(db, "admin_sync_match_weeks", actor_id=admin["user_id"], actor_username=admin["username"],
               detail=f"changes={len(changes)}")
        db.commit()

    return {"changes": changes, "errors": errors}


@router.post("/admin/sync-toornament")
def admin_sync_toornament(db=Depends(get_db), admin: dict = Depends(require_admin)):
    """Push current series results to toornament.com. Idempotent — safe to call repeatedly."""
    result = sync_toornament_results(db)
    _audit(db, "admin_sync_toornament", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"pushed={result['pushed']} skipped={result['skipped']} errors={len(result['errors'])}")
    db.commit()
    return result


@router.post("/admin/enrich-profiles")
def admin_enrich_profiles(db=Depends(get_db), admin: dict = Depends(require_admin)):
    result = run_profile_enrichment()
    _audit(db, "admin_enrich_profiles", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"enriched={result['enriched']} skipped={result['skipped']} errors={result['errors']}")
    db.commit()
    return result



@router.post("/codes")
def create_code(body: CreateCodeBody, db=Depends(get_db), admin: dict = Depends(require_admin)):
    code = body.code.strip().upper()
    if not code:
        raise HTTPException(status_code=422, detail="Code cannot be empty")
    if body.token_amount < 1:
        raise HTTPException(status_code=422, detail="Token amount must be at least 1")
    if db.query(PromoCode).filter(PromoCode.code == code).first():
        raise HTTPException(status_code=409, detail="Code already exists")
    promo = PromoCode(code=code, token_amount=body.token_amount, created_by_id=admin["user_id"])
    db.add(promo)
    _audit(db, "admin_code_create", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"code={code} tokens={body.token_amount}")
    db.commit()
    return {"id": promo.id, "code": promo.code, "token_amount": promo.token_amount}


@router.get("/codes")
def list_codes(db=Depends(get_db), _: dict = Depends(require_admin)):
    rows = db.execute(text("""
        SELECT p.id, p.code, p.token_amount, COUNT(r.id) as redemptions
        FROM promo_codes p
        LEFT JOIN code_redemptions r ON r.code_id = p.id
        GROUP BY p.id, p.code, p.token_amount
        ORDER BY p.id
    """)).fetchall()
    return [{"id": r.id, "code": r.code, "token_amount": r.token_amount,
             "redemptions": r.redemptions} for r in rows]


@router.delete("/codes/{code_id}")
def delete_code(code_id: int, db=Depends(get_db), admin: dict = Depends(require_admin)):
    promo = db.get(PromoCode, code_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Code not found")
    _audit(db, "admin_code_delete", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"code={promo.code}")
    db.delete(promo)
    db.commit()
    return {"status": "ok"}


@router.post("/redeem")
def redeem_code(body: RedeemCodeBody, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    code = body.code.strip().upper()
    promo = db.query(PromoCode).filter(PromoCode.code == code).first()
    if not promo:
        raise HTTPException(status_code=404, detail="Invalid code")
    already = db.query(CodeRedemption).filter(
        CodeRedemption.code_id == promo.id,
        CodeRedemption.user_id == user_id,
    ).first()
    if already:
        raise HTTPException(status_code=409, detail="Code already redeemed")
    user.tokens = (user.tokens or 0) + promo.token_amount
    db.add(CodeRedemption(code_id=promo.id, user_id=user_id, redeemed_at=int(time.time())))
    _audit(db, "token_redeem", actor_id=user_id, actor_username=user.username,
           detail=f"code={promo.code} granted={promo.token_amount}")
    db.commit()
    return {"tokens": user.tokens, "granted": promo.token_amount}


class TokenGrantEventBody(BaseModel):
    amount:     int = Field(..., ge=1)
    start_time: int
    end_time:   int


@router.get("/admin/token-grant-events")
def list_token_grant_events(db=Depends(get_db), _: dict = Depends(require_admin)):
    events = db.query(TokenGrantEvent).order_by(TokenGrantEvent.start_time.desc()).all()
    claim_counts = {
        row[0]: row[1]
        for row in db.query(TokenGrantClaim.event_id, func.count(TokenGrantClaim.id))
                     .group_by(TokenGrantClaim.event_id).all()
    }
    return [
        {
            "id": ev.id, "amount": ev.amount,
            "start_time": ev.start_time, "end_time": ev.end_time,
            "created_at": ev.created_at, "claim_count": claim_counts.get(ev.id, 0),
        }
        for ev in events
    ]


@router.post("/admin/token-grant-events")
def create_token_grant_event(
    body: TokenGrantEventBody,
    db=Depends(get_db),
    admin: dict = Depends(require_admin),
):
    if body.end_time <= body.start_time:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")
    ev = TokenGrantEvent(
        amount=body.amount,
        start_time=body.start_time,
        end_time=body.end_time,
        created_by=admin["user_id"],
        created_at=int(time.time()),
    )
    db.add(ev)
    db.flush()
    _audit(db, "admin_token_grant_event_created", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"id={ev.id} amount={ev.amount} start={ev.start_time} end={ev.end_time}")
    db.commit()
    return {"id": ev.id, "amount": ev.amount, "start_time": ev.start_time, "end_time": ev.end_time}


@router.delete("/admin/token-grant-events/{event_id}")
def delete_token_grant_event(
    event_id: int,
    db=Depends(get_db),
    admin: dict = Depends(require_admin),
):
    ev = db.get(TokenGrantEvent, event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    _audit(db, "admin_token_grant_event_deleted", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"id={ev.id} amount={ev.amount}")
    db.delete(ev)
    db.commit()
    return {"ok": True}


class WeekCreateBody(BaseModel):
    label:      str = Field(..., min_length=1, max_length=64)
    start_time: int
    end_time:   int


class WeekEditBody(BaseModel):
    label:      str | None = Field(None, min_length=1, max_length=64)
    start_time: int | None = None
    end_time:   int | None = None


@router.get("/admin/weeks")
def list_weeks_admin(db=Depends(get_db), _: dict = Depends(require_admin)):
    weeks = db.query(Week).order_by(Week.start_time).all()
    roster_counts = {
        row[0]: row[1]
        for row in db.query(WeeklyRosterEntry.week_id, func.count(WeeklyRosterEntry.id))
                     .group_by(WeeklyRosterEntry.week_id).all()
    }
    return [
        {
            "id": w.id, "label": w.label,
            "start_time": w.start_time, "end_time": w.end_time,
            "is_locked": w.is_locked, "roster_count": roster_counts.get(w.id, 0),
        }
        for w in weeks
    ]


@router.post("/admin/weeks")
def create_week(body: WeekCreateBody, db=Depends(get_db),
                admin: dict = Depends(require_admin)):
    if body.end_time <= body.start_time:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")
    w = Week(label=body.label, start_time=body.start_time,
             end_time=body.end_time, is_locked=False)
    db.add(w)
    db.flush()
    _audit(db, "admin_week_created", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"id={w.id} label={w.label} end_time={w.end_time}")
    db.commit()
    return {"id": w.id, "label": w.label,
            "start_time": w.start_time, "end_time": w.end_time}


@router.patch("/admin/weeks/{week_id}")
def edit_week(week_id: int, body: WeekEditBody, db=Depends(get_db),
              admin: dict = Depends(require_admin)):
    w = db.get(Week, week_id)
    if not w:
        raise HTTPException(status_code=404, detail="Week not found")
    if w.is_locked:
        raise HTTPException(status_code=409, detail="Cannot edit a locked week")
    if body.label is not None:
        w.label = body.label
    if body.start_time is not None:
        w.start_time = body.start_time
    if body.end_time is not None:
        w.end_time = body.end_time
    if w.end_time <= w.start_time:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")
    _audit(db, "admin_week_edited", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"id={w.id} label={w.label} end_time={w.end_time}")
    db.commit()
    return {"id": w.id, "label": w.label,
            "start_time": w.start_time, "end_time": w.end_time}


@router.delete("/admin/weeks/{week_id}")
def delete_week(week_id: int, db=Depends(get_db),
                admin: dict = Depends(require_admin)):
    w = db.get(Week, week_id)
    if not w:
        raise HTTPException(status_code=404, detail="Week not found")
    if w.is_locked:
        raise HTTPException(status_code=409, detail="Cannot delete a locked week")
    roster_count = db.query(WeeklyRosterEntry).filter_by(week_id=week_id).count()
    if roster_count > 0:
        raise HTTPException(status_code=409,
                            detail="Cannot delete a week that has roster entries")
    _audit(db, "admin_week_deleted", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"id={w.id} label={w.label}")
    db.delete(w)
    db.commit()
    return {"ok": True}


class NotificationBody(BaseModel):
    message:    str = Field(..., min_length=1, max_length=500)
    start_time: int
    end_time:   int


@router.get("/admin/notifications")
def list_notifications(db=Depends(get_db), _: dict = Depends(require_admin)):
    rows = db.query(Notification).order_by(Notification.start_time.desc()).all()
    dismiss_counts = {
        row[0]: row[1]
        for row in db.query(NotificationDismissal.notification_id, func.count(NotificationDismissal.id))
                     .group_by(NotificationDismissal.notification_id).all()
    }
    return [
        {"id": n.id, "message": n.message,
         "start_time": n.start_time, "end_time": n.end_time,
         "dismiss_count": dismiss_counts.get(n.id, 0)}
        for n in rows
    ]


@router.post("/admin/notifications")
def create_notification(body: NotificationBody, db=Depends(get_db),
                        admin: dict = Depends(require_admin)):
    if body.end_time <= body.start_time:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")
    n = Notification(message=body.message, start_time=body.start_time,
                     end_time=body.end_time, created_by=admin["user_id"],
                     created_at=int(time.time()))
    db.add(n)
    db.flush()
    _audit(db, "admin_notification_created", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"id={n.id}")
    db.commit()
    return {"id": n.id}


@router.delete("/admin/notifications/{notification_id}")
def delete_notification(notification_id: int, db=Depends(get_db),
                        admin: dict = Depends(require_admin)):
    n = db.get(Notification, notification_id)
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    _audit(db, "admin_notification_deleted", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"id={n.id}")
    db.delete(n)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Tag definitions CRUD
# ---------------------------------------------------------------------------

class TagBody(BaseModel):
    key:   str = Field(..., min_length=1, max_length=50)
    label: str = Field(..., min_length=1, max_length=100)


@router.get("/admin/tags")
def list_tags(db=Depends(get_db), _=Depends(require_admin)):
    return [{"id": t.id, "key": t.key, "label": t.label}
            for t in db.query(TagDefinition).order_by(TagDefinition.key).all()]


@router.post("/admin/tags")
def create_tag(body: TagBody, db=Depends(get_db), admin=Depends(require_admin)):
    if db.query(TagDefinition).filter_by(key=body.key).first():
        raise HTTPException(status_code=409, detail="Tag key already exists")
    tag = TagDefinition(key=body.key, label=body.label, created_at=int(time.time()))
    db.add(tag)
    db.flush()
    _audit(db, "admin_tag_definition_created", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"key={body.key}")
    db.commit()
    return {"id": tag.id}


@router.delete("/admin/tags/{tag_id}")
def delete_tag(tag_id: int, db=Depends(get_db), admin=Depends(require_admin)):
    tag = db.get(TagDefinition, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    db.query(UserTag).filter_by(tag_id=tag_id).delete()
    _audit(db, "admin_tag_definition_deleted", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"key={tag.key}")
    db.delete(tag)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# User tag grant / revoke
# ---------------------------------------------------------------------------

@router.post("/admin/users/{user_id}/tags/{tag_id}")
def grant_tag(user_id: int, tag_id: int, db=Depends(get_db), admin=Depends(require_admin)):
    if not db.get(User, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    tag = db.get(TagDefinition, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    existing = db.query(UserTag).filter_by(user_id=user_id, tag_id=tag_id).first()
    if not existing:
        db.add(UserTag(user_id=user_id, tag_id=tag_id,
                       granted_by=admin["user_id"], granted_at=int(time.time())))
        _audit(db, "admin_tag_grant", actor_id=admin["user_id"],
               actor_username=admin["username"],
               detail=f"user_id={user_id} tag={tag.key}")
        db.commit()
    return {"ok": True}


@router.delete("/admin/users/{user_id}/tags/{tag_id}")
def revoke_tag(user_id: int, tag_id: int, db=Depends(get_db), admin=Depends(require_admin)):
    row = db.query(UserTag).filter_by(user_id=user_id, tag_id=tag_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="User does not have this tag")
    tag = db.get(TagDefinition, tag_id)
    _audit(db, "admin_tag_revoke", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"user_id={user_id} tag={tag.key}")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/audit-logs")
def get_audit_logs(db=Depends(get_db), limit: int = 200, _: dict = Depends(require_admin)):
    rows = db.execute(text("""
        SELECT id, timestamp, actor_username, action, detail
        FROM audit_logs
        ORDER BY id DESC
        LIMIT :limit
    """), {"limit": limit}).fetchall()
    return [dict(r._mapping) for r in rows]
