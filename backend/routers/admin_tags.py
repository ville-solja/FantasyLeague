import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import get_db
from deps import require_admin, _audit
from models import TagDefinition, User, UserTag

router = APIRouter()


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
