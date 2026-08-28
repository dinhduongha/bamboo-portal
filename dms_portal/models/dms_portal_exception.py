from odoo import api, fields, models
from odoo.exceptions import UserError


class DmsPortalException(models.Model):
    """A refusal, kept where somebody at the Distributor can act on it.

    `dms.order.api` already declines to build a bad `sale.order` and returns
    the reason to the caller. That protects the data and loses the business:
    the buyer reads "over your credit limit", closes the tab, and nobody at
    the Distributor ever learns a shop tried to order.

    Section 8 keeps this on the inside. Raw refusal detail -- limits,
    assortment names, integration text -- is not portal-facing.
    """
    _name = 'dms.portal.exception'
    _inherit = ['dms.display.name.mixin']
    _dms_display_fields = ('kind', 'outlet_id', 'user_id')
    _description = 'DMS Portal Exception'
    _order = 'create_date desc'

    #: Maps the `code` `dms.order.api` returns onto the operational bucket a
    #: human works from. An unmapped code becomes `other` rather than being
    #: dropped: a refusal nobody can categorise is still a refusal somebody
    #: should see.
    _CODE_TO_KIND = {
        'credit_blocked': 'credit',
        'not_in_assortment': 'assortment',
        'no_distributor': 'distributor',
        'price_changed': 'price',
    }

    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company)
    outlet_id = fields.Many2one(
        'res.partner', string='Outlet', required=True, index=True)
    user_id = fields.Many2one(
        'res.users', string='Portal User', required=True, index=True)
    kind = fields.Selection([
        ('price', 'Price mismatch'),
        ('sku', 'Unknown SKU'),
        ('assortment', 'Outside assortment'),
        ('distributor', 'No serving Distributor'),
        ('credit', 'Credit limit'),
        ('other', 'Other'),
    ], required=True, index=True)
    detail = fields.Text(
        required=True,
        help='The refusal as the service phrased it, including the numbers. '
             '"credit failed" is not something an operator can act on.')
    state = fields.Selection([
        ('open', 'Open'),
        ('resolved', 'Resolved'),
        ('rejected', 'Rejected'),
    ], required=True, default='open', index=True)
    resolved_by_id = fields.Many2one('res.users', readonly=True)
    resolution_date = fields.Datetime(readonly=True)
    resolution_note = fields.Text()

    @api.model
    def _dms_record_errors(self, outlet, errors):
        """Log every refusal `dms.order.api` returned.

        Returns the records, and never raises: this is bookkeeping on a path
        that is already failing, and a queue that turns a refusal into a
        traceback leaves the buyer worse off than no queue at all.
        """
        vals_list = []
        for error in errors or []:
            code = error.get('code') or 'other'
            vals_list.append({
                'outlet_id': outlet.id,
                'company_id': outlet.company_id.id or self.env.company.id,
                'user_id': self.env.uid,
                'kind': self._CODE_TO_KIND.get(code, 'other'),
                'detail': f"[{code}] {error.get('message') or ''}".strip(),
            })
        if not vals_list:
            return self.browse()
        return self.sudo().create(vals_list)

    def action_resolve(self, note=None):
        for rec in self:
            if rec.state != 'open':
                raise UserError(self.env._("Only an open exception can be resolved."))
            rec.write({
                'state': 'resolved',
                'resolved_by_id': self.env.uid,
                'resolution_date': fields.Datetime.now(),
                'resolution_note': note or rec.resolution_note,
            })
        return True
