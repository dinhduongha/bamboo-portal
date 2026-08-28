"""Plan 16A Task 6 — the portal side of the ACL.

A portal user must be able to see their own entitlement (so the UI can say
"pending approval") and nothing else about anybody else's.
"""
from odoo.exceptions import AccessError
from odoo.tests.common import tagged

from .test_entitlement import EntitlementCase


@tagged('post_install', '-at_install')
class TestPortalEntitlementSecurity(EntitlementCase):

    def setUp(self):
        super().setUp()
        self.other_buyer = self.env['res.users'].create({
            'name': 'Rival Buyer', 'login': 'rival-16a@dms.test',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })

    def test_portal_user_can_read_their_own_entitlement(self):
        ent = self._entitlement()
        self.assertEqual(
            ent.with_user(self.buyer).state, 'requested',
            'the portal has to be able to say "pending approval"')

    def test_portal_user_cannot_read_another_users_entitlement(self):
        ent = self._entitlement()
        found = self.env['dms.portal.entitlement'].with_user(
            self.other_buyer).search([('id', '=', ent.id)])
        self.assertFalse(found)

    def test_portal_user_cannot_write_their_own_entitlement(self):
        ent = self._entitlement()
        with self.assertRaises(AccessError):
            ent.with_user(self.buyer).write({'state': 'approved'})

    def test_portal_user_cannot_create_an_entitlement(self):
        with self.assertRaises(AccessError):
            self.env['dms.portal.entitlement'].with_user(self.buyer).create({
                'user_id': self.buyer.id,
                'partner_id': self.outlet_b.id,
                'scope': 'outlet',
            })

    def test_no_deny_all_rule_on_this_model(self):
        """`[('id','=',False)] ` is never a scoping rule -- it denies the
        model outright and breaks every related-field read that touches it.
        Same invariant as `dms`'s `test_no_deny_all_rules_remain`."""
        rules = self.env['ir.rule'].search([
            ('model_id.model', '=', 'dms.portal.entitlement')])
        deny = rules.filtered(
            lambda r: (r.domain_force or '').replace(' ', '')
            == "[('id','=',False)]")
        self.assertFalse(deny, f'deny-all rule: {deny.mapped("name")}')

    def test_a_rule_actually_exists_for_portal_users(self):
        rules = self.env['ir.rule'].search([
            ('model_id.model', '=', 'dms.portal.entitlement')])
        self.assertTrue(
            rules, 'ACL alone gives every portal user every row; the row '
                   'filter is a record rule, and there is none')
