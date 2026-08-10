"""Cart — a draft `sale.order`, so Odoo owns price/tax/promo/stock.

Same contract as the controller: the cart is identified by its portal
`access_token`, echoed back as `cart_token` and accepted as the `X-Cart-Token`
header, a `cart_token` query param or the `bamboo_cart` cookie. `_cart_token()`
reads the header and the cookie off `odoo.http.request`, which is still the live
request inside the FastAPI app — only the query-param tier needs re-doing here,
because the dispatcher does not populate `request.params` for FastAPI routes.
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from odoo.addons.bamboo_public_api.controllers.cart import (
    _cart_dict,
    _cart_partner,
    _find_cart,
)
from odoo.http import request as odoo_request

from ..schemas.envelope import ResponseEnvelope
from ..schemas.shop import CartAddIn, CartOut, CartQtyIn
from ._common import PublicEnv, require_app

cart_router = APIRouter(tags=["Cart"], dependencies=[Depends(require_app("shop"))])

CART_COOKIE = "bamboo_cart"


def _token(cart_token: Optional[str]) -> Optional[str]:
    """Header → explicit query param → cookie, matching `cart._cart_token()`."""
    headers = odoo_request.httprequest.headers
    return (
        headers.get("X-Cart-Token")
        or cart_token
        or odoo_request.httprequest.cookies.get(CART_COOKIE)
    )


def _ensure_cart(env, token: Optional[str], create: bool = True):
    """`cart._ensure_cart()` with the token passed in rather than re-read."""
    order = _find_cart(token)
    if order:
        partner = _cart_partner()
        public = env.ref("base.public_partner")
        if order.partner_id == public and partner != public:
            order.write({"partner_id": partner.id})
        return order
    if not create:
        return order
    order = env["sale.order"].sudo().create({"partner_id": _cart_partner().id})
    order._portal_ensure_token()
    return order


def _with_cookie(response: Response, order) -> None:
    """Persist the cart across a cookie-only client (the token is also in the body).

    `samesite=None; Secure` because the React app is served from another origin.
    """
    response.set_cookie(
        CART_COOKIE, order.access_token, samesite="none", secure=True
    )


CartToken = Annotated[Optional[str], Query(alias="cart_token")]


@cart_router.post("/cart", response_model=ResponseEnvelope[CartOut], status_code=201)
async def cart_create(env: PublicEnv, response: Response, cart_token: CartToken = None):
    order = _ensure_cart(env, _token(cart_token), create=True)
    _with_cookie(response, order)
    return ResponseEnvelope(data=_cart_dict(order))


@cart_router.get("/cart", response_model=ResponseEnvelope[Optional[CartOut]])
async def cart_get(env: PublicEnv, cart_token: CartToken = None):
    order = _ensure_cart(env, _token(cart_token), create=False)
    return ResponseEnvelope(data=_cart_dict(order) if order else None)


@cart_router.post(
    "/cart/items", response_model=ResponseEnvelope[CartOut], status_code=201
)
async def cart_add(
    body: CartAddIn, env: PublicEnv, response: Response, cart_token: CartToken = None
):
    product = env["product.product"].sudo().browse(body.product_id)
    if not product.exists():
        raise HTTPException(status_code=404, detail="Product not found")

    order = _ensure_cart(env, _token(cart_token), create=True)
    line = order.order_line.filtered(lambda l: l.product_id.id == body.product_id)[:1]
    if line:
        line.product_uom_qty += body.qty
    else:
        env["sale.order.line"].sudo().create(
            {
                "order_id": order.id,
                "product_id": body.product_id,
                "product_uom_qty": body.qty,
            }
        )
    _with_cookie(response, order)
    return ResponseEnvelope(data=_cart_dict(order))


@cart_router.patch("/cart/items/{line_id}", response_model=ResponseEnvelope[CartOut])
async def cart_update(
    line_id: int, body: CartQtyIn, env: PublicEnv, cart_token: CartToken = None
):
    order = _ensure_cart(env, _token(cart_token), create=False)
    if not order:
        raise HTTPException(status_code=404, detail="Cart not found")
    line = order.order_line.filtered(lambda l: l.id == line_id)[:1]
    if not line:
        raise HTTPException(status_code=404, detail="Line not found")
    if body.qty <= 0:
        line.unlink()
    else:
        line.product_uom_qty = body.qty
    return ResponseEnvelope(data=_cart_dict(order))


@cart_router.delete("/cart/items/{line_id}", response_model=ResponseEnvelope[CartOut])
async def cart_remove(line_id: int, env: PublicEnv, cart_token: CartToken = None):
    order = _ensure_cart(env, _token(cart_token), create=False)
    if not order:
        raise HTTPException(status_code=404, detail="Cart not found")
    line = order.order_line.filtered(lambda l: l.id == line_id)[:1]
    if line:
        line.unlink()
    return ResponseEnvelope(data=_cart_dict(order))
