"""Plan 16D — B16-10 and CR-21.

CR-21's two exit criteria, verbatim:

  - "Quet ma boi identity chua lien ket mo link request, khong dat duoc don."
  - "Don ngoai chu ky khong tao visit; Coverage % khong doi vi no."

The second is the expensive one. Coverage is `actual_visits / planned_visits`
on `dms.route`. An out-of-cycle order that created a visit would raise it for
work nobody did, and would raise it FASTEST at exactly the outlets that need
a salesman least.
"""
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import tagged

from .test_portal_catalog import PortalCatalogCase


@tagged('post_install', '-at_install')
class TestOutletQr(PortalCatalogCase):

    def _qr(self, outlet=None):
        return self.env['dms.outlet.qr'].sudo().create({
            'outlet_id': (outlet or self.outlet_a).id,
            'company_id': self.parent.id})

    def test_the_code_is_minted_by_the_server(self):
        """A code the caller chooses is a code somebody can guess, and
        guessing it is standing in a shop you were never in."""
        qr = self.env['dms.outlet.qr'].sudo().create({
            'outlet_id': self.outlet_a.id, 'company_id': self.parent.id,
            'code': 'guessable'})
        self.assertNotEqual(qr.code, 'guessable')
        self.assertGreater(len(qr.code), 16)

    def test_scanning_with_an_unlinked_identity_grants_nothing(self):
        """CR-21 exit criterion one."""
        qr = self._qr()
        result = self.env['dms.outlet.qr'].with_user(
            self.buyer).dms_start_session(qr.code)
        self.assertEqual(result['outlet_id'], self.outlet_a.id)
        self.assertFalse(result['entitled'])
        self.assertFalse(result['can_order'])

    def test_scanning_does_not_let_an_unlinked_identity_order(self):
        qr = self._qr()
        self.env['dms.outlet.qr'].with_user(self.buyer).dms_start_session(
            qr.code)
        with self.assertRaises(AccessError):
            self.env['dms.portal.api'].with_user(self.buyer).dms_portal_submit(
                self.outlet_a.id,
                [{'product_id': self.product_a.id, 'quantity': 1}])

    def test_an_entitled_identity_may_order_after_scanning(self):
        self._entitle()
        qr = self._qr()
        result = self.env['dms.outlet.qr'].with_user(
            self.buyer).dms_start_session(qr.code)
        self.assertTrue(result['can_order'])

    def test_a_revoked_code_is_unknown(self):
        """A printed sign cannot be un-printed. Revoking the code is the only
        way to retire one that has been photographed."""
        qr = self._qr()
        qr.action_revoke(reason='photographed from the street')
        with self.assertRaises(UserError):
            self.env['dms.outlet.qr'].with_user(
                self.buyer).dms_start_session(qr.code)

    def test_revoking_without_a_reason_is_refused(self):
        qr = self._qr()
        with self.assertRaises(UserError):
            qr.action_revoke(reason='')

    def test_the_model_has_a_company_scoped_record_rule(self):
        """An ACL row with no record rule is unrestricted for that group. A
        portal user reading every QR row in the database can start a session
        at any shop in the country. `dms`'s TestRuleMatrixInvariants enforces
        this across the whole rule set; stated here so the reason travels
        with the file that caused it."""
        rules = self.env['ir.rule'].search([
            ('model_id.model', '=', 'dms.outlet.qr')])
        self.assertTrue(rules, 'no record rule on dms.outlet.qr')
        for rule in rules:
            self.assertIn('company_id', rule.domain_force or '')

    def test_a_portal_user_cannot_read_another_outlets_qr_row(self):
        self._entitle()
        stray = self.env['dms.outlet.qr'].sudo().create({
            'outlet_id': self.outlet_b.id, 'company_id': self.parent.id})
        found = self.env['dms.outlet.qr'].with_user(self.buyer).search([
            ('id', '=', stray.id)])
        self.assertFalse(found)

    def test_an_outlet_can_be_reissued_a_code(self):
        first = self._qr()
        first.action_revoke(reason='reprinting the sign')
        second = self._qr()
        self.assertNotEqual(first.code, second.code)
        self.assertEqual(second.state, 'active')


