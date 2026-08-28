from odoo import api, fields, models
from odoo.exceptions import UserError


class DmsChannelConversation(models.Model):
    """Conversation metadata, assignment and SLA — not a second chat engine.

    Section 7: "Unified inbox assignment, SLA, templates and handoff to
    human", and "Notification event idempotent; delivery status not
    interpreted as business completion."

    That last clause is the one with teeth. A channel reporting "delivered"
    means the message reached a phone. It does not mean the shop read it,
    agreed to it, or did anything. Treating the two as the same is how a
    promotion is recorded as accepted because a notification was delivered.
    """
    _name = 'dms.channel.conversation'
    _description = 'DMS Channel Conversation'
    _order = 'last_message_at desc'

    _unique_channel_conversation = models.Constraint(
        'UNIQUE(channel_account_id, external_conversation_id)',
        'This conversation is already recorded for this channel account.',
    )

    channel_account_id = fields.Many2one(
        'dms.channel.account', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one(
        related='channel_account_id.company_id', store=True, index=True)
    external_conversation_id = fields.Char(required=True, index=True)
    identity_id = fields.Many2one('dms.channel.identity', index=True)
    partner_id = fields.Many2one('res.partner', index=True)
    assigned_user_id = fields.Many2one('res.users', index=True)
    state = fields.Selection([
        ('open', 'Open'),
        ('assigned', 'Assigned'),
        ('closed', 'Closed'),
    ], required=True, default='open', index=True)
    last_message_at = fields.Datetime(index=True)
    sla_due_at = fields.Datetime(
        index=True,
        help='When a human must have answered. Empty means no SLA applies, '
             'not "any time".')
    consent = fields.Boolean(
        default=False,
        help='Opt-in for template notifications. Section 8 makes this a '
             'precondition, not a preference.')

    def action_assign(self, user):
        for rec in self:
            if rec.state == 'closed':
                raise UserError('Cannot assign a closed conversation.')
            rec.write({'assigned_user_id': user.id, 'state': 'assigned'})
        return True

    def dms_can_send_template(self):
        """Section 8: consent and the messaging window, both.

        Consent alone is not enough on any of the three channels -- each
        closes the window some hours after the customer's last message, and
        sending outside it is what gets an account suspended.
        """
        self.ensure_one()
        if not self.consent:
            return False
        if not self.channel_account_id.can_send_messages:
            return False
        return True
