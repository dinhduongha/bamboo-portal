"""Plan 18A ticket B18-02 — the channel account and its webhook contract.

Section 5, step 1: "Verify signature/token/timestamp/replay window."
Section 8: "Record stores secret reference only; raw secret in approved
backend."
"""
import hashlib
import hmac
import time

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


class ChannelCase(TransactionCase):

    SECRET = 'a-signing-secret'
    SECRET_KEY = 'dms.channel.test.secret'

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(
            self.SECRET_KEY, self.SECRET)
        self.account = self.env['dms.channel.account'].create({
            'name': 'CH Zalo', 'channel': 'zalo',
            'external_account_id': 'oa-123',
            'secret_ref': self.SECRET_KEY,
            'can_receive_orders': True,
        })

    def _sign(self, body, timestamp):
        payload = f'{timestamp}.'.encode() + body.encode()
        return hmac.new(self.SECRET.encode(), payload,
                        hashlib.sha256).hexdigest()


@tagged('post_install', '-at_install')
class TestChannelAccountSecret(ChannelCase):

    def test_the_secret_is_not_stored_on_the_record(self):
        """Section 8. The field holds a KEY; the value lives in
        `ir.config_parameter`. `password=True` is not a recognised field
        parameter in Odoo 19 and never restricted read, RPC or export --
        keeping the value off the record is what actually keeps it out of a
        CSV export (CLAUDE.md section 5.5)."""
        dumped = str(self.account.sudo().read()[0])
        self.assertNotIn(self.SECRET, dumped)
        self.assertIn(self.SECRET_KEY, dumped)

    def test_activation_refuses_an_account_with_no_secret(self):
        bare = self.env['dms.channel.account'].create({
            'name': 'CH Bare', 'channel': 'tiktok',
            'external_account_id': 'shop-1',
            'secret_ref': 'dms.channel.absent'})
        with self.assertRaises(UserError):
            bare.action_activate()
        self.assertEqual(bare.state, 'draft')

    def test_a_non_positive_replay_window_is_refused(self):
        with self.assertRaises(ValidationError):
            self.account.write({'replay_window_seconds': 0})

    def test_the_unique_key_is_in_postgres(self):
        self.env.cr.execute("""
            SELECT conname FROM pg_constraint
             WHERE conrelid = 'dms_channel_account'::regclass
               AND contype = 'u'
        """)
        self.assertTrue(self.env.cr.fetchall())


@tagged('post_install', '-at_install')
class TestChannelWebhookVerification(ChannelCase):

    def setUp(self):
        super().setUp()
        self.account.action_activate()

    def test_a_valid_signature_passes(self):
        now = int(time.time())
        self.assertTrue(self.account.dms_verify_webhook(
            '{"a":1}', self._sign('{"a":1}', now), now))

    def test_a_wrong_signature_raises_rather_than_returning_false(self):
        """A caller who forgets to check a boolean has written an open
        webhook, and nothing complains. There is no False to ignore."""
        now = int(time.time())
        with self.assertRaises(UserError):
            self.account.dms_verify_webhook('{"a":1}', 'deadbeef', now)

    def test_a_tampered_body_fails_even_with_the_right_signature(self):
        now = int(time.time())
        signature = self._sign('{"a":1}', now)
        with self.assertRaises(UserError):
            self.account.dms_verify_webhook('{"a":2}', signature, now)

    def test_an_old_timestamp_is_outside_the_replay_window(self):
        old = int(time.time()) - 3600
        with self.assertRaises(UserError):
            self.account.dms_verify_webhook(
                '{"a":1}', self._sign('{"a":1}', old), old)

    def test_a_future_timestamp_is_also_refused(self):
        """Clock skew cuts both ways; accepting the future is accepting a
        request signed for replay later."""
        ahead = int(time.time()) + 3600
        with self.assertRaises(UserError):
            self.account.dms_verify_webhook(
                '{"a":1}', self._sign('{"a":1}', ahead), ahead)

    def test_a_missing_timestamp_is_refused(self):
        with self.assertRaises(UserError):
            self.account.dms_verify_webhook('{"a":1}', 'x', None)

    def test_a_suspended_account_verifies_nothing(self):
        self.account.action_suspend()
        now = int(time.time())
        with self.assertRaises(UserError):
            self.account.dms_verify_webhook(
                '{"a":1}', self._sign('{"a":1}', now), now)