@tagged('post_install', '-at_install')
class TestZaloLink(PortalCatalogCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(
            'dms.zalo.test.secret', 'zalo-secret')
        self.channel = self.env['dms.channel.account'].sudo().create({
            'name': 'PT Zalo', 'channel': 'zalo',
            'external_account_id': 'oa-portal',
            'company_id': self.parent.id,
            'secret_ref': 'dms.zalo.test.secret'})
        self.channel.action_activate()
        self.outlet_a.write({'phone': '0911222333'})

    def test_a_matching_phone_creates_requests_and_grants_nothing(self):
        """Section 5.2 constraint 2. A phone number is semi-public: evidence
        somebody knows the shop's number, not that they own the shop."""
        result = self.env['dms.portal.api'].with_user(
            self.buyer).dms_portal_zalo_link(
                self.channel.id, 'zalo-open-id-1',
                phone_from_channel='0911222333')
        self.assertEqual(result['identity_state'], 'requested')
        self.assertEqual(result['entitlement_state'], 'requested')
        self.assertFalse(result['can_order'])
        self.assertFalse(self.buyer.dms_allowed_partner_ids())

    def test_an_ambiguous_phone_creates_no_entitlement_at_all(self):
        self.outlet_b.write({'phone': '0911222333', 'customer_rank': 1})
        result = self.env['dms.portal.api'].with_user(
            self.buyer).dms_portal_zalo_link(
                self.channel.id, 'zalo-open-id-2',
                phone_from_channel='0911222333')
        self.assertEqual(result['identity_state'], 'ambiguous')
        self.assertFalse(result['entitlement_id'])

    def test_the_signature_has_no_client_declared_phone(self):
        import inspect
        sig = inspect.signature(
            type(self.env['dms.portal.api']).dms_portal_zalo_link)
        self.assertIn('phone_from_channel', sig.parameters)
        self.assertNotIn('phone', sig.parameters)


@tagged('post_install', '-at_install')
class TestOutOfCycleOrder(PortalCatalogCase):

    def _api(self):
        return self.env['dms.portal.api'].with_user(self.buyer)

    def _route(self):
        template = self.env['dms.route.template'].sudo().create({
            'name': 'PT Route T', 'company_id': self.parent.id,
            'team_id': self.team.id})
        return self.env['dms.route'].sudo().create({
            'name': 'PT Route', 'company_id': self.parent.id,
            'team_id': self.team.id, 'route_template_id': template.id,
            'route_date': self.env['dms.route']._fields['route_date'].default(
                self.env['dms.route']) if 'route_date' in
            self.env['dms.route']._fields else False,
        })

    def test_an_out_of_cycle_order_creates_no_visit(self):
        """CR-21 exit criterion two, at its source. Coverage is
        actual_visits / planned_visits; no visit means no movement."""
        self._entitle()
        before = self.env['dms.outlet.visit'].sudo().search_count([])
        result = self._api().dms_portal_submit_out_of_cycle(
            self.outlet_a.id,
            [{'product_id': self.product_a.id, 'quantity': 1}])
        self.assertTrue(result['order_id'], result.get('errors'))
        self.assertEqual(
            self.env['dms.outlet.visit'].sudo().search_count([]), before,
            'an out-of-cycle order created a visit; Coverage % now counts '
            'work nobody did')

    def test_the_order_is_marked_so_reporting_can_separate_it(self):
        """"Volume still credited to the responsible salesman, reported
        separately." A channel that quietly takes the field team's numbers is
        a channel the field team will find a way to kill."""
        self._entitle()
        result = self._api().dms_portal_submit_out_of_cycle(
            self.outlet_a.id,
            [{'product_id': self.product_a.id, 'quantity': 1}])
        order = self.env['sale.order'].sudo().browse(result['order_id'])
        self.assertTrue(order.dms_out_of_cycle)
        self.assertEqual(order.dms_order_channel, 'zalo')
        self.assertFalse(order.dms_outlet_visit_id)

    def test_a_client_supplied_visit_is_stripped(self):
        """Leaving the field merely unset is not enough: a client that sends
        one puts the Coverage inflation back by hand."""
        self._entitle()
        visit = self.env['dms.outlet.visit'].sudo().search([], limit=1)
        result = self._api().dms_portal_submit_out_of_cycle(
            self.outlet_a.id,
            [{'product_id': self.product_a.id, 'quantity': 1}],
            vals={'dms_outlet_visit_id': visit.id if visit else 1})
        order = self.env['sale.order'].sudo().browse(result['order_id'])
        self.assertFalse(order.dms_outlet_visit_id)

    def test_an_out_of_cycle_order_still_passes_the_credit_gate(self):
        """The mark is a mark, not a bypass."""
        self._entitle()
        self.env['dms.outlet.credit'].sudo().search([
            ('res_partner_id', '=', self.outlet_a.id)]).write(
                {'credit_limit': 0.0})
        self.outlet_a.invalidate_recordset()
        result = self._api().dms_portal_submit_out_of_cycle(
            self.outlet_a.id,
            [{'product_id': self.product_a.id, 'quantity': 1}])
        self.assertFalse(result['order_id'])
        self.assertEqual(result['errors'][0]['code'], 'credit_blocked')
