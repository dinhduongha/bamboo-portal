from odoo import api, models
from odoo.exceptions import UserError


class DmsEb2bOrderBridge(models.Model):
    """Close the debt sub-plan 08 named, without deleting anybody's data.

    `TODO.md`, debt 1 of sub-plan 08:

        `dms.eb2b.order` still creates `sale.order` by its own path. It sets
        no `dms_flow_type` and never calls `dms_quote`, so that path has no
        credit check and no assortment check.

    Both halves are true and both matter. Without `dms_flow_type='dsr'` the
    order also gets no Team and no Distributor snapshot, so every report that
    groups by those two cannot see it.

    `action_convert_to_sale` is overridden rather than removed: plan 06
    section 11 forbids a big-bang cutover while clients still call the old
    action, and the same policy kept `action_submit` alive in 10B. The method
    keeps its name and its return shape; only the route underneath changes.
    """
    _inherit = 'dms.eb2b.order'

    def action_convert_to_sale(self):
        """Same entry point, the DSR service underneath."""
        for rec in self:
            if rec.order_status != 'pending':
                raise UserError('Only pending orders can be converted.')
            if rec.converted_to_sale_order_id:
                raise UserError('This order has already been converted.')
            content = rec.order_content or {}
            lines = [{
                'product_id': int(line['product_id']),
                # `quantity`, because `res.partner.dms_quote` reads that key.
                # `qty` silently prices every line at the default of 1.
                'quantity': line.get('qty', 1),
            } for line in content.get('lines', [])]
            if not lines:
                raise UserError('Order content is empty — cannot convert.')

            result = self.env['dms.order.api'].sudo().dms_order_submit(
                rec.res_partner_id.id, lines,
                vals={'note': f'EB2B Order: {rec.order_source_id}'},
                operation_uuid=None)
            if not result.get('order_id'):
                # Refuse loudly. The old path would have created the order
                # regardless, which is precisely the defect: a staging record
                # marked `processed` against a `sale.order` that no gate ever
                # looked at.
                raise UserError(
                    'Cannot convert: %s' % result.get('errors'))
            rec.converted_to_sale_order_id = result['order_id']
            rec.order_status = 'processed'

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': self.converted_to_sale_order_id.id,
            'view_mode': 'form',
        }
