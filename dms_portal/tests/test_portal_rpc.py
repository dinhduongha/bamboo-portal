"""Plan 16A Task 4 — the one entry point, and what it refuses.

CLAUDE.md section 6: a public model method serves BOTH
`/web/dataset/call_kw/<model>/<method>` and `/json/2/<model>/<method>`, so
new features add no controller. It also says the entry point takes no
client-supplied scope -- everything is derived from the authenticated user.
"""
import inspect

from odoo.tests.common import tagged

from .test_entitlement import EntitlementCase


@tagged('post_install', '-at_install')
class TestPortalContextRpc(EntitlementCase):

    def test_context_takes_no_client_supplied_partner(self):
        """A signature with nowhere to put a partner id is the cheapest way
        to make sure a client cannot send one -- the same reasoning that made
        `_SUBMIT_FIELDS` an allow-list in 07C rather than a `pop` of a few
        keys. A field added later defaults to REFUSED, not to accepted."""
        with self.assertRaises(TypeError):
            self.env['res.users'].with_user(self.buyer).dms_portal_context(
                partner_ids=[self.outlet_b.id])

    def test_context_lists_only_approved_partners(self):
        ent = self._entitlement()
        ent.with_user(self.approver).action_approve()
        self._entitlement(partner=self.outlet_b)   # still `requested`
        ctx = self.env['res.users'].with_user(self.buyer).dms_portal_context()
        self.assertEqual([p['id'] for p in ctx['partners']],
                         [self.outlet_a.id])

    def test_context_of_an_unentitled_user_is_empty_not_an_error(self):
        ctx = self.env['res.users'].with_user(self.buyer).dms_portal_context()
        self.assertEqual(ctx['partners'], [])
        self.assertEqual(ctx['company_ids'], [])

    def test_portal_user_a_cannot_read_partner_b_by_id(self):
        """Section 8: "no IDOR by numeric ID". Section 11, first required
        test: portal user A cannot reach Outlet B."""
        ent = self._entitlement()
        ent.with_user(self.approver).action_approve()
        ctx = self.env['res.users'].with_user(self.buyer).dms_portal_context()
        self.assertNotIn(
            self.outlet_b.id, [p['id'] for p in ctx['partners']])

    def test_the_method_is_reachable_over_rpc(self):
        """Three conditions, all checkable here (CLAUDE.md section 6):
        the name does not start with `_`, it carries no `@api.private`, and
        it is a real attribute of the model."""
        method = self.env['res.users'].dms_portal_context
        self.assertFalse(method.__name__.startswith('_'))
        self.assertFalse(
            getattr(method, '_api_private', False),
            '@api.private blocks RPC in Odoo 19')

    def test_the_builder_is_private(self):
        """The public entry point stays thin; the logic sits behind a name
        RPC cannot reach."""
        self.assertTrue(hasattr(self.env['res.users'], '_dms_portal_build_context'))
        source = inspect.getsource(
            type(self.env['res.users']).dms_portal_context)
        self.assertIn('_dms_portal_build_context', source)
