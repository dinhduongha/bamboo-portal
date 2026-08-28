from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class DmsPortalEntitlement(models.Model):
    """What a portal identity is allowed to see, as an approved record.

    Plan 16 section 4 forbids deriving this from `commercial_partner_id`, and
    section 5.2 forbids deriving it from a phone number. Both refusals mean
    the same thing: the grant has to be a row somebody approved.
    """
    _name = 'dms.portal.entitlement'
    _description = 'DMS Portal Entitlement'
    _check_company_auto = True
    _order = 'user_id, partner_id'

    # Odoo 19 ignores `_sql_constraints` written as a list -- the constraint
    # is never created in PostgreSQL and nothing warns (CLAUDE.md section 5.2).
    _unique_user_partner = models.Constraint(
        'UNIQUE(user_id, partner_id)',
        'This portal user already has an entitlement for this partner.',
    )

    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company)
    user_id = fields.Many2one(
        'res.users', string='Portal User', required=True, index=True,
        ondelete='cascade')
    partner_id = fields.Many2one(
        'res.partner', string='Outlet / Distributor', required=True,
        index=True, ondelete='cascade')
    scope = fields.Selection([
        ('outlet', 'Outlet'),
        ('distributor', 'Distributor'),
    ], required=True, default='outlet')
    state = fields.Selection([
        ('requested', 'Requested'),
        ('approved', 'Approved'),
        ('revoked', 'Revoked'),
    ], required=True, default='requested', index=True)
    source = fields.Selection([
        ('portal', 'Portal sign-up'),
        ('zalo', 'Zalo Mini App'),
        ('manual', 'Created by staff'),
    ], required=True, default='manual')

    requested_by_id = fields.Many2one(
        'res.users', readonly=True, default=lambda self: self.env.user)
    approved_by_id = fields.Many2one('res.users', readonly=True)
    approval_date = fields.Datetime(readonly=True)
    revoked_by_id = fields.Many2one('res.users', readonly=True)
    revoke_date = fields.Datetime(readonly=True)
    revoke_reason = fields.Text()

    @api.constrains('scope', 'partner_id')
    def _check_scope_matches_the_partner(self):
        """An `outlet` entitlement on a partner that is not an Outlet is a
        grant nobody can reason about -- `customer_rank > 0` is what makes a
        `res.partner` an Outlet in this system (CLAUDE.md section 2)."""
        for rec in self:
            if rec.scope == 'outlet' and rec.partner_id.customer_rank <= 0:
                raise ValidationError(
                    f'{rec.partner_id.display_name} is not an Outlet '
                    f'(customer_rank = 0); an outlet-scoped entitlement on it '
                    f'grants access to something that has no orders.')

    def action_approve(self):
        """Four eyes, and the stricter reading of it.

        D-10 settled this for `dms.company.role.assignment`: refuse when the
        REQUESTER is the approver as well as when the holder is. A staffer who
        can create and approve their own row has no second pair of eyes, and
        the fact that the row names somebody else does not change that.
        """
        for rec in self:
            if rec.state != 'requested':
                raise UserError(
                    f'Only a requested entitlement can be approved; this one '
                    f'is {rec.state}.')
            if self.env.user in (rec.requested_by_id, rec.user_id):
                raise UserError(
                    'The requester and the holder cannot approve an '
                    'entitlement. Ask a second person.')
            rec.write({
                'state': 'approved',
                'approved_by_id': self.env.uid,
                'approval_date': fields.Datetime.now(),
            })
            # Granting invalidates too. A session opened before the grant
            # carries a token computed from the old version; leaving it valid
            # would mean the grant needs a re-login to take effect -- the same
            # staleness bug, pointing the pleasant way.
            rec._dms_kill_sessions()
        return True

    def action_revoke(self, reason=None):
        """Section 4: "revoke assignment chan ngay va invalidate session"."""
        reason = (reason or '').strip()
        if not reason:
            raise UserError(
                'A revocation needs a reason. Without one nobody reading this '
                'row later can tell a mistake from a decision.')
        for rec in self:
            if rec.state == 'revoked':
                raise UserError('This entitlement is already revoked.')
            rec.write({
                'state': 'revoked',
                'revoked_by_id': self.env.uid,
                'revoke_date': fields.Datetime.now(),
                'revoke_reason': reason,
            })
            rec._dms_kill_sessions()
        return True

    def _dms_kill_sessions(self):
        """Make every open session of the holder invalid, at once.

        Odoo's session token is an HMAC over `_get_session_token_fields()`,
        and `http.py` recomputes it on every request. Bumping a field inside
        that set is how core invalidates sessions for passkeys, so this
        borrows the mechanism rather than inventing a second one.

        The ormcache on `_compute_session_token` is keyed by `sid`, so it has
        to be cleared as well -- otherwise the old token keeps being handed
        back from memory and the revocation takes effect only after a
        restart.
        """
        users = self.env['res.users']
        for rec in self:
            user = rec.user_id.sudo()
            user.dms_portal_entitlement_version += 1
            users |= user
        # `_session_token_get_values` reads the row with RAW SQL. An ORM write
        # that has not been flushed is invisible to it, so the token comes back
        # unchanged and the revocation quietly does nothing.
        users.flush_recordset(['dms_portal_entitlement_version'])
        self.env.registry.clear_cache()
        return True


class ResUsersPortalEntitlement(models.Model):
    _inherit = 'res.users'

    #: Bumped whenever an entitlement of this user is approved or revoked.
    #: Its only job is to be part of the session token, below.
    dms_portal_entitlement_version = fields.Integer(
        default=0, copy=False, readonly=True,
        help='Bumped on every entitlement change so open sessions stop '
             'validating. Not a business number.')

    def _get_session_token_fields(self):
        """A field outside this set cannot invalidate a session, however
        diligently it is bumped."""
        return super()._get_session_token_fields() | {
            'dms_portal_entitlement_version'}

    def dms_allowed_partner_ids(self):
        """Ids this user may see, from APPROVED entitlements only.

        Public on purpose: 16B/16C/16D and the client both need it, and
        CLAUDE.md section 6 says a public model method serves both
        `call_kw` and `/json/2` without a controller. It takes no argument --
        everything is derived from the authenticated user, so a client cannot
        ask for a partner it has no row for.
        """
        self.ensure_one()
        return self.env['dms.portal.entitlement'].sudo().search([
            ('user_id', '=', self.id),
            ('state', '=', 'approved'),
        ]).partner_id.ids

    @api.model
    def dms_portal_context(self):
        """POST /web/dataset/call_kw/res.users/dms_portal_context
           POST /json/2/res.users/dms_portal_context

        Takes no argument, deliberately. Everything is derived from the
        authenticated user, so a client cannot ask for a partner or a company
        it has no approved entitlement for -- and a parameter added here
        later would have to be added on purpose rather than slipping in
        (CLAUDE.md section 6).
        """
        return self.env.user._dms_portal_build_context()

    def _dms_portal_build_context(self):
        """Private: not reachable over RPC."""
        self.ensure_one()
        entitlements = self.env['dms.portal.entitlement'].sudo().search([
            ('user_id', '=', self.id),
            ('state', '=', 'approved'),
        ])
        return {
            'partners': [{
                'id': ent.partner_id.id,
                'name': ent.partner_id.display_name,
                'scope': ent.scope,
            } for ent in entitlements],
            'company_ids': entitlements.company_id.ids,
        }
