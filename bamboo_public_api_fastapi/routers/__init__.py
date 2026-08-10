"""Router assembly.

Two families live in this app and they are shaped differently on the wire:

* the **public site API** under `/public` — every response is the
  `{success, data, error, meta}` envelope, so a client can swap between here and
  the `/bamboo/public/v1` controllers by changing one base URL;
* the **generic ORM RPC** at the app root — `dataset/call_kw` speaks JSON-RPC and
  `json2` returns the raw value, because those mirror Odoo's own routes.

The `/public` prefix is applied once here rather than repeated in every route
path, so `routers/shop.py` reads exactly like `controllers/shop.py`.
"""

from fastapi import APIRouter

from .auth import auth_router
from .blog import blog_router
from .cart import cart_router
from .checkout import checkout_router
from .contact import contact_router
from .courses import courses_router
from .event import event_router
from .forum import forum_router
from .health import health_router
from .job import job_router
from .meta import meta_router
from .payment import payment_router
from .portal import portal_router
from .rpc import rpc_routers
from .shop import shop_router

PUBLIC_PREFIX = "/public"

_PUBLIC_ROUTERS = (
    meta_router,
    health_router,
    auth_router,
    shop_router,
    cart_router,
    checkout_router,
    contact_router,
    courses_router,
    blog_router,
    event_router,
    forum_router,
    job_router,
    payment_router,
    portal_router,
)


def _public_router() -> APIRouter:
    router = APIRouter(prefix=PUBLIC_PREFIX)
    for child in _PUBLIC_ROUTERS:
        router.include_router(child)
    return router


def bamboo_routers():
    """Every router the `bamboo_public` app serves, public API first."""
    return [_public_router()] + rpc_routers()
