# -*- coding: utf-8 -*-
"""Clean up after the rename from `bamboo_token_authentication`.

Odoo does not rename modules. On a database where the old name was installed,
its directory is simply gone after an upgrade, and every server start logs

    Some modules are not loaded, some dependencies or manifest may be missing:
    ['bamboo_token_authentication']

forever. Doing this in a hook rather than by hand means every deployment heals
itself on the first install of the new name, instead of each one hitting the
same error and someone remembering the same SQL.

Dropping the row rather than renaming it is deliberate: by the time this runs,
Odoo's module scan has already created the `bamboo_token_auth` row, so a rename
would collide on the unique name. And there is nothing to carry over — the old
module owned no fields, no ACLs and no data of its own, only the three shared
`ir.http` model/field rows that every module inheriting ir.http gets, which the
new name already has its own copy of.
"""

import logging

_logger = logging.getLogger(__name__)

_OLD_NAME = 'bamboo_token_authentication'


def pre_init_hook(env):
    cr = env.cr
    cr.execute("SELECT id, state FROM ir_module_module WHERE name = %s", (_OLD_NAME,))
    row = cr.fetchone()
    if not row:
        return
    module_id, state = row
    cr.execute("DELETE FROM ir_model_data WHERE module = %s", (_OLD_NAME,))
    removed = cr.rowcount
    cr.execute("DELETE FROM ir_module_module_dependency WHERE module_id = %s", (module_id,))
    cr.execute("DELETE FROM ir_module_module WHERE id = %s", (module_id,))
    _logger.info(
        "bamboo_token_auth: removed the stale %r module record (was %s) and %s "
        "ir.model.data rows it owned; this module replaces it.",
        _OLD_NAME, state, removed,
    )
