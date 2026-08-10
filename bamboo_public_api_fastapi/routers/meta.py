from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends

from odoo.addons.fastapi.dependencies import odoo_env
from odoo.api import Environment

from odoo.addons.bamboo_public_api.controllers.common import (
    APP_MODULES,
    FASTAPI_PUBLIC_ROOT,
)

from ..schemas.envelope import ResponseEnvelope

meta_router = APIRouter(tags=["Meta"])


def _module_installed(env, name):
    return bool(
        env["ir.module.module"]
        .sudo()
        .search_count([("name", "=", name), ("state", "=", "installed")])
    )


@meta_router.get("/meta", response_model=ResponseEnvelope[Dict[str, Any]])
async def meta(env: Annotated[Environment, Depends(odoo_env)]):
    company = env.company
    data = {
        "apps": {app: _module_installed(env, mod) for app, mod in APP_MODULES.items()},
        "api_mode": "fastapi",
        "api_root": FASTAPI_PUBLIC_ROOT,
        "company": {
            "name": company.name,
            "currency": company.currency_id.name,
            "country": company.country_id.code if company.country_id else None,
        },
        "languages": [
            {"code": l.code, "name": l.name}
            for l in env["res.lang"].sudo().search([("active", "=", True)])
        ],
    }
    return ResponseEnvelope(data=data)
