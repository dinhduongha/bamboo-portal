"""Plan 16A Task 5 — a revoked entitlement whose session is still open is a
read permission that is still open.

Section 4: "revoke assignment chan ngay va invalidate session". Section 11
lists it as a required test: "Revoke entitlement blocks active session and
pull data, ke ca phien Zalo Mini App."

Odoo already has the machinery: the session token is an HMAC over
`_get_session_token_fields()`, and `http.py` compares the token in the
session against a freshly computed one on every request. Adding a field to
that set is exactly how core handles passkeys. Nothing new is invented here.
"""
from odoo.tests.common import tagged

from .test_entitlement import EntitlementCase


@tagged('post_install', '-at_install')
class TestEntitlementRevokeKillsSessions(EntitlementCase):

    def test_the_version_field_is_part_of_the_session_token(self):
        self.assertIn(
            'dms_portal_entitlement_version',
            self.env['res.users']._get_session_token_fields(),
            'a field outside this set cannot invalidate a session, however '
            'diligently it is bumped')

    def test_revoke_changes_the_session_token(self):
        ent = self._entitlement()
        ent.with_user(self.approver).action_approve()
        before = self.buyer._compute_session_token('a-session-id')

        ent.with_user(self.approver).action_revoke(reason='contract ended')

        self.env.registry.clear_cache()
        after = self.buyer._compute_session_token('a-session-id')
        self.assertNotEqual(
            before, after,
            'the token a live session carries still validates, so the '
            'session survives the revocation')

    def test_approve_also_changes_the_session_token(self):
        """Granting has to invalidate too. A session opened before the grant
        carries a token computed from the old version; leaving it valid means
        the grant needs a re-login to take effect, which is the same bug in
        the pleasant direction."""
        ent = self._entitlement()
        before = self.buyer._compute_session_token('another-session-id')
        ent.with_user(self.approver).action_approve()
        self.env.registry.clear_cache()
        after = self.buyer._compute_session_token('another-session-id')
        self.assertNotEqual(before, after)

    def test_revoke_is_audited(self):
        ent = self._entitlement()
        ent.with_user(self.approver).action_approve()
        ent.with_user(self.approver).action_revoke(reason='shop closed')
        self.assertEqual(ent.revoke_reason, 'shop closed')
        self.assertEqual(ent.revoked_by_id, self.approver)
        self.assertTrue(ent.revoke_date)

    def test_an_unrelated_users_token_is_untouched(self):
        other = self.env['res.users'].create({
            'name': 'Other Buyer', 'login': 'other-16a@dms.test',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        before = other._compute_session_token('third-session-id')
        ent = self._entitlement()
        ent.with_user(self.approver).action_approve()
        self.env.registry.clear_cache()
        self.assertEqual(
            before, other._compute_session_token('third-session-id'),
            'revoking one entitlement logged out an unrelated portal user')
