"""Plan 16A Task 3 — one domain, in one place.

16B reads `sale.order`, 16C reads `account.move` and `stock.picking`, 16D
reads plan 18's channel mapping. Four copies of the same domain is three
copies that will drift, and the one that drifts is a partner reading another
partner's money.
"""
from odoo.tests.common import TransactionCase, tagged

from .test_entitlement import EntitlementCase


@tagged('post_install', '-at_install')
class TestPortalScope(EntitlementCase):

    def test_scope_returns_a_false_domain_when_there_is_no_entitlement(self):
        """An EMPTY domain here is not "nothing to filter" -- it is "read
        everything". The failure mode of getting this wrong is silent and
        total, so it gets its own test."""
        domain = self.env['dms.portal.scoped'].with_user(
            self.buyer).dms_portal_domain()
        self.assertEqual(domain, [('id', '=', False)])

    def test_scope_lists_only_approved_partners(self):
        ent = self._entitlement()
        ent.with_user(self.approver).action_approve()
        self._entitlement(partner=self.outlet_b)   # left at `requested`
        domain = self.env['dms.portal.scoped'].with_user(
            self.buyer).dms_portal_domain()
        self.assertEqual(domain, [('partner_id', 'in', [self.outlet_a.id])])

    def test_scope_honours_the_partner_field_a_model_declares(self):
        domain = self.env['dms.portal.scoped'].with_user(
            self.buyer).dms_portal_domain(partner_field='res_partner_id')
        self.assertEqual(domain, [('id', '=', False)])
        ent = self._entitlement()
        ent.with_user(self.approver).action_approve()
        domain = self.env['dms.portal.scoped'].with_user(
            self.buyer).dms_portal_domain(partner_field='res_partner_id')
        self.assertEqual(
            domain, [('res_partner_id', 'in', [self.outlet_a.id])])

    def test_internal_user_is_not_scoped_by_this_mixin(self):
        """Section 7: "Odoo internal users use back-office, not Portal
        duplication." An internal user is already filtered by the record
        rules of `dms`; narrowing them again here would hide their own
        region from them."""
        domain = self.env['dms.portal.scoped'].with_user(
            self.staff).dms_portal_domain()
        self.assertEqual(domain, [])

    def test_a_revoked_entitlement_drops_out_of_the_domain(self):
        ent = self._entitlement()
        ent.with_user(self.approver).action_approve()
        ent.with_user(self.approver).action_revoke(reason='contract ended')
        domain = self.env['dms.portal.scoped'].with_user(
            self.buyer).dms_portal_domain()
        self.assertEqual(domain, [('id', '=', False)])
