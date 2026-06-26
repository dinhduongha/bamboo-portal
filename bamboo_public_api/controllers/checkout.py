# -*- coding: utf-8 -*-
"""Checkout — turn the draft cart into a placed `sale.order`.

Requires a logged-in user (auth='user'). Binds the cart to the user's partner,
optionally writes a shipping address, then confirms. Payment is P5 — for now the
order is confirmed directly and returned. The cart is located by the same
`X-Cart-Token` as cart.py.
"""
from odoo import http
from odoo.http import request

from .common import API_ROOT, err, ok, read_body, requires_app
from .cart import _cart_dict, _find_cart, _cart_token


def _apply_address(order, body):
    """Optionally set a delivery address on the order from posted fields. Updates
    the partner's own contact when it has no address yet; otherwise leaves it."""
    street = (body.get('street') or '').strip()
    if not street:
        return
    partner = order.partner_id
    vals = {
        'street': street,
        'city': body.get('city') or '',
        'zip': body.get('zip') or '',
        'phone': body.get('phone') or partner.phone or '',
    }
    if body.get('country_code'):
        country = request.env['res.country'].sudo().search(
            [('code', '=', body['country_code'].upper())], limit=1)
        if country:
            vals['country_id'] = country.id
    partner.sudo().write(vals)


class BambooPublicCheckout(http.Controller):

    @http.route(API_ROOT + '/checkout/confirm', type='http', auth='user', methods=['POST'], csrf=False)
    @requires_app('shop')
    def confirm(self, **kw):
        order = _find_cart(_cart_token())
        if not order:
            return err('Cart not found', 404)
        if not order.order_line.filtered(lambda l: not l.display_type):
            return err('Cart is empty', 422)

        # Bind the cart to the buyer (it may have been an anonymous cart).
        order.write({'partner_id': request.env.user.partner_id.id})
        _apply_address(order, read_body())
        try:
            order.action_confirm()
        except Exception as exc:
            return err('Could not place order: %s' % exc, 400)
        data = _cart_dict(order)
        data['name'] = order.name
        return ok(data=data, status=201)
