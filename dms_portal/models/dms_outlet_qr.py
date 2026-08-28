import secrets

from odoo import api, fields, models
from odoo.exceptions import UserError


class DmsOutletQr(models.Model):
    """A code printed at the shop. It identifies an outlet and grants nothing.

    CR-21: a shop owner who runs out of a fast-moving SKU three days before
    the salesman is due has two options today -- phone the Distributor, which
    lands outside every record, or wait, which is a lost order. A printed code
    starts the self-service session.

    What the code shortens is the boring half of onboarding -- WHICH outlet.
    It does not shorten authentication: the identity and entitlement chain of
    master section 2.10 runs behind it unchanged. That distinction is the
    whole design, because a printed code is visible to anyone standing in the
    shop, photographable from the street, and permanent once printed.
    """
    _name = 'dms.outlet.qr'
    _description = 'DMS Outlet QR Code'
    _order = 'create_date desc'

    _unique_qr_code = models.Constraint(
        'UNIQUE(code)', 'This QR code already exists.')

    outlet_id = fields.Many2one(
        'res.partner', string='Outlet', required=True, index=True,
        ondelete='cascade')
    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company)
    code = fields.Char(required=True, index=True, readonly=True, copy=False)
    state = fields.Selection([
        ('active', 'Active'),
        ('revoked', 'Revoked'),
    ], required=True, default='active', index=True)
    issued_by_id = fields.Many2one(
        'res.users', readonly=True, default=lambda self: self.env.user)
    revoked_by_id = fields.Many2one('res.users', readonly=True)
    revoke_date = fields.Datetime(readonly=True)
    revoke_reason = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Server-minted, always. A code the caller chooses is a code
            # somebody can guess, and guessing it is standing in a shop you
            # were never in.
            vals['code'] = secrets.token_urlsafe(16)
        return super().create(vals_list)

    def action_revoke(self, reason=None):
        """Revocable and reissuable per outlet, with an audit trail (CR-21).

        A printed sign cannot be un-printed, so revoking the code is the only
        way to retire one that has been photographed.
        """
        reason = (reason or '').strip()
        if not reason:
            raise UserError('A revocation needs a reason.')
        for rec in self:
            if rec.state == 'revoked':
                raise UserError('Already revoked.')
            rec.write({'state': 'revoked', 'revoked_by_id': self.env.uid,
                       'revoke_date': fields.Datetime.now(),
                       'revoke_reason': reason})
        return True

    @api.model
    def dms_start_session(self, code):
        """POST /web/dataset/call_kw/dms.outlet.qr/dms_start_session
           POST /json/2/dms.outlet.qr/dms_start_session

        Returns WHICH outlet, and whether the caller may already act on it.
        It never grants: CR-21's exit criterion is that scanning with an
        unlinked identity opens a link request and cannot place an order.
        """
        record = self.sudo().search(
            [('code', '=', code), ('state', '=', 'active')], limit=1)
        if not record:
            raise UserError('Unknown or revoked code.')
        entitled = record.outlet_id.id in \
            self.env.user.dms_allowed_partner_ids()
        return {
            'outlet_id': record.outlet_id.id,
            'outlet_name': record.outlet_id.display_name,
            'entitled': entitled,
            # Said explicitly so a client cannot read "we got an outlet back"
            # as "we may order".
            'can_order': entitled,
        }
