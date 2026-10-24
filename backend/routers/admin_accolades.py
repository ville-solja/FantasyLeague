"""Admin management of season champions and accolades (issues #50, #105).

PUT /admin/season-champions replaces one season and division's champions; the
/admin/season-accolades routes list, add, correct and remove single rows. Every write
needs admin rights plus a recent re-auth and writes an audit entry.
"""
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

import accolades
from database import get_db
from deps import require_admin, require_recent_reauth, _audit
from models import SeasonAccolade, User

router = APIRouter()

AccountId = Annotated[int, Field(ge=1, le=2**63 - 1)]
RowId = Annotated[int, Path(ge=1, le=2**63 - 1)]
Label = Annotated[str, Field(min_length=1, max_length=100)]
Name = Annotated[str, Field(max_length=100)]

# Most rows one save may carry: a champion team with stand-ins, or a season's played list.
MAX_CHAMPIONS = 50
MAX_ROWS = 500


def _strip(v):
    return v.strip() if isinstance(v, str) else v


# ---------------------------------------------------------------------------
# PUT /admin/season-champions
# ---------------------------------------------------------------------------

class ChampionPlayer(BaseModel):
    account_id: AccountId
    name: Name

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Every player needs a name")
        return v


class ChampionSetBody(BaseModel):
    season_label: Label
    division: Literal["div1", "div2"]
    team_name: Name = ""
    players: list[ChampionPlayer] = Field(..., max_length=MAX_CHAMPIONS)

    @field_validator("season_label", "team_name")
    @classmethod
    def _trim(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _check(self):
        if not self.season_label:
            raise ValueError("Season label cannot be empty")
        ids = [p.account_id for p in self.players]
        if len(ids) != len(set(ids)):
            raise ValueError("Each OpenDota id can appear only once")
        if self.players and not self.team_name:
            raise ValueError("Team name cannot be empty")
        return self


@router.put("/admin/season-champions", dependencies=[Depends(require_recent_reauth)])
def set_season_champions(body: ChampionSetBody, db=Depends(get_db),
                         admin: dict = Depends(require_admin)):
    """Make this season and division's champions exactly the list given, in one
    transaction. An empty list removes the division's champions. Holo eligibility
    follows the record; cards already drawn as Holo stay Holo."""
    players = [p.model_dump() for p in body.players]
    added, removed = accolades.set_champions(db, body.season_label, body.division,
                                             body.team_name, players, admin["user_id"])
    _audit(db, "admin_champions_set", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"season_label={body.season_label} division={body.division} "
                  f"team={body.team_name} players={len(players)} added={added} removed={removed}")
    db.commit()
    return {"season_label": body.season_label, "division": body.division,
            "team_name": body.team_name, "players": len(players),
            "added": added, "removed": removed}


# ---------------------------------------------------------------------------
# /admin/season-accolades
# ---------------------------------------------------------------------------

class AccoladeIn(BaseModel):
    season_label: Label
    kind: Literal["champion", "most_points", "best_average", "best_match", "fantasy_winner", "played"]
    division: Literal["div1", "div2"] | None = None
    team_name: Name | None = None
    player_account_id: AccountId | None = None
    player_name: Name | None = None
    user_id: AccountId | None = None
    username: Name | None = None
    value: float | None = Field(None, ge=-1e9, le=1e9)
    match_id: AccountId | None = None

    @field_validator("season_label", "team_name", "player_name", "username")
    @classmethod
    def _trim(cls, v):
        return _strip(v)

    @model_validator(mode="after")
    def _check(self):
        if not self.season_label:
            raise ValueError("Season label cannot be empty")
        if self.kind == "champion":
            if self.division is None:
                raise ValueError("A champion needs a division (div1 or div2)")
            if not self.team_name:
                raise ValueError("A champion needs a team name")
        elif self.division is not None:
            raise ValueError("Only a champion has a division")
        if self.kind == "fantasy_winner":
            if self.user_id is None and not self.username:
                raise ValueError("A fantasy winner needs a user")
            if self.player_account_id is not None:
                raise ValueError("A fantasy winner is a user, not a player")
        else:
            if self.player_account_id is None:
                raise ValueError("This accolade needs a player (OpenDota id)")
            if self.user_id is not None or self.username:
                raise ValueError("Only a fantasy winner names a user")
        return self


def _resolve(db, a: AccoladeIn, admin_id: int, now: int) -> dict:
    row = a.model_dump()
    if a.kind == "fantasy_winner":
        user = db.get(User, a.user_id) if a.user_id is not None else (
            db.query(User).filter(func.lower(User.username) == a.username.lower()).first())
        if user is None:
            raise HTTPException(status_code=422, detail="User not found")
        # Rankings leave out testers and Twitch viewer soft accounts; so does this.
        if user.account_type != "full" or user.is_tester:
            raise HTTPException(status_code=422,
                                detail="A fantasy winner must be a website account that is not a tester")
        row["user_id"], row["username"] = user.id, user.display_name
    else:
        name = a.player_name or accolades.known_name(db, a.player_account_id)
        if not name:
            raise HTTPException(status_code=422,
                                detail=f"Name needed for OpenDota id {a.player_account_id}")
        row["player_name"] = name
    if a.kind != "champion":
        row["team_name"] = None
    if a.kind != "best_match":
        row["match_id"] = None
    row.update(source=accolades.SOURCE_ADMIN, created_at=now, created_by=admin_id)
    return row


@router.post("/admin/season-accolades", dependencies=[Depends(require_recent_reauth)])
def add_season_accolades(body: AccoladeIn | list[AccoladeIn], db=Depends(get_db),
                         admin: dict = Depends(require_admin)):
    """Add one accolade (409 when it already exists) or a list, such as a season's
    played rows (rows that already exist are skipped and counted)."""
    single = not isinstance(body, list)
    items = [body] if single else body
    if not items:
        raise HTTPException(status_code=422, detail="Nothing to add")
    if len(items) > MAX_ROWS:
        raise HTTPException(status_code=422, detail=f"At most {MAX_ROWS} rows at once")
    now = int(time.time())
    rows = [_resolve(db, a, admin["user_id"], now) for a in items]
    if single:
        row = SeasonAccolade(**rows[0])
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="That accolade already exists")
        added, skipped, result = 1, 0, accolades.row_dict(row)
    else:
        added = accolades.insert_ignore(db, rows)
        skipped = len(rows) - added
        result = None
    seasons = sorted({r["season_label"] for r in rows})
    kinds = sorted({r["kind"] for r in rows})
    _audit(db, "admin_accolade_added", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"season_label={','.join(seasons)} kind={','.join(kinds)} "
                  f"added={added} skipped={skipped}")
    db.commit()
    if single:
        return result
    return {"added": added, "skipped": skipped}


