"""Plan 18A ticket B18-04 — identity mapping, and the three refusals.

Master section 2.10, restated in plan 16 section 5.2 and plan 18 section 7:

1. The client sends the token the channel issued; the server exchanges it.
   A number the client declares is never trusted.
2. A matching phone number does NOT grant. It creates a link request.
3. A number matching several outlets, or none, goes to an exception. Nothing
   is chosen on the caller's behalf and no outlet is created.
"""
from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .test_channel_account import ChannelCase


@tagged('post_install', '-at_install')
class TestChannelIdentity(ChannelCase):

    def setUp(self):
        super().setUp()
        self.Identity = self.env['dms.channel.identity']
        self.shop = self.env['res.partner'].create({
            'name': 'CH Shop', 'customer_rank': 1, 'phone': '0900000001'})

    def test_a_matching_phone_creates_a_request_not_a_grant(self):
        identity = self.Identity.dms_resolve_from_token(
            self.account.id, 'zalo-user-1', phone_from_channel='0900000001')
        self.assertEqual(identity.state, 'requested')
        self.assertEqual(identity.partner_id, self.shop)

    def test_two_matching_outlets_go_to_ambiguous_and_pick_nothing(self):
        self.env['res.partner'].create({
            'name': 'CH Shop Two', 'customer_rank': 1,
            'phone': '0900000001'})
        identity = self.Identity.dms_resolve_from_token(
            self.account.id, 'zalo-user-2', phone_from_channel='0900000001')
        self.assertEqual(identity.state, 'ambiguous')
        self.assertFalse(
            identity.partner_id,
            'picking one is a coin toss whose loser is a shop owner reading '
            'somebody else\'s receivables')

    def test_no_match_does_not_create_an_outlet(self):
        before = self.env['res.partner'].search_count([])
        identity = self.Identity.dms_resolve_from_token(
            self.account.id, 'zalo-user-3', phone_from_channel='0999999999')
        self.assertEqual(identity.state, 'unmatched')
        self.assertEqual(self.env['res.partner'].search_count([]), before)

    def test_resolving_twice_returns_the_same_record(self):
        first = self.Identity.dms_resolve_from_token(
            self.account.id, 'zalo-user-4', phone_from_channel='0900000001')
        second = self.Identity.dms_resolve_from_token(
            self.account.id, 'zalo-user-4', phone_from_channel='0900000001')
        self.assertEqual(first, second)

    def test_the_signature_has_no_client_declared_phone(self):
        """Constraint 1. A parameter called `phone` invites somebody to pass
        the one the client typed; `phone_from_channel` says where it must
        come from."""
        import inspect
        sig = inspect.signature(type(self.Identity).dms_resolve_from_token)
        self.assertIn('phone_from_channel', sig.parameters)
        self.assertNotIn('phone', sig.parameters)

    def test_approving_a_link_still_grants_no_document_access(self):
        """The link says "this Zalo user is that shop". Reading orders and
        debt is `dms.portal.entitlement` in `dms_portal`, deliberately a
        separate approval."""
        identity = self.Identity.dms_resolve_from_token(
            self.account.id, 'zalo-user-5', phone_from_channel='0900000001')
        identity.action_approve()
        self.assertEqual(identity.state, 'approved')
        portal_user = self.env['res.users'].create({
            'name': 'CH Buyer', 'login': 'ch-buyer@dms.test',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])]})
        self.assertFalse(
            portal_user.dms_allowed_partner_ids(),
            'an approved channel link handed out document access by itself')

    def test_approving_an_ambiguous_link_needs_a_named_outlet(self):
        self.env['res.partner'].create({
            'name': 'CH Shop Three', 'customer_rank': 1,
            'phone': '0900000001'})
        identity = self.Identity.dms_resolve_from_token(
            self.account.id, 'zalo-user-6', phone_from_channel='0900000001')
        with self.assertRaises(UserError):
            identity.action_approve()

    def test_the_unique_key_is_in_postgres(self):
        self.env.cr.execute("""
            SELECT conname FROM pg_constraint
             WHERE conrelid = 'dms_channel_identity'::regclass
               AND contype = 'u'
        """)
        self.assertTrue(self.env.cr.fetchall())
