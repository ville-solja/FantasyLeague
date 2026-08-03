import datetime
import os
import secrets
import time
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, text

import clock
from auth import hash_password
from database import get_db, backup_sqlite_db
from deps import get_current_user, require_admin, _audit
from enrich import run_enrichment, run_profile_enrichment
from ingest import ingest_league
from models import Card, CardModifier, League, Match, MatchBan, Player, PlayerMatchStats, PromoCode, CodeRedemption, SeasonArchive, Team, TwitchMVP, TwitchTokenDrop, User, Week, WeeklyRosterEntry, Weight, TokenGrantEvent, TokenGrantClaim, Notification, NotificationDismissal, TagDefinition, UserTag
from opendota_client import OPEN_DOTA_URL, get_json as opendota_get_json
from routers.cards import draw_card
from routers.leaderboard import compute_season_standings
from schedule import get_schedule, bust_cache, SCHEDULE_SHEET_URL
from scoring import fantasy_score
from toornament import sync_toornament_results
from weeks import auto_lock_weeks

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
    start_time: int | None = None
    end_time:   int | None = None
    start_date: str | None = Field(None, min_length=10, max_length=10)  # ISO date YYYY-MM-DD
    end_date:   str | None = Field(None, min_length=10, max_length=10)  # ISO date YYYY-MM-DD


class WeekEditBody(BaseModel):
    label:      str | None = Field(None, min_length=1, max_length=64)
    start_time: int | None = None
    end_time:   int | None = None
    start_date: str | None = Field(None, min_length=10, max_length=10)  # ISO date YYYY-MM-DD
    end_date:   str | None = Field(None, min_length=10, max_length=10)  # ISO date YYYY-MM-DD


def _derive_week_times(start_date: str | None, end_date: str | None) -> tuple[int | None, int | None]:
    """Derive week timestamps from date-only inputs.

    start_time = start_date 00:00:00 UTC
    end_time   = (end_date + 1 day) 03:00:00 UTC — matches running past
                 midnight still count toward the week.
    """
    start_time = end_time = None
    try:
        if start_date:
            d = datetime.date.fromisoformat(start_date)
            start_time = int(datetime.datetime(
                d.year, d.month, d.day, 0, 0, 0,
                tzinfo=datetime.timezone.utc).timestamp())
        if end_date:
            d = datetime.date.fromisoformat(end_date) + datetime.timedelta(days=1)
            end_time = int(datetime.datetime(
                d.year, d.month, d.day, 3, 0, 0,
                tzinfo=datetime.timezone.utc).timestamp())
    except ValueError:
        raise HTTPException(status_code=422,
                            detail="Dates must be ISO format (YYYY-MM-DD)")
    return start_time, end_time


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
    date_start, date_end = _derive_week_times(body.start_date, body.end_date)
    start_time = date_start if date_start is not None else body.start_time
    end_time   = date_end   if date_end   is not None else body.end_time
    if start_time is None or end_time is None:
        raise HTTPException(status_code=422,
                            detail="Provide start/end as dates or timestamps")
    if end_time <= start_time:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")
    w = Week(label=body.label, start_time=start_time,
             end_time=end_time, is_locked=False)
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
    date_start, date_end = _derive_week_times(body.start_date, body.end_date)
    if body.label is not None:
        w.label = body.label
    if date_start is not None:
        w.start_time = date_start
    elif body.start_time is not None:
        w.start_time = body.start_time
    if date_end is not None:
        w.end_time = date_end
    elif body.end_time is not None:
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


# ---------------------------------------------------------------------------
# Player Pool Management
# ---------------------------------------------------------------------------

class AddPlayerBody(BaseModel):
    player_id: int


class BulkAddPlayersBody(BaseModel):
    player_ids: str = Field(..., min_length=1, max_length=2000)  # CSV string


class RemovePlayersBody(BaseModel):
    player_ids: List[int]


