# -*- coding: utf-8 -*-
"""Portal / My-Account — authenticated self-service for ANY logged-in user.

auth='user', so portal (share=True) AND internal users alike reach it; an internal
user is also a customer. Because the standard `portal` group ships minimal
ir.model.access, every handler runs sudo() and HARD-SCOPES to the caller's
commercial partner hierarchy (`partner_id child_of commercial_partner_id`) — a
missing filter would leak other customers' records. Ownership is re-checked on the
target record before any write/act (never trust the id in the URL).

Endpoints (each presence-guarded on its module):
  GET  /portal/orders [+ /<id>]            POST /portal/orders/<id>/reorder
  GET  /portal/invoices [+ /<id>]          POST /portal/invoices/<id>/pay (P5 stub)
  GET  /portal/subscriptions               POST /portal/subscriptions/<id>/{cancel,renew}
  GET/PATCH /portal/profile
  GET/POST/PATCH/DELETE /portal/addresses [/<id>]
"""
from odoo import http
from odoo.http import request

from .common import (
    API_ROOT, err, module_installed, ok, page_meta, page_params, read_body,
)


def _user():
    """The logged-in user, or None for the public/anonymous user."""
    user = request.env.user
    if not user or user.id == request.env.ref('base.public_user').id:
        return None
    return user


def _commercial():
    """The caller's commercial partner — the root we scope all records to."""
    return request.env.user.partner_id.commercial_partner_id


def _scoped_domain(field='partner_id'):
    """Domain term restricting records to the caller's partner hierarchy."""
    return [(field, 'child_of', _commercial().id)]


# ---- serializers -----------------------------------------------------------

def _order_card(o):
    return {
        'id': o.id,
        'name': o.name,
        'date': o.date_order,
        'state': o.state,
        'amount_total': o.amount_total,
        'amount_untaxed': o.amount_untaxed,
        'amount_tax': o.amount_tax,
        'currency': o.currency_id.name,
        'invoice_status': o.invoice_status,
    }


def _order_detail(o):
    data = _order_card(o)
    data['lines'] = [{
        'id': l.id,
        'name': l.name,
        'product_id': l.product_id.id,
        'qty': l.product_uom_qty,
        'price_unit': l.price_unit,
        'price_subtotal': l.price_subtotal,
    } for l in o.order_line.filtered(lambda x: not x.display_type)]
    data['partner'] = {'id': o.partner_id.id, 'name': o.partner_id.name}
    return data


def _invoice_card(m):
    return {
        'id': m.id,
        'name': m.name,
        'date': m.invoice_date,
        'due_date': m.invoice_date_due,
        'state': m.state,
        'payment_state': m.payment_state,
        'amount_total': m.amount_total,
        'amount_residual': m.amount_residual,
        'currency': m.currency_id.name,
        'move_type': m.move_type,
    }


def _invoice_detail(m):
    data = _invoice_card(m)
    data['lines'] = [{
        'id': l.id,
        'name': l.name,
        'qty': l.quantity,
        'price_unit': l.price_unit,
        'price_subtotal': l.price_subtotal,
    } for l in m.invoice_line_ids.filtered(lambda x: not x.display_type)]
    return data


def _partner_dict(p):
    return {
        'id': p.id,
        'name': p.name,
        'email': p.email or '',
        'phone': p.phone or '',
        'street': p.street or '',
        'street2': p.street2 or '',
        'city': p.city or '',
        'zip': p.zip or '',
        'country_code': p.country_id.code or '',
        'country_id': p.country_id.id or False,
        'type': p.type,
    }


def _set_country(vals, code):
    if not code:
        return
    country = request.env['res.country'].sudo().search([('code', '=', code.upper())], limit=1)
    if country:
        vals['country_id'] = country.id


_PARTNER_WRITABLE = ('name', 'phone', 'street', 'street2', 'city', 'zip')


