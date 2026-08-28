"""Plan 18C ticket B18-09 — migration, and B18-08's secret half.

Section 11:

  "Replace `dms.messaging.channel.config` plaintext with channel account +
   secret reference. Rotate all migrated tokens; never copy plaintext into
   logs/migration report."
  "Backfill external order keys with channel account; resolve global key
   collisions."
"""
from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .test_channel_account import ChannelCase


@tagged('post_install', '-at_install')
class TestChannelConfigMigration(ChannelCase):

    def setUp(self):
        super().setUp()
        self.legacy = self.env['dms.messaging.channel.config'].sudo().create({
            'channel': 'zalo', 'secret_ref': self.SECRET_KEY,
            'company_id': self.env.company.id})

    def test_a_legacy_config_becomes_a_channel_account(self):
        created = self.env['dms.channel.account'].dms_migrate_messaging_configs()
        self.assertIn(self.legacy, created.mapped('migrated_from_config_id'))

    def test_rerunning_the_migration_creates_nothing_new(self):
        """A migration nobody dares run twice is one that stays half
        finished, permanently."""
        first = self.env['dms.channel.account'].dms_migrate_messaging_configs()
        second = self.env['dms.channel.account'].dms_migrate_messaging_configs()
        self.assertTrue(first)
        self.assertFalse(second)

    def test_an_unknown_channel_is_not_mapped_to_a_plausible_one(self):
        """A Telegram row turned into a Zalo account is a webhook verified
        against the wrong secret, and it would look like it worked."""
        self.env['dms.messaging.channel.config'].sudo().create({
            'channel': 'telegram', 'secret_ref': self.SECRET_KEY,
            'company_id': self.env.company.id})
        created = self.env['dms.channel.account'].dms_migrate_messaging_configs()
        self.assertNotIn('telegram', created.mapped('channel'))

    def test_a_migrated_account_starts_in_draft(self):
        """`action_activate` reads the secret. An account that cannot verify
        anything must not accept a webhook while somebody notices later."""
        created = self.env['dms.channel.account'].dms_migrate_messaging_configs()
        self.assertTrue(created)
        self.assertEqual(set(created.mapped('state')), {'draft'})


@tagged('post_install', '-at_install')
class TestSecretRotation(ChannelCase):

    def test_rotation_takes_a_reference_not_a_value(self):
        """A signature that accepted the secret would put it in every
        traceback, audit log and RPC transcript touching this call."""
        import inspect
        sig = inspect.signature(
            type(self.account).action_rotate_secret)
        self.assertIn('new_secret_ref', sig.parameters)
        self.assertNotIn('secret', sig.parameters)
        self.assertNotIn('new_secret', sig.parameters)

    def test_rotating_onto_an_empty_key_is_refused(self):
        """It would disable verification while looking like it worked."""
        with self.assertRaises(UserError):
            self.account.action_rotate_secret('dms.channel.nothing.here')

    def test_rotating_onto_the_same_key_is_refused(self):
        with self.assertRaises(UserError):
            self.account.action_rotate_secret(self.SECRET_KEY)

    def test_rotation_records_when(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'dms.channel.rotated', 'a-new-secret')
        self.account.action_rotate_secret('dms.channel.rotated')
        self.assertEqual(self.account.sudo().secret_ref,
                         'dms.channel.rotated')
        self.assertTrue(self.account.secret_rotated_at)

    def test_the_new_secret_verifies_and_the_old_one_does_not(self):
        import hashlib
        import hmac
        import time
        self.env['ir.config_parameter'].sudo().set_param(
            'dms.channel.rotated2', 'brand-new-secret')
        self.account.action_activate()
        self.account.action_rotate_secret('dms.channel.rotated2')
        now = int(time.time())
        old_sig = hmac.new(self.SECRET.encode(),
                           f'{now}.'.encode() + b'{}', hashlib.sha256).hexdigest()
        with self.assertRaises(UserError):
            self.account.dms_verify_webhook('{}', old_sig, now)
        new_sig = hmac.new(b'brand-new-secret',
                           f'{now}.'.encode() + b'{}', hashlib.sha256).hexdigest()
        self.assertTrue(self.account.dms_verify_webhook('{}', new_sig, now))


@tagged('post_install', '-at_install')
class TestEb2bKeyBackfill(ChannelCase):

    def setUp(self):
        super().setUp()
        self.account.write({'can_receive_orders': True})
        self.account.action_activate()
        self.outlet = self.env['res.partner'].create({
            'name': 'BK Outlet', 'customer_rank': 1})

    def _staged(self, source):
        return self.env['dms.eb2b.order'].sudo().create({
            'res_partner_id': self.outlet.id,
            'order_source_id': source,
            'order_content': {'lines': []},
        })

    def test_backfill_attaches_a_correctly_keyed_record(self):
        staged = self._staged('LEGACY-1')
        self.env['dms.eb2b.order'].dms_backfill_channel_orders(self.account)
        self.assertTrue(staged.dms_channel_order_id)
        self.assertEqual(staged.dms_channel_order_id.external_order_id,
                         'LEGACY-1')

    def test_backfill_is_idempotent(self):
        self._staged('LEGACY-2')
        first = self.env['dms.eb2b.order'].dms_backfill_channel_orders(
            self.account)
        second = self.env['dms.eb2b.order'].dms_backfill_channel_orders(
            self.account)
        self.assertTrue(first)
        self.assertFalse(second)

    def test_the_legacy_column_and_constraint_are_left_alone(self):
        """Dropping either makes existing rows unreadable through the ORM
        (TRAPS section 22), and reconciliation is the whole reason those rows
        were kept. The repair is a forward path, not a deletion."""
        self.assertIn('order_source_id', self.env['dms.eb2b.order']._fields)
        self.env.cr.execute("""
            SELECT conname FROM pg_constraint
             WHERE conrelid = 'dms_eb2b_order'::regclass AND contype = 'u'
        """)
        self.assertTrue(self.env.cr.fetchall())

    def test_backfill_without_an_account_is_refused(self):
        with self.assertRaises(UserError):
            self.env['dms.eb2b.order'].dms_backfill_channel_orders(None)