@router.get("/admin/players")
def list_players(db=Depends(get_db), _=Depends(require_admin)):
    # Same name/avatar/team identity as GET /players (public Players tab) — team
    # is each player's most recent match's team, not a static assignment.
    rows = db.execute(text("""
        SELECT p.id, p.name, p.avatar_url, p.is_active,
               t.id as team_id, t.name as team_name
        FROM players p
        LEFT JOIN (
            SELECT s2.player_id, s2.team_id
            FROM player_match_stats s2
            INNER JOIN (
                SELECT player_id, MAX(match_id) as max_match
                FROM player_match_stats
                GROUP BY player_id
            ) mx ON mx.player_id = s2.player_id AND mx.max_match = s2.match_id
        ) latest ON latest.player_id = p.id
        LEFT JOIN teams t ON t.id = latest.team_id
        ORDER BY p.name
    """)).fetchall()
    card_counts = {
        r[0]: r[1] for r in
        db.query(Card.player_id, func.count(Card.id))
          .filter(Card.is_active == True)
          .group_by(Card.player_id).all()
    }
    return [
        {
            "id": r.id, "name": r.name, "avatar_url": r.avatar_url,
            "team_id": r.team_id, "team_name": r.team_name,
            "is_active": r.is_active,
            "active_card_count": card_counts.get(r.id, 0),
        }
        for r in rows
    ]


@router.post("/admin/players")
def add_player(body: AddPlayerBody, db=Depends(get_db), admin=Depends(require_admin)):
    existing = db.get(Player, body.player_id)
    if existing and existing.is_active:
        raise HTTPException(status_code=409, detail="Player already exists in pool")
    result = opendota_get_json(f"{OPEN_DOTA_URL}/players/{body.player_id}",
                               label=f"player {body.player_id}")
    if not result or not result.get("profile"):
        raise HTTPException(status_code=422, detail="Player not found on OpenDota")
    data = result["profile"]
    if existing:
        existing.is_active = True
        existing.name = data.get("personaname", str(body.player_id))
        existing.avatar_url = data.get("avatarfull", "")
        p = existing
    else:
        p = Player(
            id=body.player_id,
            name=data.get("personaname", str(body.player_id)),
            avatar_url=data.get("avatarfull", ""),
            is_active=True,
        )
        db.add(p)
    _audit(db, "admin_player_added", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"player_id={body.player_id}")
    db.commit()
    return {"id": p.id, "name": p.name}


@router.post("/admin/players/bulk")
def bulk_add_players(body: BulkAddPlayersBody, db=Depends(get_db),
                     admin=Depends(require_admin)):
    raw_ids = [s.strip() for s in body.player_ids.split(",") if s.strip()]
    added, skipped = [], []
    for raw in raw_ids:
        try:
            pid = int(raw)
        except ValueError:
            skipped.append({"id": raw, "reason": "not an integer"})
            continue
        if db.get(Player, pid):
            skipped.append({"id": pid, "reason": "already exists"})
            continue
        result = opendota_get_json(f"{OPEN_DOTA_URL}/players/{pid}", label=f"player {pid}")
        if not result or not result.get("profile"):
            skipped.append({"id": pid, "reason": "not found on OpenDota"})
            continue
        data = result["profile"]
        db.add(Player(
            id=pid,
            name=data.get("personaname", str(pid)),
            avatar_url=data.get("avatarfull", ""),
            is_active=True,
        ))
        added.append(pid)
    if added:
        _audit(db, "admin_player_bulk_added", actor_id=admin["user_id"],
               actor_username=admin["username"], detail=f"added={len(added)}")
    db.commit()
    return {"added": len(added), "skipped": skipped}


@router.post("/admin/players/remove")
def remove_players(body: RemovePlayersBody, db=Depends(get_db),
                   admin=Depends(require_admin)):
    for pid in body.player_ids:
        player = db.get(Player, pid)
        if not player or not player.is_active:
            continue
        player.is_active = False
        cards = db.query(Card).filter(Card.player_id == pid).all()
        refund_totals: dict = {}
        for card in cards:
            card.is_active = False
            refund_totals[card.owner_id] = refund_totals.get(card.owner_id, 0) + 1
        for user_id, token_count in refund_totals.items():
            user = db.get(User, user_id)
            if user:
                user.tokens = (user.tokens or 0) + token_count
                _audit(db, "admin_player_refund_issued", actor_id=admin["user_id"],
                       actor_username=admin["username"],
                       detail=f"player_id={pid} user_id={user_id} tokens={token_count}")
        _audit(db, "admin_player_removed", actor_id=admin["user_id"],
               actor_username=admin["username"], detail=f"player_id={pid}")
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# League Management
# ---------------------------------------------------------------------------

