from odoo import api, fields, models
from odoo.exceptions import UserError


class DmsChannelIdentity(models.Model):
    """An external user id, and what it is allowed to be.

    Plan 18 section 7: "Identity matching never solely on PSID/open ID;
    verified mapping and merge audit." Plan 18 section 7 again, for Zalo:
    the Mini App shares the identity constraints of master section 2.10 --
    token exchanged server-side, a phone number grants nothing by itself, an
    ambiguous match goes to an exception.

    A phone number is semi-public information. It is evidence that somebody
    knows the shop's number, not that they own the shop.
    """
    _name = 'dms.channel.identity'
    _inherit = ['dms.display.name.mixin']
    _dms_display_fields = ('external_user_id', 'channel_account_id')
    _description = 'DMS Channel External Identity'
    _order = 'create_date desc'

    _unique_channel_external_user = models.Constraint(
        'UNIQUE(channel_account_id, external_user_id)',
        'This external user is already mapped for this channel account.',
    )

    channel_account_id = fields.Many2one(
        'dms.channel.account', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one(
        related='channel_account_id.company_id', store=True, index=True)
    external_user_id = fields.Char(
        required=True, index=True,
        help='The id the channel issued. Never a phone number the client '
             'typed: section 5.2 requires the token be exchanged server-side '
             'and the number read from the channel, not from the caller.')
    phone_from_channel = fields.Char(
        help='Resolved by exchanging the token with the channel API. A '
             'client-declared number is never written here.')
    partner_id = fields.Many2one(
        'res.partner', string='Outlet', index=True,
        help='Set only once the link has been approved.')
    state = fields.Selection([
        ('requested', 'Link requested'),
        ('ambiguous', 'Ambiguous — needs a human'),
        ('unmatched', 'No outlet matched'),
        ('approved', 'Approved'),
        ('revoked', 'Revoked'),
    ], required=True, default='requested', index=True)
    consent = fields.Boolean(default=False)
    resolution_note = fields.Text()

    @api.model
    def dms_resolve_from_token(self, channel_account_id, external_user_id,
                              phone_from_channel=None):
        """Create or find the link request for one external identity.

        Deliberately NOT `dms_resolve_from_phone`: section 5.2 constraint 1
        says the client sends the token the channel issued and the server
        exchanges it. This method's caller is the adapter that has already
        done that exchange, which is why `phone_from_channel` is named for
        where it came from -- a parameter called `phone` invites somebody to
        pass the one the client typed.

        A match NEVER grants. Section 5.2 constraint 2: matching an Outlet
        creates a link request; read access to orders and debt opens only
        after entitlement approval.
        """
        account = self.env['dms.channel.account'].browse(
            int(channel_account_id)).exists()
        if not account:
            raise UserError('Unknown channel account.')
        existing = self.search([
            ('channel_account_id', '=', account.id),
            ('external_user_id', '=', external_user_id),
        ], limit=1)
        if existing:
            return existing

        candidates = self.env['res.partner'].sudo().search([
            ('phone', '=', phone_from_channel),
            ('customer_rank', '>', 0),
        ]) if phone_from_channel else self.env['res.partner'].browse()

        if len(candidates) == 1:
            state, partner, note = 'requested', candidates, ''
        elif len(candidates) > 1:
            # Section 5.2 constraint 3. Picking one is a coin toss whose loser
            # is a shop owner reading somebody else's receivables.
            state, partner, note = 'ambiguous', candidates.browse(), (
                'Phone matches %s outlets: %s'
                % (len(candidates), ', '.join(candidates.mapped('display_name'))))
        else:
            state, partner, note = 'unmatched', candidates.browse(), (
                'No outlet carries this number. Creating one here would let '
                'anybody with a phone add a shop to the master data.')

        return self.create({
            'channel_account_id': account.id,
            'external_user_id': external_user_id,
            'phone_from_channel': phone_from_channel or False,
            'partner_id': partner.id if partner else False,
            'state': state,
            'resolution_note': note,
        })

    def action_approve(self, partner=None):
        """Approving the LINK. It still grants nothing on its own.

        The read permission is `dms.portal.entitlement` in `dms_portal`, and
        keeping them separate is the point: this says "this Zalo user is that
        shop", and that says "and may therefore read these documents".
        """
        for rec in self:
            if rec.state not in ('requested', 'ambiguous', 'unmatched'):
                raise UserError(f'Cannot approve a link that is {rec.state}.')
            target = partner or rec.partner_id
            if not target:
                raise UserError(
                    'Name the outlet: an approval with no outlet is a link to '
                    'nothing.')
            rec.write({'state': 'approved', 'partner_id': target.id})
        return True

    def action_revoke(self, reason=None):
        reason = (reason or '').strip()
        if not reason:
            raise UserError('A revocation needs a reason.')
        self.write({'state': 'revoked', 'resolution_note': reason})
        return True

    def dms_erase_pii(self, reason=None):
        """Honour a deletion request without destroying the audit trail.

        Section 8 requires deletion and export requests to be answerable. It
        also requires an audit. Those pull opposite ways, and deleting the row
        outright resolves the tension in the wrong direction: the link record
        is the evidence of who could see what, and an incident asks exactly
        that question.

        So the PERSONAL data goes -- the phone number the channel returned --
        and the row stays, revoked and annotated. What remains is an opaque
        external id and a state, which identifies nobody on its own.
        """
        reason = (reason or '').strip()
        if not reason:
            raise UserError('A deletion request needs a reason recorded.')
        for rec in self:
            rec.write({
                'phone_from_channel': False,
                'state': 'revoked',
                'consent': False,
                'resolution_note': f'PII erased on request: {reason}',
            })
        return True