class BambooPublicPortal(http.Controller):

    # ---- orders ------------------------------------------------------------

    @http.route(API_ROOT + '/portal/orders', type='http', auth='user', methods=['GET'], csrf=False)
    def orders(self, **kw):
        if not _user():
            return err('Authentication required', 401)
        if not module_installed('sale'):
            return err("Orders are not available on this server", 404)
        Order = request.env['sale.order'].sudo()
        domain = _scoped_domain() + [('state', 'not in', ('draft', 'sent', 'cancel'))]
        limit, offset, page = page_params()
        total = Order.search_count(domain)
        orders = Order.search(domain, limit=limit, offset=offset, order='date_order desc')
        return ok(data=[_order_card(o) for o in orders], meta=page_meta(total, limit, page))

    @http.route(API_ROOT + '/portal/orders/<int:order_id>', type='http', auth='user', methods=['GET'], csrf=False)
    def order_detail(self, order_id, **kw):
        if not _user():
            return err('Authentication required', 401)
        order = request.env['sale.order'].sudo().search(
            _scoped_domain() + [('id', '=', order_id)], limit=1)
        if not order:
            return err('Order not found', 404)
        return ok(data=_order_detail(order))

    @http.route(API_ROOT + '/portal/orders/<int:order_id>/reorder', type='http', auth='user', methods=['POST'], csrf=False)
    def reorder(self, order_id, **kw):
        if not _user():
            return err('Authentication required', 401)
        order = request.env['sale.order'].sudo().search(
            _scoped_domain() + [('id', '=', order_id)], limit=1)
        if not order:
            return err('Order not found', 404)
        # Clone the sellable lines into a fresh draft cart for the caller.
        cart = request.env['sale.order'].sudo().create({
            'partner_id': request.env.user.partner_id.id,
        })
        for l in order.order_line.filtered(lambda x: not x.display_type):
            request.env['sale.order.line'].sudo().create({
                'order_id': cart.id,
                'product_id': l.product_id.id,
                'product_uom_qty': l.product_uom_qty,
            })
        cart._portal_ensure_token()
        resp = ok(data={'cart_token': cart.access_token, 'order_id': cart.id}, status=201)
        resp.set_cookie('bamboo_cart', cart.access_token, samesite='None', secure=True)
        return resp

    # ---- invoices ----------------------------------------------------------

    @http.route(API_ROOT + '/portal/invoices', type='http', auth='user', methods=['GET'], csrf=False)
    def invoices(self, **kw):
        if not _user():
            return err('Authentication required', 401)
        if not module_installed('account'):
            return err("Invoices are not available on this server", 404)
        Move = request.env['account.move'].sudo()
        domain = _scoped_domain() + [
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('state', '=', 'posted'),
        ]
        limit, offset, page = page_params()
        total = Move.search_count(domain)
        moves = Move.search(domain, limit=limit, offset=offset, order='invoice_date desc, id desc')
        return ok(data=[_invoice_card(m) for m in moves], meta=page_meta(total, limit, page))

    @http.route(API_ROOT + '/portal/invoices/<int:move_id>', type='http', auth='user', methods=['GET'], csrf=False)
    def invoice_detail(self, move_id, **kw):
        if not _user():
            return err('Authentication required', 401)
        move = request.env['account.move'].sudo().search(
            _scoped_domain() + [
                ('id', '=', move_id),
                ('move_type', 'in', ('out_invoice', 'out_refund')),
            ], limit=1)
        if not move:
            return err('Invoice not found', 404)
        return ok(data=_invoice_detail(move))

    @http.route(API_ROOT + '/portal/invoices/<int:move_id>/pay', type='http', auth='user', methods=['POST'], csrf=False)
    def invoice_pay(self, move_id, **kw):
        if not _user():
            return err('Authentication required', 401)
        move = request.env['account.move'].sudo().search(
            _scoped_domain() + [('id', '=', move_id)], limit=1)
        if not move:
            return err('Invoice not found', 404)
        # Start a payment transaction for this invoice via the shared payment flow.
        from .common import read_body
        from .payment import start_transaction, _tx_payload
        tx, error = start_transaction(read_body().get('provider_id'), 'invoice', move.id)
        if error:
            return err(error[0], error[1])
        return ok(data=_tx_payload(tx), status=201)

    # ---- subscriptions -----------------------------------------------------

    @http.route(API_ROOT + '/portal/subscriptions', type='http', auth='user', methods=['GET'], csrf=False)
    def subscriptions(self, **kw):
        if not _user():
            return err('Authentication required', 401)
        if not module_installed('sale_subscription'):
            return err("Subscriptions are not available on this server", 404)
        # In Odoo 17+ subscriptions are sale.order records flagged is_subscription.
        Order = request.env['sale.order'].sudo()
        domain = _scoped_domain() + [('is_subscription', '=', True)]
        limit, offset, page = page_params()
        total = Order.search_count(domain)
        subs = Order.search(domain, limit=limit, offset=offset, order='id desc')
        return ok(data=[_order_card(s) for s in subs], meta=page_meta(total, limit, page))

    @http.route(API_ROOT + '/portal/subscriptions/<int:sub_id>/cancel', type='http', auth='user', methods=['POST'], csrf=False)
    def subscription_cancel(self, sub_id, **kw):
        if not _user():
            return err('Authentication required', 401)
        if not module_installed('sale_subscription'):
            return err("Subscriptions are not available on this server", 404)
        sub = request.env['sale.order'].sudo().search(
            _scoped_domain() + [('id', '=', sub_id), ('is_subscription', '=', True)], limit=1)
        if not sub:
            return err('Subscription not found', 404)
        try:
            if hasattr(sub, 'set_close'):
                sub.set_close()
            else:
                sub.action_cancel()
        except Exception as exc:
            return err('Could not cancel: %s' % exc, 400)
        return ok(data=_order_card(sub))

    # ---- profile -----------------------------------------------------------

    @http.route(API_ROOT + '/portal/profile', type='http', auth='user', methods=['GET'], csrf=False)
    def profile_get(self, **kw):
        if not _user():
            return err('Authentication required', 401)
        return ok(data=_partner_dict(request.env.user.partner_id))

    @http.route(API_ROOT + '/portal/profile', type='http', auth='user', methods=['PATCH'], csrf=False)
    def profile_set(self, **kw):
        if not _user():
            return err('Authentication required', 401)
        body = read_body()
        partner = request.env.user.partner_id.sudo()
        vals = {f: body[f] for f in _PARTNER_WRITABLE if f in body}
        _set_country(vals, body.get('country_code'))
        if vals:
            partner.write(vals)
        return ok(data=_partner_dict(partner))

    # ---- addresses ---------------------------------------------------------

    @http.route(API_ROOT + '/portal/addresses', type='http', auth='user', methods=['GET'], csrf=False)
    def addresses(self, **kw):
        if not _user():
            return err('Authentication required', 401)
        children = request.env['res.partner'].sudo().search([
            ('id', 'child_of', _commercial().id),
            ('id', '!=', _commercial().id),
            ('type', 'in', ('delivery', 'invoice', 'other')),
        ], order='id desc')
        return ok(data=[_partner_dict(p) for p in children])

    @http.route(API_ROOT + '/portal/addresses', type='http', auth='user', methods=['POST'], csrf=False)
    def address_create(self, **kw):
        if not _user():
            return err('Authentication required', 401)
        body = read_body()
        vals = {f: body.get(f) or '' for f in _PARTNER_WRITABLE}
        if not vals.get('name'):
            return err('Name is required', 422)
        vals['parent_id'] = _commercial().id
        vals['type'] = body.get('type') if body.get('type') in ('delivery', 'invoice', 'other') else 'other'
        _set_country(vals, body.get('country_code'))
        partner = request.env['res.partner'].sudo().create(vals)
        return ok(data=_partner_dict(partner), status=201)

    @http.route(API_ROOT + '/portal/addresses/<int:partner_id>', type='http', auth='user', methods=['PATCH'], csrf=False)
    def address_update(self, partner_id, **kw):
        if not _user():
            return err('Authentication required', 401)
        partner = self._own_address(partner_id)
        if not partner:
            return err('Address not found', 404)
        body = read_body()
        vals = {f: body[f] for f in _PARTNER_WRITABLE if f in body}
        if body.get('type') in ('delivery', 'invoice', 'other'):
            vals['type'] = body['type']
        _set_country(vals, body.get('country_code'))
        if vals:
            partner.write(vals)
        return ok(data=_partner_dict(partner))

    @http.route(API_ROOT + '/portal/addresses/<int:partner_id>', type='http', auth='user', methods=['DELETE'], csrf=False)
    def address_delete(self, partner_id, **kw):
        if not _user():
            return err('Authentication required', 401)
        partner = self._own_address(partner_id)
        if not partner:
            return err('Address not found', 404)
        # Archive (a partner referenced by orders/invoices can't be unlinked).
        partner.write({'active': False})
        return ok(data={'deleted': partner_id})

    def _own_address(self, partner_id):
        """A child address belonging to the caller's commercial partner, or empty."""
        return request.env['res.partner'].sudo().search([
            ('id', '=', partner_id),
            ('id', 'child_of', _commercial().id),
            ('id', '!=', _commercial().id),
        ], limit=1)