@router.get("/admin/season-accolades")
def list_season_accolades(season: str | None = Query(None, max_length=100),
                          kind: str | None = Query(None, max_length=32),
                          db=Depends(get_db), _: dict = Depends(require_admin)):
    """Every accolade row, newest season first, optionally for one season and kind."""
    q = db.query(SeasonAccolade)
    if season:
        q = q.filter(SeasonAccolade.season_label == season.strip())
    if kind:
        q = q.filter(SeasonAccolade.kind == kind.strip())
    rows = q.all()
    order = {k["key"]: i for i, k in enumerate(accolades.ACCOLADE_KINDS)}
    rows.sort(key=lambda r: (-accolades.season_sort_key(r.season_label)[0],
                             r.season_label,
                             order.get(r.division if r.kind == "champion" else r.kind, 99),
                             str(r.player_name or r.username or "").lower()))
    return [accolades.row_dict(r) for r in rows]


class AccoladePatch(BaseModel):
    value: float | None = Field(None, ge=-1e9, le=1e9)
    player_name: Name | None = None
    team_name: Name | None = None
    username: Name | None = None


def _get_row(db, row_id: int) -> SeasonAccolade:
    row = db.get(SeasonAccolade, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Accolade not found")
    return row


@router.patch("/admin/season-accolades/{row_id}", dependencies=[Depends(require_recent_reauth)])
def update_season_accolade(row_id: RowId, body: AccoladePatch, db=Depends(get_db),
                           admin: dict = Depends(require_admin)):
    """Correct an accolade's value, player name, team name or username."""
    row = _get_row(db, row_id)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Nothing to change")
    for field in ("player_name", "team_name", "username"):
        if field in changes:
            v = (changes[field] or "").strip()
            if not v:
                raise HTTPException(status_code=422, detail=f"{field} cannot be empty")
            changes[field] = v
    for field, v in changes.items():
        setattr(row, field, v)
    _audit(db, "admin_accolade_updated", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"id={row.id} season_label={row.season_label} kind={row.kind} "
                  f"fields={','.join(sorted(changes))}")
    db.commit()
    return accolades.row_dict(row)


@router.delete("/admin/season-accolades/{row_id}", dependencies=[Depends(require_recent_reauth)])
def delete_season_accolade(row_id: RowId, db=Depends(get_db),
                           admin: dict = Depends(require_admin)):
    """Remove one accolade. A season_winner tag already granted stays."""
    row = _get_row(db, row_id)
    detail = (f"id={row.id} season_label={row.season_label} kind={row.kind} "
              f"player={row.player_account_id or ''} user={row.username or ''}")
    db.delete(row)
    _audit(db, "admin_accolade_removed", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=detail)
    db.commit()
    return {"status": "ok", "id": row_id}
