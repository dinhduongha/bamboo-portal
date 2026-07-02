# -*- coding: utf-8 -*-
"""Checkout — bind the cart to the buyer and capture the shipping address.

Requires a logged-in user (auth='user'). Binds the cart to the user's partner and
optionally writes a shipping address. A FREE cart (total <= 0) is confirmed right
here; a payable cart is left draft and the response asks the client to run the
payment step (see payment.py), which confirms the order once the transaction is
done. The cart is located by the same `X-Cart-Token` as cart.py.
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

        # A payable cart is confirmed by the payment step (payment.py) once the
        # transaction is done; only a free cart is placed directly here.
        if order.amount_total > 0:
            data = _cart_dict(order)
            data['name'] = order.name
            data['requires_payment'] = True
            return ok(data=data, status=200)

        try:
            order.action_confirm()
        except Exception as exc:
            return err('Could not place order: %s' % exc, 400)
        data = _cart_dict(order)
        data['name'] = order.name
        data['requires_payment'] = False
        return ok(data=data, status=201)