@router.get("/admin/leagues")
def list_leagues(db=Depends(get_db), admin=Depends(require_admin)):
    leagues = db.query(League).all()
    match_counts = {
        r[0]: r[1] for r in
        db.query(Match.league_id, func.count(Match.match_id))
          .group_by(Match.league_id).all()
    }
    return [
        {
            "id": l.id,
            "name": l.name or "(unknown)",
            "is_monitored": l.is_monitored,
            "match_count": match_counts.get(l.id, 0),
        }
        for l in leagues
    ]


@router.post("/admin/leagues/{league_id}/monitor")
def add_monitored_league(league_id: int, db=Depends(get_db), admin=Depends(require_admin)):
    league = db.get(League, league_id)
    if league and league.is_monitored:
        raise HTTPException(status_code=409, detail="League is already monitored")
    if not league:
        league = League(id=league_id, name="(pending ingest)", is_monitored=True)
        db.add(league)
    else:
        league.is_monitored = True
    _audit(db, "admin_league_add_monitor", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"league_id={league_id}")
    db.commit()
    return {"status": "ok", "league_id": league_id}


@router.delete("/admin/leagues/{league_id}/monitor")
def remove_monitored_league(league_id: int, db=Depends(get_db), admin=Depends(require_admin)):
    league = db.get(League, league_id)
    if not league or not league.is_monitored:
        raise HTTPException(status_code=404, detail="League is not currently monitored")
    league.is_monitored = False
    _audit(db, "admin_league_remove_monitor", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"league_id={league_id}")
    db.commit()
    return {"status": "ok", "league_id": league_id}


@router.delete("/admin/leagues/{league_id}/data")
def purge_league_data(league_id: int, db=Depends(get_db), admin=Depends(require_admin)):
    match_ids = [r[0] for r in db.execute(
        text("SELECT match_id FROM matches WHERE league_id = :lid"), {"lid": league_id}
    ).fetchall()]
    deleted_stats = 0
    deleted_bans = 0
    if match_ids:
        deleted_stats = (
            db.query(PlayerMatchStats)
            .filter(PlayerMatchStats.match_id.in_(match_ids))
            .delete(synchronize_session=False)
        )
        deleted_bans = (
            db.query(MatchBan)
            .filter(MatchBan.match_id.in_(match_ids))
            .delete(synchronize_session=False)
        )
    deleted_matches = (
        db.query(Match)
        .filter(Match.league_id == league_id)
        .delete(synchronize_session=False)
    )
    league = db.get(League, league_id)
    if league:
        league.is_monitored = False
    _audit(db, "admin_league_purge", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"league_id={league_id} matches={deleted_matches} stats={deleted_stats}")
    db.commit()
    return {
        "status": "ok",
        "league_id": league_id,
        "deleted_matches": deleted_matches,
        "deleted_stats": deleted_stats,
        "deleted_bans": deleted_bans,
        "note": "Run /recalculate to refresh fantasy scores after purge",
    }


# ---------------------------------------------------------------------------
# Season lifecycle — End Season archive + Season Reset
# ---------------------------------------------------------------------------

class SeasonEndBody(BaseModel):
    season_label: str = Field(..., min_length=1, max_length=100)


class SeasonResetBody(BaseModel):
    force: bool = False


