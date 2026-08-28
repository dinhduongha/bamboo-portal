from odoo import api, models


class DmsPortalScoped(models.AbstractModel):
    """The portal visibility domain, defined once.

    Every portal-facing read in 16B, 16C and 16D goes through this. The
    alternative -- writing the same domain into each model -- is three
    opportunities for one of them to drift, and drift here means a partner
    reading another partner's orders.
    """
    _name = 'dms.portal.scoped'
    _description = 'DMS Portal Scoping Mixin'

    #: Models mixing this in override it when their link to the Outlet is not
    #: called `partner_id` (`dms.eb2b.order` uses `res_partner_id`).
    _dms_portal_partner_field = 'partner_id'

    @api.model
    def dms_portal_domain(self, partner_field=None):
        """Domain restricting a portal user to their approved partners.

        Returns `[]` for an internal user: they are already scoped by the
        record rules of `dms` (section 7 -- internal users belong in the
        back office, not in a second copy of it), and narrowing them here
        would hide their own region from them.

        Returns `[('id', '=', False)]` -- never `[]` -- for a portal user
        with no approved entitlement. An empty domain reads as "no filter",
        which is the opposite of what an unentitled user should get.
        """
        user = self.env.user
        if not user.has_group('base.group_portal'):
            return []
        allowed = user.dms_allowed_partner_ids()
        if not allowed:
            return [('id', '=', False)]
        field = partner_field or self._dms_portal_partner_field
        return [(field, 'in', allowed)]
