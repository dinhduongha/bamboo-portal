# -*- coding: utf-8 -*-
"""Make the FastAPI app answer as whoever the Bearer token identified.

OCA's `fastapi.endpoint` runs its app as one fixed user (`endpoint.user_id`):
`FastApiDispatcher.dispatch` calls `get_uid(path)` and hands that uid to
`_manage_odoo_env`, which replaces the environment. That happens *after*
`ir.http._authenticate` has already resolved the request's real user, so a valid
token is accepted and then discarded — every FastAPI call runs as the public
user, whatever it carried.

Both token flavours land in `request.env` before the dispatcher runs, so neither
is special-cased here:

* `bamboo_token_auth` decodes its HS256 JWT in `_auth_method_public` and calls
  `request.update_env(user=uid)`.
* `bamboo_abp_auth` validates ABP's RS256 JWT in `_authenticate` and does the
  same.

So "who is calling" is simply `request.env.uid`, and this module only has to stop
OCA from throwing it away. Nothing here re-implements authentication.
"""

from typing import Annotated, Optional

from fastapi import Depends, HTTPException, status

from odoo.addons.fastapi.context import odoo_env_ctx
from odoo.addons.fastapi.dependencies import company_id
from odoo.api import Environment
from odoo.http import request


def _request_uid():
    """The uid `ir.http` authenticated for this request, or None.

    `_manage_odoo_env` never reassigns `request.env` — it only builds a separate
    environment for the contextvar — so the authenticated uid is still here.
    """
    try:
        return request.env.uid
    except Exception:
        # No HTTP request (a test calling the app directly), or no env yet.
        return None


def authenticated_odoo_env(
    company_id: Annotated[Optional[int], Depends(company_id)],
) -> Environment:
    """Drop-in replacement for OCA's `odoo_env`, honouring the request's user.

    Same contract as the original (a generator dependency yielding an
    Environment), with one difference: when the caller authenticated as somebody
    other than the endpoint's own user, the environment is switched to them.

    The endpoint's company is deliberately NOT forced in that case. It is derived
    from `endpoint.user_id.company_id`, and pinning `allowed_company_ids` to a
    company the authenticated user has no access to raises "Access to
    unauthorized or invalid companies" on the first read. Their own companies are
    the only correct answer once the identity changed.
    """
    env = odoo_env_ctx.get()
    uid = _request_uid()
    if uid and uid != env.uid:
        env = env(user=uid)
        # Their own company first: `env.company` is the first allowed id, and
        # res.company orders by name — left alone, a multi-company user gets
        # whichever company sorts first alphabetically, which then picks the
        # pricelist, the taxes and the currency.
        default = env.user.company_id
        allowed = default.ids + (env.user.company_ids - default).ids
        if allowed:
            env = env(context=dict(env.context, allowed_company_ids=allowed))
    elif company_id is not None:
        env = env(context=dict(env.context, allowed_company_ids=[company_id]))
    yield env


def authenticated_partner_impl(
    env: Annotated[Environment, Depends(authenticated_odoo_env)],
):
    """OCA's hook for `Depends(authenticated_partner)`.

    401 rather than 403: the caller is not forbidden from the resource, they have
    not said who they are — and the client's next move (get a token, retry) only
    follows from that distinction.
    """
    user = env.user
    if not user or user._is_public():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user.partner_id


def optionally_authenticated_partner_impl(
    env: Annotated[Environment, Depends(authenticated_odoo_env)],
):
    """Same, for routes that render differently when signed in but never 401."""
    user = env.user
    if not user or user._is_public():
        return None
    return user.partner_id
