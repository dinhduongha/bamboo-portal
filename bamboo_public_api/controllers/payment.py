# -*- coding: utf-8 -*-
"""Payment — pay a cart (checkout) or an outstanding invoice online.

Odoo 19 API: create a `payment.transaction` with
`env['payment.transaction'].create(vals)` (there is no
`sale.order._create_payment_transaction` anymore) and drive it with
`_get_processing_values()`. Redirect providers return a form/URL to POST to;
the Demo provider has no external redirect — its outcome is simulated through
`action_demo_set_*`, exposed here as the `/demo` endpoint.

On a `done` transaction we confirm any linked draft sale order (Odoo does not do
that for us here); invoices are reconciled by the payment framework itself.
"""
from odoo import http
from odoo.http import request

from .common import API_ROOT, err, image_url, ok, read_body, requires_app
from .cart import _cart_token, _find_cart


def _enabled_providers():
    return request.env['payment.provider'].sudo().search([
        ('state', 'in', ('enabled', 'test')),
    ])


def _provider_dict(p):
    return {
        'id': p.id,
        'name': p.name,
        'code': p.code,
        'state': p.state,  # 'enabled' | 'test'
        'image_url': image_url('payment.provider', p.id, 'image_128'),
        'demo': p.code == 'demo',
    }


def _tx_dict(tx):
    return {
        'reference': tx.reference,
        'state': tx.state,  # draft|pending|authorized|done|cancel|error
        'amount': tx.amount,
        'currency': tx.currency_id.name,
        'provider_code': tx.provider_code,
        'demo': tx.provider_code == 'demo',
    }


def _owns_tx(tx):
    """The transaction must belong to the caller (same commercial partner)."""
    me = request.env.user.partner_id.commercial_partner_id
    return bool(tx) and tx.partner_id.commercial_partner_id == me


def _settle_on_done(tx):
    """When a transaction is done, run the framework post-processing (which
    creates/reconciles the invoice payment) and confirm any linked draft sale
    order so the checkout completes."""
    if tx.state != 'done':
        return
    try:
        tx.sudo()._post_process()  # create + reconcile the account.payment
    except Exception:
        pass  # best-effort; the poll will retry on the next call
    for order in tx.sale_order_ids:
        if order.state in ('draft', 'sent'):
            order.sudo().action_confirm()


def start_transaction(provider_id, kind='order', ref_id=None):
    """Create a payment.transaction for the current user's cart (`kind='order'`)
    or an invoice (`kind='invoice'`, `ref_id=<move id>`). Shared by the checkout
    payment endpoint and the portal invoice Pay-now.

    Returns `(tx, error)` where `error` is `(message, status)` or `None`.
    """
    provider = request.env['payment.provider'].sudo().browse(int(provider_id or 0))
    if not provider.exists() or provider.state not in ('enabled', 'test'):
        return None, ('Invalid payment provider', 422)

    partner = request.env.user.partner_id
    if kind == 'invoice':
        move = request.env['account.move'].sudo().browse(int(ref_id or 0))
        if not move.exists() or move.partner_id.commercial_partner_id != partner.commercial_partner_id:
            return None, ('Invoice not found', 404)
        amount = move.amount_residual
        currency = move.currency_id
        link = {'invoice_ids': [(6, 0, [move.id])]}
        prefix = move.name
    else:
        order = _find_cart(_cart_token())
        if not order:
            return None, ('Cart not found', 404)
        order.write({'partner_id': partner.id})
        amount = order.amount_total
        currency = order.currency_id
        link = {'sale_order_ids': [(6, 0, [order.id])]}
        prefix = order.name

    if amount <= 0:
        return None, ('Nothing to pay', 422)

    pm = provider.payment_method_ids[:1]
    if not pm:
        return None, ('Provider has no payment method configured', 422)

    PT = request.env['payment.transaction'].sudo()
    tx = PT.create({
        'provider_id': provider.id,
        'payment_method_id': pm.id,
        'reference': PT._compute_reference(provider.code, prefix=prefix or 'BAMBOO'),
        'amount': amount,
        'currency_id': currency.id,
        'partner_id': partner.id,
        'operation': 'online_redirect',
        **link,
    })
    return tx, None


def _tx_payload(tx):
    """The tx dict plus the redirect form/URL when the provider supplies one."""
    data = _tx_dict(tx)
    try:
        pv = tx._get_processing_values()
        data['redirect_form_html'] = pv.get('redirect_form_html') or ''
    except Exception:
        data['redirect_form_html'] = ''
    return data


class BambooPublicPayment(http.Controller):

    @http.route(API_ROOT + '/payment/providers', type='http', auth='public', methods=['GET'], csrf=False)
    @requires_app('payment')
    def providers(self, **kw):
        """List the payment providers a customer may choose (enabled or test)."""
        return ok(data=[_provider_dict(p) for p in _enabled_providers()])

    @http.route(API_ROOT + '/payment/transaction', type='http', auth='user', methods=['POST'], csrf=False)
    @requires_app('payment')
    def create_transaction(self, **kw):
        """Create a transaction for the cart (`kind=order`) or an invoice
        (`kind=invoice`, `ref_id=<move id>`) with the chosen provider."""
        body = read_body()
        tx, error = start_transaction(
            body.get('provider_id'), body.get('kind') or 'order', body.get('ref_id'),
        )
        if error:
            return err(error[0], error[1])
        return ok(data=_tx_payload(tx), status=201)

    @http.route(API_ROOT + '/payment/demo', type='http', auth='user', methods=['POST'], csrf=False)
    @requires_app('payment')
    def demo_process(self, **kw):
        """Simulate a Demo-provider outcome. Body: `{reference, outcome}` where
        outcome is done|cancel|error. The reference is read from the body (not the
        path) because invoice references contain slashes."""
        body = read_body()
        tx = request.env['payment.transaction'].sudo().search(
            [('reference', '=', body.get('reference'))], limit=1)
        if not _owns_tx(tx) or tx.provider_code != 'demo':
            return err('Transaction not found', 404)
        outcome = body.get('outcome') or 'done'
        if outcome == 'done':
            tx.action_demo_set_done()
        elif outcome == 'cancel':
            tx.action_demo_set_canceled()
        else:
            tx.action_demo_set_error()
        _settle_on_done(tx)
        return ok(data=_tx_dict(tx))

    @http.route(API_ROOT + '/payment/status', type='http', auth='user', methods=['GET'], csrf=False)
    @requires_app('payment')
    def transaction_status(self, reference=None, **kw):
        """Poll a transaction's state by `?reference=` (and settle a linked order
        if it just finished out-of-band via a redirect provider)."""
        tx = request.env['payment.transaction'].sudo().search(
            [('reference', '=', reference)], limit=1)
        if not _owns_tx(tx):
            return err('Transaction not found', 404)
        _settle_on_done(tx)
        return ok(data=_tx_dict(tx))
