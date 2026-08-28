from odoo import api, models
from odoo.exceptions import AccessError


class DmsPortalApi(models.AbstractModel):
    """The portal's whole RPC surface.

    Every method here does the same two things and nothing else: check the
    caller is entitled to the Outlet they named, then hand the work to the
    service in `dms` that already does it. There is no pricing, no credit
    arithmetic and no order building in this file, on purpose -- a second
    copy of any of those is the copy that drifts.

    What `dms` cannot do for us: `dms.order.api` trusts its caller, because
    a salesman calling it is already filtered by the record rules of `dms`.
    A portal user has no such rule behind them, so the `outlet_id` they send
    is an arbitrary integer until this layer says otherwise.
    """
    _name = 'dms.portal.api'
    _description = 'DMS Portal API'

    @api.model
    def _dms_portal_outlet(self, outlet_id=None):
        """The Outlet this call may act on, or `AccessError`.

        With no `outlet_id`, and exactly one approved entitlement, that one
        is used -- the common case is a buyer with a single shop, and making
        them repeat its id buys nothing.
        """
        allowed = self.env.user.dms_allowed_partner_ids()
        if outlet_id is None:
            if len(allowed) == 1:
                return self.env['res.partner'].browse(allowed[0])
            raise AccessError(
                'Name the outlet: this account is entitled to '
                f'{len(allowed)} of them.')
        outlet_id = int(outlet_id)
        if outlet_id not in allowed:
            # Refuse rather than return nothing. An empty result would say
            # "that outlet has no products", which tells the caller the
            # outlet exists.
            raise AccessError(
                'No approved entitlement for this outlet.')
        return self.env['res.partner'].browse(outlet_id)

    @api.model
    def dms_portal_catalog(self, outlet_id=None):
        """POST /web/dataset/call_kw/dms.portal.api/dms_portal_catalog
           POST /json/2/dms.portal.api/dms_portal_catalog

        No pricelist parameter, deliberately: section 5 says the server
        resolves it. A signature with nowhere to put one cannot be talked
        into accepting one later by accident.
        """
        allowed = self.env.user.dms_allowed_partner_ids()
        if not allowed:
            return []
        outlet = self._dms_portal_outlet(outlet_id)
        listings = self.env['dms.outlet.product.listing'].sudo()._effective_for(
            outlet)
        quote = outlet.sudo().dms_quote([
            {'product_id': line.product_id.id, 'quantity': 1}
            for line in listings
        ]) if listings else {'lines': []}
        by_product = {row['product_id']: row for row in quote['lines']}
        out = []
        for line in listings:
            row = by_product.get(line.product_id.id)
            if not row:
                continue
            # Explicit allow-list of what leaves the server. A dict built by
            # subtraction lets the next field added to the quote reach the
            # portal by default; section 8 forbids exactly that for margin.
            out.append({
                'product_id': line.product_id.id,
                'name': line.product_id.display_name,
                'uom_id': row['uom_id'],
                'price_unit': row['price_unit'],
                'currency_id': quote.get('currency_id'),
            })
        return out

    @api.model
    def dms_portal_quote(self, outlet_id, lines):
        """POST /web/dataset/call_kw/dms.portal.api/dms_portal_quote
           POST /json/2/dms.portal.api/dms_portal_quote

        Entitlement, then straight through. `dms.order.api.dms_cart_quote`
        already ignores a client-supplied `price_unit`, `discount` and tax,
        and already returns `errors[{'code': 'not_in_assortment'}]` -- with
        tests in `dms/tests/test_pricing_service.py`. Recomputing any of it
        here would be a second answer to the same question.
        """
        outlet = self._dms_portal_outlet(outlet_id)
        return self.env['dms.order.api'].sudo().dms_cart_quote(
            outlet.id, lines)

    @api.model
    def dms_portal_submit(self, outlet_id, lines, vals=None,
                          operation_uuid=None, accept_price_change=False):
        """POST /web/dataset/call_kw/dms.portal.api/dms_portal_submit
           POST /json/2/dms.portal.api/dms_portal_submit

        `dms.order.api.dms_order_submit` sets `dms_flow_type='dsr'` and calls
        `dms_submit()`, which is what puts the credit gate and the assortment
        gate in the path. The debt sub-plan 08 left -- `dms.eb2b.order`
        building a `sale.order` by its own route, with neither gate -- is
        exactly what NOT delegating here would recreate on a second channel.

        `vals` is not filtered here: `_SUBMIT_FIELDS` in `dms.order.api` is an
        allow-list, so an unknown key is dropped there. Filtering twice would
        mean two lists to keep in step.
        """
        outlet = self._dms_portal_outlet(outlet_id)
        result = self.env['dms.order.api'].sudo().dms_order_submit(
            outlet.id, lines, vals=vals, operation_uuid=operation_uuid,
            accept_price_change=accept_price_change)
        # Log the refusal, then return it unchanged. Swallowing it here would
        # leave the buyer looking at a form that did nothing.
        self.env['dms.portal.exception']._dms_record_errors(
            outlet, result.get('errors'))
        return result
