"""Plan 16A Task 2 — entitlement is a RECORD, not an inference.

Plan 16 section 4: "Khong suy quyen chi tu commercial partner neu mot
partner co nhieu Outlet/child." A chain of ten shops sits under one
`commercial_partner_id`; inferring from it hands the owner of one shop the
receivables of the other nine.

Section 5.2 says the same thing again for the Zalo channel: a matching phone
number "khong tu sinh quyen -- chi tao yeu cau lien ket". One invariant,
stated twice, so it lives in one model.
"""
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


class EntitlementCase(TransactionCase):

    def setUp(self):
        super().setUp()
        self.org = self.env['res.organization'].create({
            'code': 'ORGP', 'name': 'Portal Region'})
        self.outlet_a = self.env['res.partner'].create({
            'name': 'Outlet A', 'customer_rank': 1})
        self.outlet_b = self.env['res.partner'].create({
            'name': 'Outlet B', 'customer_rank': 1})
        self.buyer = self.env['res.users'].create({
            'name': 'Portal Buyer', 'login': 'buyer-16a@dms.test',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self.staff = self.env['res.users'].create({
            'name': 'Sales Admin', 'login': 'admin-16a@dms.test',
            'organization_id': self.org.id,
            'group_ids': [(4, self.env.ref('dms.group_dms_sale_admin').id)],
        })
        self.approver = self.env['res.users'].create({
            'name': 'Second Pair of Eyes', 'login': 'approver-16a@dms.test',
            'organization_id': self.org.id,
            'group_ids': [(4, self.env.ref('dms.group_dms_sale_admin').id)],
        })

    def _entitlement(self, partner=None, user=None, **vals):
        return self.env['dms.portal.entitlement'].with_user(
            user or self.staff).create(dict({
                'user_id': self.buyer.id,
                'partner_id': (partner or self.outlet_a).id,
                'scope': 'outlet',
            }, **vals))


@tagged('post_install', '-at_install')
class TestEntitlementGrants(EntitlementCase):

    def test_a_requested_entitlement_grants_nothing(self):
        ent = self._entitlement()
        self.assertEqual(ent.state, 'requested')
        self.assertFalse(
            self.buyer.dms_allowed_partner_ids(),
            'a link REQUEST is not a grant; section 5.2 is explicit that a '
            'match creates a request and nothing more')

    def test_only_approved_entitlements_grant(self):
        ent = self._entitlement()
        ent.with_user(self.approver).action_approve()
        self.assertEqual(ent.state, 'approved')
        self.assertEqual(
            self.buyer.dms_allowed_partner_ids(), [self.outlet_a.id])

    def test_revoke_removes_the_partner_immediately(self):
        ent = self._entitlement()
        ent.with_user(self.approver).action_approve()
        ent.with_user(self.approver).action_revoke(reason='chain sold')
        self.assertEqual(ent.state, 'revoked')
        self.assertFalse(
            self.buyer.dms_allowed_partner_ids(),
            'section 4: "revoke assignment chan ngay"; nothing here waits for '
            'a re-login')

    def test_an_approved_entitlement_for_b_does_not_grant_a(self):
        ent = self._entitlement(partner=self.outlet_b)
        ent.with_user(self.approver).action_approve()
        self.assertEqual(
            self.buyer.dms_allowed_partner_ids(), [self.outlet_b.id])


@tagged('post_install', '-at_install')
class TestEntitlementFourEyes(EntitlementCase):

    def test_requester_cannot_approve_their_own_entitlement(self):
        """Same policy as D-10 on `dms.company.role.assignment`, and for the
        same reason: requester != approver, not merely holder != approver."""
        ent = self._entitlement()
        with self.assertRaises(UserError):
            ent.with_user(self.staff).action_approve()

    def test_the_holder_cannot_approve_their_own_entitlement(self):
        ent = self._entitlement()
        with self.assertRaises(UserError):
            ent.with_user(self.buyer).action_approve()

    def test_revoke_without_a_reason_is_refused(self):
        ent = self._entitlement()
        ent.with_user(self.approver).action_approve()
        with self.assertRaises(UserError):
            ent.with_user(self.approver).action_revoke(reason='')

    def test_approving_twice_is_refused(self):
        ent = self._entitlement()
        ent.with_user(self.approver).action_approve()
        with self.assertRaises(UserError):
            ent.with_user(self.approver).action_approve()


@tagged('post_install', '-at_install')
class TestEntitlementConstraint(EntitlementCase):

    def test_unique_entitlement_per_user_and_partner_exists_in_postgres(self):
        """Asserted against `pg_constraint`, not against the source.

        Odoo 19 ignores `_sql_constraints` written as a list ENTIRELY -- the
        constraint is never created and nothing warns. Reading the model file
        proves nothing; the catalog does. (CLAUDE.md section 5.2.)
        """
        self.env.cr.execute("""
            SELECT conname FROM pg_constraint
             WHERE conrelid = 'dms_portal_entitlement'::regclass
               AND contype = 'u'
        """)
        self.assertTrue(
            self.env.cr.fetchall(),
            'no UNIQUE constraint on dms_portal_entitlement in PostgreSQL')

    def test_a_second_entitlement_for_the_same_pair_is_refused(self):
        self._entitlement()
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self._entitlement()

    def test_scope_must_match_what_the_partner_is(self):
        distributor_partner = self.env['res.partner'].create({
            'name': 'Not an outlet', 'customer_rank': 0})
        with self.assertRaises(ValidationError):
            self._entitlement(partner=distributor_partner, scope='outlet')
