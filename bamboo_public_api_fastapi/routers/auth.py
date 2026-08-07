"""Who am I — the FastAPI counterpart of the controllers' `/portal/profile` GET.

Also the proof that the token survives the dispatcher: this is the only route in
the app whose answer differs per caller, so it is what fails first if the
`odoo_env` override in ../dependencies.py stops being applied.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from odoo.api import Environment

from ..dependencies import authenticated_odoo_env
from ..schemas.envelope import ResponseEnvelope
from ..schemas.public import MeOut

auth_router = APIRouter(tags=["Auth"])


@auth_router.get(
    "/me",
    response_model=ResponseEnvelope[MeOut],
    responses={401: {"description": "No valid Bearer token or session"}},
)
async def me(env: Annotated[Environment, Depends(authenticated_odoo_env)]):
    """The signed-in user. 401 when nobody is.

    The 401 is returned, not raised. OCA's dispatcher re-raises HTTPException so
    that `odoo.http` can log it, which means `Depends(authenticated_partner)`
    writes an ERROR and a full traceback for every anonymous hit — and "am I
    logged in?" is a request a client makes constantly. `authenticated_partner`
    is still wired up (see ../dependencies.py) for routes that want it.
    """
    user = env.user
    if not user or user._is_public():
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "data": None,
                "error": "Authentication required.",
                "meta": {},
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    partner = user.partner_id
    return ResponseEnvelope(
        data=MeOut(
            uid=user.id,
            login=user.login,
            name=partner.name,
            email=partner.email or "",
            partner_id=partner.id,
            company=env.company.name,
        )
    )
