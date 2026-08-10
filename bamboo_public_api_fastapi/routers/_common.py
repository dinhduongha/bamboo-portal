"""Shared router plumbing — the FastAPI counterparts of the controller decorators.

`bamboo_public_api`'s controllers guard themselves with `@requires_app('shop')` and
an `if not _user(): 401`. Those are `odoo.http`-shaped; here the same two guards are
FastAPI dependencies so they show up in the OpenAPI schema and run before the body.
"""

from typing import Annotated, Any, Dict, Optional

from fastapi import Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse

from odoo.api import Environment

from odoo.addons.bamboo_public_api.controllers.common import (
    APP_MODULES,
    module_installed,
)

from ..dependencies import authenticated_odoo_env


def envelope_error(message: str, status_code: int, headers=None) -> JSONResponse:
    """The controllers' `err()` as a FastAPI response.

    Returned, not raised, on the paths a client hits routinely (an anonymous
    "am I logged in?"): OCA's dispatcher re-raises HTTPException so `odoo.http` can
    log it, which writes an ERROR and a full traceback every time.
    """
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "data": None, "error": message, "meta": {}},
        headers=headers,
    )


def require_app(app: str):
    """Dependency: 404 the route when the app's Odoo module is not installed.

    Mirrors `bamboo_public_api.controllers.common.requires_app`, so the addon stays
    installable on any Odoo and a missing app degrades cleanly instead of 500-ing.
    """

    def _guard(env: Annotated[Environment, Depends(authenticated_odoo_env)]) -> None:
        if not module_installed(APP_MODULES[app]):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="App '%s' is not available on this server" % app,
            )

    return _guard


def require_module(name: str, label: str):
    """Same, for a plain module name that is not in `APP_MODULES` (sale, account…).

    `label` is what the caller sees ("Orders", "Invoices") — worded exactly as the
    controller words it, so the two modes return the same message.
    """

    def _guard(env: Annotated[Environment, Depends(authenticated_odoo_env)]) -> None:
        if not module_installed(name):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="%s are not available on this server" % label,
            )

    return _guard


def current_user(env: Environment):
    """The signed-in user, or None when the caller is the public/anonymous user."""
    user = env.user
    if not user or user._is_public():
        return None
    return user


def authenticated_env(
    env: Annotated[Environment, Depends(authenticated_odoo_env)],
) -> Environment:
    """`authenticated_odoo_env` + the controllers' `auth='user'` check.

    Raising (rather than returning `envelope_error`) is right here: these are
    actions, not polls, so an anonymous hit is an anomaly worth a log line. The
    dispatcher's error handler renders it in the envelope shape.
    """
    if current_user(env) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return env


AuthEnv = Annotated[Environment, Depends(authenticated_env)]
PublicEnv = Annotated[Environment, Depends(authenticated_odoo_env)]


class Page:
    """`page`/`limit` query params — the FastAPI form of `common.page_params()`
    (which cannot be reused: it reads `request.params`, which the FastAPI
    dispatcher does not populate)."""

    def __init__(
        self,
        page: int = Query(default=1, ge=1),
        limit: int = Query(default=20, ge=1, le=100),
    ):
        self.page = page
        self.limit = limit
        self.offset = (page - 1) * limit


Paging = Annotated[Page, Depends(Page)]


def meta_page(total: int, paging: Page) -> Dict[str, Any]:
    """`common.page_meta` with the arguments a `Page` carries."""
    from odoo.addons.bamboo_public_api.controllers.common import page_meta

    return page_meta(total, paging.limit, paging.page)


def country_id(env: Environment, code: Optional[str]) -> Optional[int]:
    """Resolve an ISO country code to an id, or None (mirrors `_set_country`)."""
    if not code:
        return None
    country = env["res.country"].sudo().search([("code", "=", code.upper())], limit=1)
    return country.id or None
