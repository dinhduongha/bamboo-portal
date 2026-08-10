"""Portal / My-Account — authenticated self-service for ANY signed-in user.

Portal (share=True) and internal users alike: an internal user is also a customer.
Because the standard `portal` group ships minimal `ir.model.access`, every handler
reads through `sudo()` and HARD-SCOPES to the caller's commercial partner
hierarchy — a missing filter would leak other customers' records. Ownership is
re-checked on the target record before any write (never trust the id in the URL).

The scoping helpers and serializers are the controller's own, so the two modes
cannot drift apart on the part that matters.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response

from odoo.addons.bamboo_public_api.controllers.payment import (
    _tx_payload,
    start_transaction,
)
from odoo.addons.bamboo_public_api.controllers.portal import (
    _PARTNER_WRITABLE,
    _commercial,
    _invoice_card,
    _invoice_detail,
    _order_card,
    _order_detail,
    _partner_dict,
    _scoped_domain,
)

from ..schemas.envelope import ResponseEnvelope
from ..schemas.portal import (
    DeletedOut,
    InvoiceCardOut,
    InvoiceDetailOut,
    OrderCardOut,
    OrderDetailOut,
    PartnerIn,
    PartnerOut,
    PayIn,
    ReorderOut,
    TransactionPayloadOut,
)
from ._common import AuthEnv, Paging, country_id, meta_page, require_module
from .cart import CART_COOKIE

portal_router = APIRouter(tags=["Portal"])

_ADDRESS_TYPES = ("delivery", "invoice", "other")


# --- orders -----------------------------------------------------------------


@portal_router.get(
    "/portal/orders",
    response_model=ResponseEnvelope[List[OrderCardOut]],
    dependencies=[Depends(require_module("sale", "Orders"))],
)
async def orders(env: AuthEnv, paging: Paging):
    Order = env["sale.order"].sudo()
    domain = _scoped_domain() + [("state", "not in", ("draft", "sent", "cancel"))]
    total = Order.search_count(domain)
    records = Order.search(
        domain, limit=paging.limit, offset=paging.offset, order="date_order desc"
    )
    return ResponseEnvelope(
        data=[_order_card(o) for o in records], meta=meta_page(total, paging)
    )


@portal_router.get(
    "/portal/orders/{order_id}", response_model=ResponseEnvelope[OrderDetailOut]
)
async def order_detail(order_id: int, env: AuthEnv):
    order = env["sale.order"].sudo().search(
        _scoped_domain() + [("id", "=", order_id)], limit=1
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return ResponseEnvelope(data=_order_detail(order))


@portal_router.post(
    "/portal/orders/{order_id}/reorder",
    response_model=ResponseEnvelope[ReorderOut],
    status_code=201,
)
async def reorder(order_id: int, env: AuthEnv, response: Response):
    """Clone the sellable lines of a past order into a fresh draft cart."""
    order = env["sale.order"].sudo().search(
        _scoped_domain() + [("id", "=", order_id)], limit=1
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    cart = env["sale.order"].sudo().create({"partner_id": env.user.partner_id.id})
    for line in order.order_line.filtered(lambda x: not x.display_type):
        env["sale.order.line"].sudo().create(
            {
                "order_id": cart.id,
                "product_id": line.product_id.id,
                "product_uom_qty": line.product_uom_qty,
            }
        )
    cart._portal_ensure_token()
    response.set_cookie(CART_COOKIE, cart.access_token, samesite="none", secure=True)
    return ResponseEnvelope(
        data=ReorderOut(cart_token=cart.access_token, order_id=cart.id)
    )


# --- invoices ---------------------------------------------------------------

_CUSTOMER_MOVES = [("move_type", "in", ("out_invoice", "out_refund"))]


@portal_router.get(
    "/portal/invoices",
    response_model=ResponseEnvelope[List[InvoiceCardOut]],
    dependencies=[Depends(require_module("account", "Invoices"))],
)
async def invoices(env: AuthEnv, paging: Paging):
    Move = env["account.move"].sudo()
    domain = _scoped_domain() + _CUSTOMER_MOVES + [("state", "=", "posted")]
    total = Move.search_count(domain)
    records = Move.search(
        domain,
        limit=paging.limit,
        offset=paging.offset,
        order="invoice_date desc, id desc",
    )
    return ResponseEnvelope(
        data=[_invoice_card(m) for m in records], meta=meta_page(total, paging)
    )


@portal_router.get(
    "/portal/invoices/{move_id}", response_model=ResponseEnvelope[InvoiceDetailOut]
)
async def invoice_detail(move_id: int, env: AuthEnv):
    move = env["account.move"].sudo().search(
        _scoped_domain() + [("id", "=", move_id)] + _CUSTOMER_MOVES, limit=1
    )
    if not move:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return ResponseEnvelope(data=_invoice_detail(move))


@portal_router.post(
    "/portal/invoices/{move_id}/pay",
    response_model=ResponseEnvelope[TransactionPayloadOut],
    status_code=201,
)
async def invoice_pay(move_id: int, body: PayIn, env: AuthEnv):
    move = env["account.move"].sudo().search(
        _scoped_domain() + [("id", "=", move_id)], limit=1
    )
    if not move:
        raise HTTPException(status_code=404, detail="Invoice not found")
    tx, error = start_transaction(body.provider_id, "invoice", move.id)
    if error:
        raise HTTPException(status_code=error[1], detail=error[0])
    return ResponseEnvelope(data=_tx_payload(tx))


# --- subscriptions ----------------------------------------------------------

_SUBSCRIPTION = [("is_subscription", "=", True)]


@portal_router.get(
    "/portal/subscriptions",
    response_model=ResponseEnvelope[List[OrderCardOut]],
    dependencies=[Depends(require_module("sale_subscription", "Subscriptions"))],
)
async def subscriptions(env: AuthEnv, paging: Paging):
    """Odoo 17+ models subscriptions as `sale.order` records flagged
    `is_subscription`."""
    Order = env["sale.order"].sudo()
    domain = _scoped_domain() + _SUBSCRIPTION
    total = Order.search_count(domain)
    records = Order.search(
        domain, limit=paging.limit, offset=paging.offset, order="id desc"
    )
    return ResponseEnvelope(
        data=[_order_card(s) for s in records], meta=meta_page(total, paging)
    )


@portal_router.post(
    "/portal/subscriptions/{sub_id}/cancel",
    response_model=ResponseEnvelope[OrderCardOut],
    dependencies=[Depends(require_module("sale_subscription", "Subscriptions"))],
)
async def subscription_cancel(sub_id: int, env: AuthEnv):
    sub = env["sale.order"].sudo().search(
        _scoped_domain() + [("id", "=", sub_id)] + _SUBSCRIPTION, limit=1
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    try:
        if hasattr(sub, "set_close"):
            sub.set_close()
        else:
            sub.action_cancel()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400, detail="Could not cancel: %s" % exc
        ) from exc
    return ResponseEnvelope(data=_order_card(sub))


# --- profile ----------------------------------------------------------------


def _write_partner(env, partner, body: PartnerIn, with_type: bool = False) -> None:
    vals = {
        f: getattr(body, f)
        for f in _PARTNER_WRITABLE
        if getattr(body, f, None) is not None
    }
    if with_type and body.type in _ADDRESS_TYPES:
        vals["type"] = body.type
    country = country_id(env, body.country_code)
    if country:
        vals["country_id"] = country
    if vals:
        partner.write(vals)


@portal_router.get("/portal/profile", response_model=ResponseEnvelope[PartnerOut])
async def profile_get(env: AuthEnv):
    return ResponseEnvelope(data=_partner_dict(env.user.partner_id))


@portal_router.patch("/portal/profile", response_model=ResponseEnvelope[PartnerOut])
async def profile_set(body: PartnerIn, env: AuthEnv):
    partner = env.user.partner_id.sudo()
    _write_partner(env, partner, body)
    return ResponseEnvelope(data=_partner_dict(partner))


# --- addresses --------------------------------------------------------------


def _own_address(env, partner_id: int):
    """A child address of the caller's commercial partner, or empty."""
    return env["res.partner"].sudo().search(
        [
            ("id", "=", partner_id),
            ("id", "child_of", _commercial().id),
            ("id", "!=", _commercial().id),
        ],
        limit=1,
    )


