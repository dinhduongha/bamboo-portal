from typing import Annotated

import odoo
from fastapi import APIRouter, Depends

from odoo.addons.fastapi.dependencies import odoo_env
from odoo.api import Environment

from ..schemas.envelope import ResponseEnvelope
from ..schemas.public import HealthOut

health_router = APIRouter(tags=["Meta"])


@health_router.get("/health", response_model=ResponseEnvelope[HealthOut])
async def health(env: Annotated[Environment, Depends(odoo_env)]):
    return ResponseEnvelope(
        data=HealthOut(
            status="ok",
            service="bamboo_public_api",
            odoo_version=odoo.release.version,
            db=env.cr.dbname,
        )
    )
