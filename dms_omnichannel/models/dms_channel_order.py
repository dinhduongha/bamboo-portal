import hashlib
import json

from odoo import api, fields, models
from odoo.exceptions import UserError


class DmsChannelOrder(models.Model):
    """The external order, keyed the way plan 18 section 4 keys it.

    `(channel_account, external_order_id)` -- NOT `external_order_id` alone.
    Two channels number their orders independently, so a global unique key
    rejects a legitimate TikTok order because a Zalo order happens to share
    its number. `dms.eb2b.order` in core carries exactly that global key
    today, and section 11 lists fixing it as migration work.

    Section 6: external price, discount and stock are a SNAPSHOT for
    reconciliation. Conversion goes through the DSR service, which resolves
    SKU, assortment, pricelist and credit itself.
    """
    _name = 'dms.channel.order'
    _inherit = ['dms.display.name.mixin']
    _dms_display_fields = ('external_order_id', 'partner_id')
    _description = 'DMS External Channel Order'
    _order = 'received_at desc'

    _unique_channel_external_order = models.Constraint(
        'UNIQUE(channel_account_id, external_order_id)',
        'This external order is already recorded for this channel account.',
    )

    channel_account_id = fields.Many2one(
        'dms.channel.account', required=True, index=True, ondelete='restrict')
    company_id = fields.Many2one(
        related='channel_account_id.company_id', store=True, index=True)
    external_order_id = fields.Char(required=True, index=True)
    identity_id = fields.Many2one('dms.channel.identity', index=True)
    partner_id = fields.Many2one('res.partner', string='Outlet', index=True)
    received_at = fields.Datetime(
        required=True, default=fields.Datetime.now, index=True)
    payload_checksum = fields.Char(
        required=True, index=True,
        help='SHA-256 of the normalised payload. Two deliveries of the same '
             'event carry the same checksum; a genuine amendment does not.')
    state = fields.Selection([
        ('received', 'Received'),
        ('converted', 'Converted'),
        ('exception', 'Exception'),
        ('cancelled', 'Cancelled'),
    ], required=True, default='received', index=True)
    sale_order_id = fields.Many2one('sale.order', readonly=True, index=True)
    exception_detail = fields.Text()

    @api.model
    def _dms_checksum(self, payload):
        """Stable across dict ordering, so a re-serialised identical payload
        is recognised as the same event rather than as an amendment."""
        return hashlib.sha256(
            json.dumps(payload or {}, sort_keys=True,
                       separators=(',', ':')).encode()).hexdigest()

    @api.model
    def dms_record_external_order(self, channel_account_id, external_order_id,
                                  payload, identity_id=None):
        """Step 3 of the webhook contract: dedup by account plus checksum.

        Returns the existing record unchanged when the same payload arrives
        twice. A redelivered webhook is the normal case, not the exception --
        every channel retries when it does not get a fast enough answer.
        """
        account = self.env['dms.channel.account'].browse(
            int(channel_account_id)).exists()
        if not account:
            raise UserError(self.env._("Unknown channel account."))
        if not account.can_receive_orders:
            raise UserError(
                self.env._("%s is not configured to receive orders.", account.name))
        checksum = self._dms_checksum(payload)
        existing = self.search([
            ('channel_account_id', '=', account.id),
            ('external_order_id', '=', external_order_id),
        ], limit=1)
        if existing:
            if existing.payload_checksum != checksum:
                # Not silently overwritten. An amendment that rewrites the
                # record in place destroys the evidence of what was ordered
                # first, which is the only thing reconciliation has.
                existing.message_post(body='Amended payload received.') \
                    if hasattr(existing, 'message_post') else None
            return existing
        identity = self.env['dms.channel.identity'].browse(
            int(identity_id)) if identity_id else None
        return self.create({
            'channel_account_id': account.id,
            'external_order_id': external_order_id,
            'payload_checksum': checksum,
            'identity_id': identity.id if identity else False,
            'partner_id': (identity.partner_id.id
                           if identity and identity.state == 'approved'
                           else False),
        })

    def dms_convert(self, lines, operation_uuid=None):
        """Convert through the DSR service, exactly like the portal does.

        Not `sale.order.create` here. Section 6 requires the server to map
        SKU, assortment, pricelist and credit, and `dms.order.api
        .dms_order_submit` is where all four live. `dms.eb2b.order` has its
        own route and therefore has neither the credit check nor the
        assortment check -- the debt sub-plan 08 recorded, and the one thing
        this model exists to avoid repeating.
        """
        self.ensure_one()
        if self.state == 'converted':
            return {'order_id': self.sale_order_id.id, 'replayed': True,
                    'errors': []}
        if not self.partner_id:
            raise UserError(
                self.env._("This external order has no approved outlet link yet. A matched phone number is not an approved link."))
        result = self.env['dms.order.api'].sudo().dms_order_submit(
            self.partner_id.id, lines, operation_uuid=operation_uuid)
        if result.get('order_id'):
            self.write({'state': 'converted',
                        'sale_order_id': result['order_id']})
        else:
            self.write({
                'state': 'exception',
                'exception_detail': str(result.get('errors')),
            })
        return result