@router.post("/admin/season/end")
def end_season(body: SeasonEndBody, db=Depends(get_db),
               admin: dict = Depends(require_admin)):
    """Snapshot the current season leaderboard into season_archive.

    Run this BEFORE a season reset — standings are computed live from match
    stats and are destroyed by the reset.
    """
    season_label = body.season_label.strip()
    if not season_label:
        raise HTTPException(status_code=422, detail="Season label cannot be empty")
    existing = (db.query(SeasonArchive)
                .filter(SeasonArchive.season_label == season_label).first())
    if existing:
        raise HTTPException(status_code=409,
                            detail=f"Season '{season_label}' is already archived")
    standings = compute_season_standings(db)
    now = int(time.time())
    for rank, row in enumerate(standings, start=1):
        db.add(SeasonArchive(
            season_label=season_label,
            user_id=row["id"],
            username=row["username"],
            points=row["points"],
            rank=rank,
            archived_at=now,
        ))
    _audit(db, "admin_season_archived", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"season_label={season_label} users={len(standings)}")
    db.commit()
    return {"season_label": season_label, "archived_users": len(standings)}


@router.post("/admin/season/reset")
def reset_season(body: SeasonResetBody, db=Depends(get_db),
                 admin: dict = Depends(require_admin)):
    """Clear all per-season data so the next season starts from a clean slate.

    Deletes matches, stats, bans, weeks, roster snapshots, Twitch season
    records, all known players and teams, and every user's cards; resets
    user tokens to INITIAL_TOKENS; unmonitors all leagues. User accounts,
    tags, audit logs, and season archives are retained.

    Players and teams are wiped along with match data — this also clears the
    admin-curated Player Pool, so a new season (or a new league entirely)
    starts with an empty draft pool that the admin repopulates via Player
    Management. Cards are deleted outright rather than deactivated: player
    rosters fluctuate season to season, so keeping cards for players who no
    longer play would be dead weight, and a "clean slate" season should mean
    users draw a fresh collection with their reset tokens rather than keep
    holding cards tied to a season that no longer exists.

    Takes an automatic online backup of the SQLite database immediately
    before deleting anything, since this single call is the most destructive
    operation in the app and has no undo path otherwise. Aborts with a 500
    (no deletes performed) if the backup cannot be taken, rather than
    proceeding uninsured.
    """
    locked_weeks = db.query(Week).filter(Week.is_locked == True).all()  # noqa: E712
    if locked_weeks and not body.force:
        newest_lock = max(w.start_time or 0 for w in locked_weeks)
        newer_archive = (db.query(SeasonArchive)
                         .filter(SeasonArchive.archived_at >= newest_lock).first())
        if not newer_archive:
            raise HTTPException(
                status_code=409,
                detail="Locked weeks exist but no season archive was created "
                       "after the newest locked week. Run End Season first "
                       "or pass force=true.")

    try:
        backup_path = backup_sqlite_db()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Season reset aborted — pre-reset backup failed: {e}")

    counts = {
        "player_match_stats":    db.query(PlayerMatchStats).delete(synchronize_session=False),
        "match_bans":            db.query(MatchBan).delete(synchronize_session=False),
        "matches":               db.query(Match).delete(synchronize_session=False),
        "weekly_roster_entries": db.query(WeeklyRosterEntry).delete(synchronize_session=False),
        "weeks":                 db.query(Week).delete(synchronize_session=False),
        "twitch_mvp":            db.query(TwitchMVP).delete(synchronize_session=False),
        "twitch_token_drops":    db.query(TwitchTokenDrop).delete(synchronize_session=False),
        "players":               db.query(Player).delete(synchronize_session=False),
        "teams":                 db.query(Team).delete(synchronize_session=False),
        "card_modifiers":        db.query(CardModifier).delete(synchronize_session=False),
        "cards":                 db.query(Card).delete(synchronize_session=False),
    }
    initial_tokens = int(os.getenv("INITIAL_TOKENS", "5"))
    counts["users_tokens_reset"] = (
        db.query(User).update({User.tokens: initial_tokens},
                              synchronize_session=False)
    )
    counts["leagues_unmonitored"] = (
        db.query(League).filter(League.is_monitored == True)  # noqa: E712
        .update({League.is_monitored: False}, synchronize_session=False)
    )
    detail = f"backup={backup_path} " + " ".join(f"{k}={v}" for k, v in counts.items())
    _audit(db, "admin_season_reset", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=detail)
    db.commit()
    return {"status": "ok", "initial_tokens": initial_tokens, "counts": counts,
            "backup_path": backup_path}


