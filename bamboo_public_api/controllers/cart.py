# -*- coding: utf-8 -*-
"""Server-side cart = a draft `sale.order`, so Odoo owns price/tax/promo/stock.

The cart is identified by a `cart_token` (the order's portal `access_token`),
returned in every cart payload. The client persists it (localStorage) and sends
it back as the `X-Cart-Token` header (also accepted as the `cart_token` param or
a cookie). Anonymous carts use the public partner; on login the cart binds to the
logged-in user's partner. Pattern after webkul (create-empty-cart / addtocart).
"""
from odoo import http
from odoo.http import request

from .common import API_ROOT, err, image_url, ok, requires_app


def _cart_token():
    return (
        request.httprequest.headers.get('X-Cart-Token')
        or request.params.get('cart_token')
        or request.httprequest.cookies.get('bamboo_cart')
    )


def _find_cart(token):
    if not token:
        return request.env['sale.order'].sudo()
    return request.env['sale.order'].sudo().search([
        ('access_token', '=', token),
        ('state', 'in', ('draft', 'sent')),
    ], limit=1)


def _cart_partner():
    """Logged-in user's partner, else the public partner (placeholder until checkout)."""
    user = request.env.user
    if user and user.id != request.env.ref('base.public_user').id:
        return user.partner_id
    return request.env.ref('base.public_partner')


def _line_dict(line):
    return {
        'line_id': line.id,
        'product_id': line.product_id.id,
        'name': line.product_id.display_name,
        'qty': line.product_uom_qty,
        'price_unit': line.price_unit,
        'price_subtotal': line.price_subtotal,
        'image_url': image_url('product.product', line.product_id.id),
    }


def _cart_dict(order):
    return {
        'cart_token': order.access_token,
        'order_id': order.id,
        'state': order.state,
        'lines': [_line_dict(l) for l in order.order_line.filtered(lambda x: not x.display_type)],
        'amount_untaxed': order.amount_untaxed,
        'amount_tax': order.amount_tax,
        'amount_total': order.amount_total,
        'currency': order.currency_id.name,
    }


def _ensure_cart(create=True):
    """Return (order, token). Creates a fresh draft order when needed."""
    token = _cart_token()
    order = _find_cart(token)
    if order:
        # Bind an anonymous cart to the user once they log in.
        partner = _cart_partner()
        public = request.env.ref('base.public_partner')
        if order.partner_id == public and partner != public:
            order.write({'partner_id': partner.id})
        return order
    if not create:
        return order
    order = request.env['sale.order'].sudo().create({'partner_id': _cart_partner().id})
    order._portal_ensure_token()
    return order


class BambooPublicCart(http.Controller):

    @http.route(API_ROOT + '/cart', type='http', auth='public', methods=['POST'], csrf=False)
    @requires_app('shop')
    def cart_create(self, **kw):
        order = _ensure_cart(create=True)
        resp = ok(data=_cart_dict(order), status=201)
        resp.set_cookie('bamboo_cart', order.access_token, samesite='None', secure=True)
        return resp

    @http.route(API_ROOT + '/cart', type='http', auth='public', methods=['GET'], csrf=False)
    @requires_app('shop')
    def cart_get(self, **kw):
        order = _ensure_cart(create=False)
        if not order:
            return ok(data=None)
        return ok(data=_cart_dict(order))

    @http.route(API_ROOT + '/cart/items', type='http', auth='public', methods=['POST'], csrf=False)
    @requires_app('shop')
    def cart_add(self, **kw):
        from .common import read_body
        body = read_body()
        try:
            product_id = int(body.get('product_id'))
            qty = float(body.get('qty', 1) or 1)
        except (TypeError, ValueError):
            return err('Invalid product or quantity', 422)
        product = request.env['product.product'].sudo().browse(product_id)
        if not product.exists():
            return err('Product not found', 404)

        order = _ensure_cart(create=True)
        line = order.order_line.filtered(lambda l: l.product_id.id == product_id)[:1]
        if line:
            line.product_uom_qty += qty
        else:
            request.env['sale.order.line'].sudo().create({
                'order_id': order.id,
                'product_id': product_id,
                'product_uom_qty': qty,
            })
        resp = ok(data=_cart_dict(order), status=201)
        resp.set_cookie('bamboo_cart', order.access_token, samesite='None', secure=True)
        return resp

    @http.route(API_ROOT + '/cart/items/<int:line_id>', type='http', auth='public', methods=['PATCH'], csrf=False)
    @requires_app('shop')
    def cart_update(self, line_id, **kw):
        from .common import read_body
        order = _ensure_cart(create=False)
        if not order:
            return err('Cart not found', 404)
        line = order.order_line.filtered(lambda l: l.id == line_id)[:1]
        if not line:
            return err('Line not found', 404)
        try:
            qty = float(read_body().get('qty'))
        except (TypeError, ValueError):
            return err('Invalid quantity', 422)
        if qty <= 0:
            line.unlink()
        else:
            line.product_uom_qty = qty
        return ok(data=_cart_dict(order))

    @http.route(API_ROOT + '/cart/items/<int:line_id>', type='http', auth='public', methods=['DELETE'], csrf=False)
    @requires_app('shop')
    def cart_remove(self, line_id, **kw):
        order = _ensure_cart(create=False)
        if not order:
            return err('Cart not found', 404)
        line = order.order_line.filtered(lambda l: l.id == line_id)[:1]
        if line:
            line.unlink()
        return ok(data=_cart_dict(order))
