# -*- coding: utf-8 -*-
"""The marker a client probes to find out this addon is here."""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class BambooIdempotency(models.AbstractModel):
    """Exists so a client can ask "is server-side dedup available?".

    A client cannot read `ir.module.module` — that is an administrator's table —
    so "is this addon installed" has to be answerable some other way. `ir.model`
    *is* readable, and the app already probes it to decide whether a model
    exists (see `CrmFields.hasModel`). Declaring an abstract model here therefore
    costs one row in `ir.model` and reuses a capability check the client already
    has, instead of inventing a new endpoint and a new access rule.

    Abstract on purpose: there is nothing to store.
    """

    _name = 'bamboo.idempotency'
    _description = 'Bamboo Idempotency Capability'

    @api.model
    def _uuidv7_available(self):
        """Whether this PostgreSQL can generate UUIDv7 itself (18+).

        The server-side default is a convenience, not the mechanism: clients
        mint their own UUIDv7 for anything they queue. On an older PostgreSQL
        the column simply has no default, records made outside the app carry no
        key, and idempotent create still works exactly as designed.
        """
        from .base import _uuidv7_available

        return _uuidv7_available(self.env.cr)

    @api.model
    def bamboo_capabilities(self):
        """What a freshly logged-in client wants to know, in one call."""
        return {
            'idempotent_create': True,
            'uuid_version': 7,
            'server_uuid_default': self._uuidv7_available(),
        }