@router.get("/audit-logs")
def get_audit_logs(db=Depends(get_db), limit: int = 200, _: dict = Depends(require_admin)):
    rows = db.execute(text("""
        SELECT id, timestamp, actor_username, action, detail
        FROM audit_logs
        ORDER BY id DESC
        LIMIT :limit
    """), {"limit": limit}).fetchall()
    return [dict(r._mapping) for r in rows]


# ---------------------------------------------------------------------------
# Match table + Admin MVP selection
# ---------------------------------------------------------------------------

class AdminMVPRequest(BaseModel):
    player_id: int


@router.get("/admin/matches")
def list_matches(db=Depends(get_db), _: dict = Depends(require_admin)):
    matches = db.query(Match).order_by(Match.start_time.desc()).all()
    match_ids = [m.match_id for m in matches]

    mvps_by_match = {
        mv.match_id: mv
        for mv in db.query(TwitchMVP).filter(TwitchMVP.match_id.in_(match_ids)).all()
    } if match_ids else {}

    mvp_player_ids = {mv.player_id for mv in mvps_by_match.values()}
    players_by_id = {
        p.id: p for p in db.query(Player).filter(Player.id.in_(mvp_player_ids)).all()
    } if mvp_player_ids else {}

    team_ids = {tid for m in matches for tid in (m.radiant_team_id, m.dire_team_id) if tid}
    teams_by_id = {
        t.id: t for t in db.query(Team).filter(Team.id.in_(team_ids)).all()
    } if team_ids else {}

    result = []
    for m in matches:
        mvp = mvps_by_match.get(m.match_id)
        mvp_player = players_by_id.get(mvp.player_id) if mvp else None
        radiant = teams_by_id.get(m.radiant_team_id) if m.radiant_team_id else None
        dire = teams_by_id.get(m.dire_team_id) if m.dire_team_id else None
        result.append({
            "match_id": m.match_id,
            "league_id": m.league_id,
            "radiant_team_id": m.radiant_team_id,
            "dire_team_id": m.dire_team_id,
            "team1": radiant.name if radiant else None,
            "team2": dire.name if dire else None,
            "start_time": m.start_time,
            "mvp_player_name": mvp_player.name if mvp_player else None,
            "mvp_player_id": mvp.player_id if mvp else None,
        })
    return result


@router.get("/admin/matches/{match_id}/players")
def match_players(match_id: int, db=Depends(get_db), _: dict = Depends(require_admin)):
    rows = (
        db.query(Player)
        .join(PlayerMatchStats, PlayerMatchStats.player_id == Player.id)
        .filter(PlayerMatchStats.match_id == match_id)
        .all()
    )
    return [{"id": p.id, "name": p.name} for p in rows]


