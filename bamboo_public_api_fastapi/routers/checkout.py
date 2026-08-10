"""Checkout — bind the cart to the buyer, capture an address, place free orders.

Requires a signed-in user. A payable cart is left draft and the response asks the
client to run the payment step (`routers/payment.py`), which confirms the order
once the transaction is done; only a free cart is confirmed here.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from odoo.addons.bamboo_public_api.controllers.cart import _cart_dict, _find_cart

from ..schemas.envelope import ResponseEnvelope
from ..schemas.shop import CheckoutIn, CheckoutOut
from ._common import AuthEnv, country_id, require_app
from .cart import _token

checkout_router = APIRouter(
    tags=["Checkout"], dependencies=[Depends(require_app("shop"))]
)


def _apply_address(env, order, body: CheckoutIn) -> None:
    """Write the posted delivery address onto the buyer's partner (`checkout._apply_address`)."""
    street = (body.street or "").strip()
    if not street:
        return
    partner = order.partner_id
    vals = {
        "street": street,
        "city": body.city or "",
        "zip": body.zip or "",
        "phone": body.phone or partner.phone or "",
    }
    country = country_id(env, body.country_code)
    if country:
        vals["country_id"] = country
    partner.sudo().write(vals)


@checkout_router.post(
    "/checkout/confirm", response_model=ResponseEnvelope[CheckoutOut]
)
async def confirm(
    body: CheckoutIn,
    env: AuthEnv,
    cart_token: Optional[str] = Query(default=None, alias="cart_token"),
):
    order = _find_cart(_token(cart_token))
    if not order:
        raise HTTPException(status_code=404, detail="Cart not found")
    if not order.order_line.filtered(lambda l: not l.display_type):
        raise HTTPException(status_code=422, detail="Cart is empty")

    order.write({"partner_id": env.user.partner_id.id})
    _apply_address(env, order, body)

    data = dict(_cart_dict(order), name=order.name)
    if order.amount_total > 0:
        data["requires_payment"] = True
        return ResponseEnvelope(data=data)

    try:
        order.action_confirm()
    except Exception as exc:  # noqa: BLE001 — surfaced to the shopper verbatim
        raise HTTPException(
            status_code=400, detail="Could not place order: %s" % exc
        ) from exc
    data = dict(_cart_dict(order), name=order.name, requires_payment=False)
    return ResponseEnvelope(data=data)
