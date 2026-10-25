from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import User
from ..schemas import Login, user_out
from ..security import authenticate, current_user, issue_token

router = APIRouter(tags=["auth"])


@router.post("/auth/login")
def login(body: Login, s: Session = Depends(get_session)) -> dict:
    user = authenticate(s, body.username, body.password)
    return {"token": issue_token(user), "user": user_out(user)}


@router.get("/auth/me")
def me(user: User = Depends(current_user)) -> dict:
    return user_out(user)


@router.get("/auth/demo")
def demo_accounts() -> dict:
    """Public demo deployments show their demo accounts on the login page (DEMO_MODE=true only)."""
    if os.environ.get("DEMO_MODE", "").lower() != "true":
        return {"enabled": False}
    return {"enabled": True, "accounts": ["lead.demo", "engineer.demo"], "password": os.environ.get("DEMO_PASSWORD", "")}


@router.get("/users")
def users(_: User = Depends(current_user), s: Session = Depends(get_session)) -> list[dict]:
    return [user_out(u) for u in s.scalars(select(User).where(User.active.is_(True)).order_by(User.name))]
