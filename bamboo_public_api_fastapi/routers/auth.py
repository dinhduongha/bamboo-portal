"""Public-site authentication: who am I, login, signup, logout.

Classic email+password for the public/portal site, separate from the internal
Bamboo client's per-account auth.

One deliberate divergence from the controller: **no session cookie**. The
controller logs the browser in through `request.session.authenticate`; here the
credentials are verified against `res.users.authenticate` and the caller gets the
JWT only. A FastAPI route writing to the Odoo session would be reaching around the
app it is mounted in, and the public client already sends `Authorization: Bearer`
on every request. `/me` still honours a session cookie if one exists — that is the
dispatcher's doing, not this router's.
"""

import time
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException

from odoo import release
from odoo.api import Environment
from odoo.exceptions import AccessDenied

from ..dependencies import authenticated_odoo_env
from ..schemas.envelope import ResponseEnvelope
from ..schemas.public import LoginIn, LoginOut, LogoutOut, MeOut, SignupIn
from ._common import current_user, envelope_error

auth_router = APIRouter(tags=["Auth"])


def _issue_token(env: Environment, uid: int) -> str:
    """A JWT `bamboo_token_auth` will accept (HS256 over `database.secret`).

    Empty when that module is not installed — the caller then has nothing but the
    session, which is exactly the controller's behaviour.
    """
    try:
        from odoo.addons.bamboo_token_auth import jwt_min as jwt
    except ImportError:
        return ""
    secret = env["ir.config_parameter"].sudo().get_param("database.secret")
    now = int(time.time())
    return jwt.encode(
        {"uid": uid, "iat": now, "exp": now + 90 * 24 * 3600},
        secret,
        algorithm="HS256",
    )


def _verify_credentials(env: Environment, login: str, password: str) -> Optional[int]:
    """The uid behind login/password, or None. Creates no session.

    `res.users.authenticate` changed shape in 19 (an env-bound method taking the
    credential, versus an 18 classmethod taking the database name), and this file
    is shared by both branches.
    """
    credential = {"login": login, "password": password, "type": "password"}
    Users = env["res.users"].sudo()
    try:
        if release.version_info[0] >= 19:
            auth_info = Users.authenticate(credential, {"interactive": False})
        else:
            auth_info = Users.authenticate(env.cr.dbname, credential, None)
    except AccessDenied:
        return None
    if isinstance(auth_info, dict):
        return auth_info.get("uid")
    return auth_info or None


def _user_payload(user, token: Optional[str] = None) -> dict:
    """`portal_auth._user_dict` — kept identical so the two modes are swappable."""
    data = {
        "uid": user.id,
        "name": user.name,
        "login": user.login,
        "email": user.email or "",
        "partner_id": user.partner_id.id,
        "share": user.share,
    }
    if token is not None:
        data["access_token"] = token
    return data


PublicEnv = Annotated[Environment, Depends(authenticated_odoo_env)]


@auth_router.get(
    "/me",
    response_model=ResponseEnvelope[Optional[MeOut]],
    responses={401: {"description": "No valid Bearer token or session"}},
)
async def me(env: PublicEnv):
    """The signed-in user, or `data: null` when nobody is.

    Not a 401: "am I logged in?" is a question, and the answer "nobody" is a
    successful answer — the public site renders fine either way. This matches the
    controller exactly, so the two modes stay swappable.

    This is also the canary for `../dependencies.py`: it is the only public route
    whose answer differs per caller, so it fails first if the `odoo_env` override
    stops reaching the dispatcher.
    """
    user = current_user(env)
    if user is None:
        return ResponseEnvelope(data=None)
    return ResponseEnvelope(data=_user_payload(user))


@auth_router.post("/auth/login", response_model=ResponseEnvelope[LoginOut])
async def login(body: LoginIn, env: PublicEnv):
    login_name = (body.login or body.email or "").strip()
    password = body.password or ""
    if not login_name or not password:
        raise HTTPException(status_code=422, detail="Login and password are required")
    uid = _verify_credentials(env, login_name, password)
    if not uid:
        return envelope_error("Invalid credentials", 401)
    user = env["res.users"].sudo().browse(uid)
    return ResponseEnvelope(data=_user_payload(user, _issue_token(env, uid)))


@auth_router.post(
    "/auth/signup", response_model=ResponseEnvelope[LoginOut], status_code=201
)
async def signup(body: SignupIn, env: PublicEnv):
    name = (body.name or "").strip()
    email = (body.email or "").strip()
    password = body.password or ""
    if not name or not email or not password:
        raise HTTPException(
            status_code=422, detail="Name, email and password are required"
        )

    Users = env["res.users"].sudo()
    if Users.search_count([("login", "=", email)]):
        raise HTTPException(
            status_code=409, detail="An account with this email already exists"
        )

    portal_group = env.ref("base.group_portal")
    # Odoo 19 renamed res.users.groups_id → group_ids.
    group_field = "group_ids" if "group_ids" in Users._fields else "groups_id"
    try:
        user = Users.create(
            {
                "name": name,
                "login": email,
                "email": email,
                "password": password,
                group_field: [(6, 0, [portal_group.id])],
            }
        )
    except Exception as exc:  # noqa: BLE001 — validation errors belong to the caller
        raise HTTPException(
            status_code=400, detail="Could not create account: %s" % exc
        ) from exc
    return ResponseEnvelope(data=_user_payload(user, _issue_token(env, user.id)))


@auth_router.post("/auth/logout", response_model=ResponseEnvelope[LogoutOut])
async def logout(env: PublicEnv):
    """Drop the session cookie if the caller has one.

    A JWT cannot be revoked here — it is stateless and self-expiring — so a
    token-only client logs out by discarding it. Reported as done either way, like
    the controller.
    """
    try:
        from odoo.http import request as odoo_request

        odoo_request.session.logout(keep_db=True)
    except Exception:  # noqa: BLE001 — no session to drop is a successful logout
        pass
    return ResponseEnvelope(data=LogoutOut(logged_out=True))
