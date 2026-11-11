"""Admin › Settings › Season › Team signup (issue #220): open and close the signup
period, list and remove listings, export them and clear a period. Thin wrappers; the
logic is in team_signup.py."""
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

import team_signup
from database import get_db
from deps import _audit, require_admin, require_recent_reauth

router = APIRouter()

Id = Annotated[int, Field(ge=1, le=2**63 - 1)]


class PeriodBody(BaseModel):
    label: str = Field(..., min_length=1, max_length=team_signup.LABEL_MAX)
    closes_at: Annotated[int, Field(ge=1, le=2**53)] | None = None


class ClearBody(BaseModel):
    period_id: Id


def _log(db, admin: dict, action: str, detail: str) -> None:
    _audit(db, action, actor_id=admin["user_id"], actor_username=admin["username"], detail=detail)


@router.get("/admin/team-signup")
def get_admin_team_signup(db=Depends(get_db), _: dict = Depends(require_admin)):
    return team_signup.admin_view(db)


@router.post("/admin/team-signup/period")
def open_period(body: PeriodBody, db=Depends(get_db), admin: dict = Depends(require_admin)):
    p = team_signup.start_period(db, body.label, body.closes_at, admin["user_id"])
    _log(db, admin, "admin_team_signup_opened", f"period={p.label} closes_at={p.closes_at}")
    db.commit()
    return team_signup.admin_view(db)


@router.post("/admin/team-signup/period/close")
def close_period(db=Depends(get_db), admin: dict = Depends(require_admin)):
    p = team_signup.close_period(db)
    _log(db, admin, "admin_team_signup_closed", f"period={p.label}")
    db.commit()
    return team_signup.admin_view(db)


@router.get("/admin/team-signup/export.csv")
def export_csv(period_id: Annotated[int | None, Query(ge=1, le=2**63 - 1)] = None,
               db=Depends(get_db), _: dict = Depends(require_admin)):
    """One row per listed player; formula-like cells are prefixed with an apostrophe."""
    p = team_signup.export_period(db, period_id)
    return Response(team_signup.csv_text(db, p), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="team-signups-{p.id}.csv"',
                             "Cache-Control": "no-store"})


@router.get("/admin/team-signup/export.json")
def export_json(period_id: Annotated[int | None, Query(ge=1, le=2**63 - 1)] = None,
                db=Depends(get_db), _: dict = Depends(require_admin)):
    return team_signup.export_json(db, team_signup.export_period(db, period_id))


@router.post("/admin/team-signup/clear", dependencies=[Depends(require_recent_reauth)])
def clear_signups(body: ClearBody, db=Depends(get_db), admin: dict = Depends(require_admin)):
    p, n = team_signup.clear_period(db, body.period_id)
    _log(db, admin, "admin_team_signup_cleared", f"period={p.label} listings={n}")
    db.commit()
    return {"deleted": n}


@router.delete("/admin/team-signup/{signup_id}")
def remove_listing(signup_id: Annotated[int, Path(ge=1, le=2**63 - 1)], db=Depends(get_db),
                   admin: dict = Depends(require_admin)):
    name, p = team_signup.remove_listing(db, signup_id)
    _log(db, admin, "admin_team_signup_removed", f"period={p.label if p else ''} team={name}")
    db.commit()
    return {"ok": True}