@portal_router.get(
    "/portal/addresses", response_model=ResponseEnvelope[List[PartnerOut]]
)
async def addresses(env: AuthEnv):
    children = env["res.partner"].sudo().search(
        [
            ("id", "child_of", _commercial().id),
            ("id", "!=", _commercial().id),
            ("type", "in", _ADDRESS_TYPES),
        ],
        order="id desc",
    )
    return ResponseEnvelope(data=[_partner_dict(p) for p in children])


@portal_router.post(
    "/portal/addresses",
    response_model=ResponseEnvelope[PartnerOut],
    status_code=201,
)
async def address_create(body: PartnerIn, env: AuthEnv):
    vals = {f: getattr(body, f) or "" for f in _PARTNER_WRITABLE}
    if not vals.get("name"):
        raise HTTPException(status_code=422, detail="Name is required")
    vals["parent_id"] = _commercial().id
    vals["type"] = body.type if body.type in _ADDRESS_TYPES else "other"
    country = country_id(env, body.country_code)
    if country:
        vals["country_id"] = country
    partner = env["res.partner"].sudo().create(vals)
    return ResponseEnvelope(data=_partner_dict(partner))


@portal_router.patch(
    "/portal/addresses/{partner_id}", response_model=ResponseEnvelope[PartnerOut]
)
async def address_update(partner_id: int, body: PartnerIn, env: AuthEnv):
    partner = _own_address(env, partner_id)
    if not partner:
        raise HTTPException(status_code=404, detail="Address not found")
    _write_partner(env, partner, body, with_type=True)
    return ResponseEnvelope(data=_partner_dict(partner))


@portal_router.delete(
    "/portal/addresses/{partner_id}", response_model=ResponseEnvelope[DeletedOut]
)
async def address_delete(partner_id: int, env: AuthEnv):
    partner = _own_address(env, partner_id)
    if not partner:
        raise HTTPException(status_code=404, detail="Address not found")
    # Archive: a partner referenced by orders/invoices cannot be unlinked.
    partner.write({"active": False})
    return ResponseEnvelope(data=DeletedOut(deleted=partner_id))
