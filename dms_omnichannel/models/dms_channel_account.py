import hashlib
import hmac
import time

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class DmsChannelAccount(models.Model):
    """One external account on one channel, for one company.

    Plan 18 section 4 makes this plan the owner of the channel account and of
    the identity and order mappings. Plan 16 section 5.1 says the portal
    plan REUSES them rather than defining a second staging model -- two
    staging tables for the same external order is two answers about whether
    it has been converted.

    Section 8: the record stores a secret REFERENCE. The value lives in
    `ir.config_parameter`, which is also what `dms.messaging.channel.config`
    already does and for the reason CLAUDE.md section 5.5 records:
    `password=True` is not a recognised field parameter in Odoo 19 and never
    restricted `read()`, RPC or export -- it only masked a widget.
    """
    _name = 'dms.channel.account'
    _description = 'DMS Channel Account'
    _check_company_auto = True
    _order = 'channel, name'

    _unique_channel_external_account = models.Constraint(
        'UNIQUE(channel, external_account_id, company_id)',
        'This external account is already registered for this channel and '
        'company.',
    )

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company)
    channel = fields.Selection([
        ('zalo', 'Zalo OA / Mini App'),
        ('tiktok', 'TikTok Shop'),
        ('facebook', 'Facebook Page / Messenger'),
    ], required=True, index=True)
    external_account_id = fields.Char(required=True, index=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('suspended', 'Suspended'),
    ], required=True, default='draft', index=True)

    #: What this account is allowed to do. A channel that can receive orders
    #: is a different risk from one that can only send notifications, and the
    #: difference has to be a field somebody set rather than a property of
    #: whichever adapter happens to call.
    can_receive_orders = fields.Boolean(default=False)
    can_send_messages = fields.Boolean(default=False)

    secret_ref = fields.Char(
        string='Secret Reference', required=True,
        groups='dms.group_dms_sale_manager',
        help='Key in ir.config_parameter holding the webhook signing secret. '
             'The secret itself is never stored on this record.')
    secret_rotated_at = fields.Datetime(readonly=True)
    #: Seconds a signed timestamp stays acceptable. Not unlimited: a captured
    #: request that is valid forever is a replay waiting for an outage.
    replay_window_seconds = fields.Integer(default=300, required=True)

    @api.constrains('replay_window_seconds')
    def _check_replay_window(self):
        for rec in self:
            if rec.replay_window_seconds <= 0:
                raise ValidationError(
                    'The replay window must be positive. Zero or less accepts '
                    'nothing; there is no value that means "no limit" here on '
                    'purpose.')

    def _dms_secret(self):
        """Resolve the signing secret at the point of use, never on the record."""
        self.ensure_one()
        secret = self.env['ir.config_parameter'].sudo().get_param(
            self.sudo().secret_ref)
        if not secret:
            raise UserError(
                f'No secret stored under {self.sudo().secret_ref!r}. A channel '
                f'account with no secret cannot verify anything, and treating '
                f'that as "signature matched" is how an unsigned request gets '
                f'accepted.')
        return secret

    def dms_verify_webhook(self, body, signature, timestamp):
        """Step 1 of the webhook contract (section 5).

        Verifies the signature, and refuses a timestamp outside the replay
        window. Returns True or raises -- never returns False, because a
        caller that forgets to check a boolean has written an open webhook
        and nothing complains.
        """
        self.ensure_one()
        if self.state != 'active':
            raise UserError(f'Channel account {self.name} is {self.state}.')
        try:
            sent_at = int(timestamp)
        except (TypeError, ValueError):
            raise UserError('Missing or malformed timestamp.')
        drift = abs(int(time.time()) - sent_at)
        if drift > self.replay_window_seconds:
            raise UserError(
                f'Timestamp is {drift}s off; the replay window is '
                f'{self.replay_window_seconds}s.')
        expected = self._dms_sign(body, sent_at)
        # `compare_digest`, not `==`: a plain comparison returns early on the
        # first differing byte, and the timing of that leaks the signature one
        # byte at a time.
        if not hmac.compare_digest(expected, signature or ''):
            raise UserError('Signature does not match.')
        return True

    def _dms_sign(self, body, timestamp):
        self.ensure_one()
        payload = f'{timestamp}.'.encode() + (
            body if isinstance(body, bytes) else (body or '').encode())
        return hmac.new(self._dms_secret().encode(), payload,
                        hashlib.sha256).hexdigest()

    def action_activate(self):
        for rec in self:
            if rec.state == 'active':
                raise UserError('Already active.')
            # Reading the secret is the check: an account activated without
            # one verifies nothing, and the failure would first appear as an
            # accepted forged webhook.
            rec._dms_secret()
            rec.state = 'active'
        return True

    def action_suspend(self):
        self.write({'state': 'suspended'})
        return True
