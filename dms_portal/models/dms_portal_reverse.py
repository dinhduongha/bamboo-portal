from odoo import api, models
from odoo.exceptions import AccessError, UserError


class DmsPortalReverse(models.AbstractModel):
    """Return and claim requests from the portal.

    Neither is approved here. Section 8: "Portal cannot approve its own
    credit/claim/return." The eligibility arithmetic stays where plan 10 put
    it -- `dms.return.order._dms_check_eligibility` already knows that
    requested qty may not exceed delivered minus ALREADY RETURNED, which is
    the term people forget and the reason the same case gets credited three
    times without anyone committing fraud.
    """
    _inherit = 'dms.portal.api'

    @api.model
    def dms_portal_request_return(self, outlet_id, lines, reason=None,
                                  attachment_ids=None, operation_uuid=None):
        """POST /web/dataset/call_kw/dms.portal.api/dms_portal_request_return
           POST /json/2/dms.portal.api/dms_portal_request_return

        `lines`: [{'product_id': int, 'qty': float, 'sale_line_id': int,
                   'return_reason': str}]. No prices: plan 10 fixed the price
        at the source document, and a client-supplied one would be a credit
        note the buyer wrote themselves.
        """
        outlet = self._dms_portal_outlet(outlet_id)
        if not lines:
            raise UserError(self.env._("A return needs at least one line."))
        # Every portal line must name its source sale line.
        #
        # `dms.return.order._dms_check_eligibility` already allows an
        # undocumented return -- but only with a stated exception reason AND
        # only for a Supervisor or Warehouse user. A portal buyer is neither,
        # so without this the buyer's request dies deep inside the back-office
        # guard with a message written for staff. Refusing here says the true
        # thing: section 6 scopes portal returns to "source delivery
        # eligibility", and a return with no source is not a portal case.
        undocumented = [line for line in lines if not line.get('sale_line_id')]
        if undocumented:
            raise UserError(
                self.env._("A return from the portal has to name the delivery line it came from. Contact your sales representative for a return without one."))

        def _run():
            order = self.env['dms.return.order'].sudo().create({
                'res_partner_id': outlet.id,
                'company_id': outlet.company_id.id,
                'notes': reason or '',
                'attachment_ids': [(6, 0, list(attachment_ids or []))],
                'line_ids': [(0, 0, {
                    'product_id': int(line['product_id']),
                    'qty': float(line['qty']),
                    'sale_line_id': line.get('sale_line_id') or False,
                    'return_reason': line.get('return_reason') or 'other',
                }) for line in lines],
            })
            # `dms_submit` carries the eligibility guard. Writing
            # `status = 'submitted'` instead would skip it, and the guard
            # would then live in one place that the portal does not use.
            order.dms_submit()
            return order

        order, replayed = self.env['dms.sync.operation']._dms_once(
            operation_uuid, 'portal.return.submit',
            {'outlet_id': outlet.id,
             'lines': sorted((int(l['product_id']), float(l['qty']))
                             for l in lines)},
            _run)
        return {'return_id': order.id, 'status': order.status,
                'replayed': replayed}

    @api.model
    def dms_portal_submit_claim(self, outlet_id, vals, attachment_ids=None,
                                operation_uuid=None):
        """POST /web/dataset/call_kw/dms.portal.api/dms_portal_submit_claim
           POST /json/2/dms.portal.api/dms_portal_submit_claim

        The signature has nowhere to put an eligible or approved amount, and
        `dms.trade.api._SUBMIT_FIELDS` drops them from `vals` as well. Both,
        deliberately: fixing only one means the next edit removes the other
        without noticing (07C settled this).
        """
        outlet = self._dms_portal_outlet(outlet_id)
        clean = dict(vals or {})
        # The beneficiary is the entitled outlet, not whoever the caller
        # names. Everything else `dms.trade.api` filters.
        clean['beneficiary_partner_id'] = outlet.id
        clean['company_id'] = outlet.company_id.id
        return self.env['dms.trade.api'].sudo().dms_claim_submit(
            clean, attachment_ids=attachment_ids,
            operation_uuid=operation_uuid)
