from odoo import api, fields, models
from odoo.exceptions import UserError


class DmsChannelOrderStatus(models.Model):
    """Fulfillment and reverse status, in both directions, without a loop.

    Section 6: "Odoo source of fulfillment/stock/invoice; channel source of
    external order lifecycle" and "Status sync loop protection using
    version/source marker."

    The loop is the interesting failure. Odoo pushes "shipped" to the channel;
    the channel echoes "shipped" back on its next poll; the adapter writes it
    again and pushes again. Nothing is wrong with any single step and the two
    systems talk forever. The marker below is what stops it: an inbound status
    that we ourselves last wrote is dropped rather than re-applied.
    """
    _inherit = 'dms.channel.order'

    fulfillment_state = fields.Selection([
        ('pending', 'Pending'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
        ('returned', 'Returned'),
    ], default='pending', required=True, index=True)
    #: Which side wrote the current value, and the monotonic version it came
    #: with. Both are needed: the source alone cannot order two updates, and
    #: the version alone cannot tell an echo from a genuine change.
    status_source = fields.Selection([
        ('odoo', 'Odoo'),
        ('channel', 'Channel'),
    ], default='odoo', required=True)
    status_version = fields.Integer(default=0, required=True)

    def dms_apply_channel_status(self, state, version):
        """Inbound status from the channel.

        Returns True when applied, False when ignored -- and ignoring is the
        normal case, not an error: every channel redelivers, and out-of-order
        delivery is routine.
        """
        self.ensure_one()
        version = int(version)
        if version <= self.status_version:
            # Out of order or redelivered. Applying it would move the record
            # backwards, which is how a delivered order becomes pending again
            # an hour after the customer signed for it.
            return False
        if self.status_source == 'odoo' and state == self.fulfillment_state:
            # Our own value coming back. Writing it would bump the version and
            # trigger another outbound push, and the two systems would then
            # talk to each other forever.
            self.status_version = version
            return False
        self.write({'fulfillment_state': state, 'status_source': 'channel',
                    'status_version': version})
        return True

    def dms_push_status(self, state):
        """Outbound status from Odoo. Odoo owns fulfillment, so this is the
        authoritative direction for these values."""
        self.ensure_one()
        if state not in dict(self._fields['fulfillment_state'].selection):
            raise UserError(self.env._("Unknown fulfillment state %r.", state))
        self.write({'fulfillment_state': state, 'status_source': 'odoo',
                    'status_version': self.status_version + 1})
        # The actual send is an integration operation, so it inherits the
        # retry, backoff and dead-letter that plan 14 already built. A second
        # queue here would be a second thing to monitor and a second place to
        # lose a message.
        return self.env['dms.integration.operation'].sudo()