@router.post("/admin/matches/{match_id}/mvp")
def admin_set_mvp(
    match_id: int,
    body: AdminMVPRequest,
    db=Depends(get_db),
    admin: dict = Depends(require_admin),
):
    match = db.query(Match).filter(Match.match_id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    player = db.query(Player).filter(Player.id == body.player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    existing = db.query(TwitchMVP).filter(TwitchMVP.match_id == match_id).first()
    if existing:
        existing.player_id = body.player_id
        existing.channel_id = "admin"
        existing.selected_at = int(time.time())
    else:
        db.add(TwitchMVP(
            match_id=match_id,
            player_id=body.player_id,
            channel_id="admin",
            selected_at=int(time.time()),
        ))

    _audit(db, "admin_set_mvp", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"match {match_id} → player {body.player_id} ({player.name})")
    db.commit()
    return {"match_id": match_id, "player_id": body.player_id, "player_name": player.name}


# ---------------------------------------------------------------------------
# Demo Mode — env-gated. Structurally invisible (404, not 403) whenever
# DEMO_MODE is not explicitly "true", regardless of caller identity, so its
# existence is never revealed in a production deployment.
# ---------------------------------------------------------------------------

class DemoClockBody(BaseModel):
    timestamp: int


class SeedDemoAccountsBody(BaseModel):
    count:             int | None = Field(None, ge=1, le=100)
    cards_per_account: int | None = Field(None, ge=0, le=50)


def _require_demo_mode():
    if os.getenv("DEMO_MODE", "").lower() != "true":
        raise HTTPException(status_code=404)


@router.get("/admin/demo/clock")
def get_demo_clock(db=Depends(get_db), _demo: None = Depends(_require_demo_mode),
                   _: dict = Depends(require_admin)):
    # Also called imperatively (not just via Depends) because this codebase's
    # test suite invokes endpoint functions directly, bypassing FastAPI's
    # dependency resolution — a bare Depends() default never fires there.
    _require_demo_mode()
    override = clock.get_override(db)
    return {"override_timestamp": override, "effective_now": clock.now(db)}


@router.post("/admin/demo/clock")
def set_demo_clock(body: DemoClockBody, db=Depends(get_db),
                   _demo: None = Depends(_require_demo_mode),
                   admin: dict = Depends(require_admin)):
    _require_demo_mode()
    clock.set_override(db, body.timestamp)
    auto_lock_weeks(db)  # synchronous — make the lock transition observable immediately
    _audit(db, "admin_demo_clock_set", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"timestamp={body.timestamp}")
    db.commit()
    return {"override_timestamp": body.timestamp, "effective_now": clock.now(db)}


@router.delete("/admin/demo/clock")
def clear_demo_clock(db=Depends(get_db), _demo: None = Depends(_require_demo_mode),
                     admin: dict = Depends(require_admin)):
    _require_demo_mode()
    clock.clear_override(db)
    _audit(db, "admin_demo_clock_cleared", actor_id=admin["user_id"],
           actor_username=admin["username"], detail="")
    db.commit()
    return {"override_timestamp": None}


@router.post("/admin/demo/seed-accounts")
def seed_demo_accounts(body: SeedDemoAccountsBody, db=Depends(get_db),
                       _demo: None = Depends(_require_demo_mode),
                       admin: dict = Depends(require_admin)):
    """Create disposable demo1, demo2, ... accounts pre-loaded with random cards.

    Reuses draw_card from routers/cards.py directly (a plain Python function
    call, not an HTTP round-trip) — it already handles rarity rolls, player
    selection, modifier assignment, and roster auto-activation up to
    ROSTER_LIMIT. Granting cards_per_account tokens up front lets the loop
    call the real draw path unmodified.

    _require_demo_mode is declared as a dependency ahead of require_admin so a
    real HTTP request resolves it first: a non-admin caller gets 404 (mode
    disabled), not 403, when DEMO_MODE is off — the endpoint's existence stays
    hidden. It is also called imperatively below because this codebase's test
    suite invokes endpoint functions directly, bypassing FastAPI's dependency
    resolution entirely; a bare Depends() default would never fire there.
    """
    _require_demo_mode()
    count = body.count or 5
    cards_per_account = body.cards_per_account if body.cards_per_account is not None else 3
    existing = {u.username for u in db.query(User).filter(User.username.like("demo%")).all()}
    created = []
    n = 1
    while len(created) < count:
        username = f"demo{n}"
        n += 1
        if username in existing:
            continue
        password = secrets.token_urlsafe(9)
        user = User(username=username, email=f"{username}@demo.local",
                    password_hash=hash_password(password),
                    tokens=cards_per_account)
        db.add(user)
        db.flush()
        fake_current_user = {"user_id": user.id, "username": username, "is_admin": False}
        for _ in range(cards_per_account):
            try:
                draw_card(db=db, current_user=fake_current_user)
            except HTTPException:
                # No players available to draw (empty pool) or out of tokens —
                # the account is still created; it just ends up with fewer cards.
                break
        created.append({"username": username, "password": password})
    _audit(db, "admin_demo_accounts_seeded", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"created={len(created)}")
    db.commit()
    return {"accounts": created}
