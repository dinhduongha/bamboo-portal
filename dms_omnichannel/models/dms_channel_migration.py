from odoo import api, fields, models
from odoo.exceptions import UserError


class DmsChannelAccountMigration(models.Model):
    """Section 11 — moving off the plaintext config, and the order key with it.

    Two migrations, both stated as requirements rather than cleanups:

      "Replace `dms.messaging.channel.config` plaintext with channel account
       + secret reference. Rotate all migrated tokens; never copy plaintext
       into logs/migration report."

      "Backfill external order keys with channel account; resolve global key
       collisions."

    `dms.messaging.channel.config` already stores a `secret_ref` rather than a
    value -- that part was fixed in Phase 0. What it does not have is a
    channel account, a state, capabilities, a replay window or a signature.
    So this is a migration of SHAPE, not of secrets, and the rotation below
    exists because a secret that survived a migration is a secret that has
    been read by whoever ran it.
    """
    _inherit = 'dms.channel.account'

    migrated_from_config_id = fields.Many2one(
        'dms.messaging.channel.config', readonly=True, index=True,
        help='The legacy row this account replaces. Kept so the migration is '
             'rerunnable and auditable, not so anything reads it at runtime.')

    @api.model
    def dms_migrate_messaging_configs(self):
        """Idempotent: rerunning it creates nothing new.

        A migration that is not rerunnable is a migration nobody dares run
        twice, and a half-finished one is then permanent.
        """
        Config = self.env['dms.messaging.channel.config'].sudo()
        created = self.browse()
        for config in Config.search([]):
            if self.sudo().search_count(
                    [('migrated_from_config_id', '=', config.id)]):
                continue
            channel = (config.channel or '').strip().lower()
            if channel not in dict(self._fields['channel'].selection):
                # Not silently mapped to something plausible. A Telegram row
                # turned into a Zalo account is a webhook verified against the
                # wrong secret, and it would look like it worked.
                continue
            created |= self.sudo().create({
                'name': f'{config.channel} (migrated {config.id})',
                'channel': channel,
                'external_account_id': f'legacy-{config.id}',
                'company_id': config.company_id.id,
                'secret_ref': config.secret_ref or f'dms.channel.legacy.{config.id}',
                'migrated_from_config_id': config.id,
                # Left in draft on purpose. `action_activate` reads the secret,
                # and an account that cannot verify anything must not be able
                # to accept a webhook while somebody notices later.
                'state': 'draft',
            })
        return created

    def action_rotate_secret(self, new_secret_ref):
        """Point the account at a NEW key, and never at a value.

        Section 11: "Rotate all migrated tokens; never copy plaintext into
        logs/migration report." A secret that came through a migration has
        been read by whoever ran it, so it is not the secret any more.

        The parameter is a REFERENCE, not the secret. A signature that
        accepted the value would put it in every traceback, every audit log
        and every RPC transcript that touches this call.
        """
        new_secret_ref = (new_secret_ref or '').strip()
        if not new_secret_ref:
            raise UserError(self.env._("Name the config key holding the new secret."))
        if not self.env['ir.config_parameter'].sudo().get_param(
                new_secret_ref):
            raise UserError(
                self.env._("Nothing stored under %r. Rotating onto an empty key disables verification while looking like a rotation.", new_secret_ref))
        for rec in self:
            if rec.sudo().secret_ref == new_secret_ref:
                raise UserError(
                    self.env._("That is the key already in use \u2014 rotating onto it changes nothing and would be recorded as a rotation."))
            rec.sudo().write({
                'secret_ref': new_secret_ref,
                'secret_rotated_at': fields.Datetime.now(),
            })
        return True


class DmsEb2bOrderKeyBackfill(models.Model):
    """The global unique key section 11 lists for repair.

    `dms.eb2b.order` carries `UNIQUE(order_source_id)` — global. Two channels
    number their orders independently, so a TikTok order is rejected because a
    Zalo order happens to share its number, and the rejection looks like a
    duplicate.

    The column is NOT dropped and the constraint is NOT removed here. Dropping
    either makes existing rows unreadable through the ORM (TRAPS §22) and the
    reconciliation those rows exist for is the whole reason they were kept.
    What this adds is the forward path: a migrated row points at the channel
    order that supersedes it, and new external orders go to
    `dms.channel.order`, which is keyed correctly.
    """
    _inherit = 'dms.eb2b.order'

    dms_channel_order_id = fields.Many2one(
        'dms.channel.order', readonly=True, index=True,
        help='The correctly-keyed record that supersedes this staging row.')

    @api.model
    def dms_backfill_channel_orders(self, channel_account):
        """Attach legacy staging rows to a channel account, idempotently."""
        if not channel_account:
            raise UserError(self.env._("Name the channel account these rows belong to."))
        ChannelOrder = self.env['dms.channel.order'].sudo()
        touched = self.browse()
        for rec in self.sudo().search([('dms_channel_order_id', '=', False)]):
            mapped = ChannelOrder.dms_record_external_order(
                channel_account.id, rec.order_source_id,
                rec.order_content or {})
            rec.dms_channel_order_id = mapped.id
            touched |= rec
        return touched
