# -*- coding: utf-8 -*-
"""Shared bits for this module's HTTP tests."""


from odoo.tests import HttpCase

from odoo.addons.bamboo_public_api.controllers.common import (
    API_ROOT,
    FASTAPI_PUBLIC_ROOT,
    FASTAPI_ROOT,
)

CONTROLLER_ROOT = API_ROOT
PUBLIC_ROOT = FASTAPI_PUBLIC_ROOT
RPC_ROOT = FASTAPI_ROOT


class BambooFastapiCase(HttpCase):
    """`HttpCase` plus a bamboo JWT minter."""

    def _bearer(self, user):
        """A bamboo_token_auth JWT for `user` — the HS256 flavour.

        The RS256/ABP flavour is not exercised: it needs a live AuthServer to sign
        with. Both land in `request.env.uid` before the dispatcher runs, which is
        the only thing this module depends on, so one of them proves the seam.
        """
        from odoo.addons.bamboo_token_auth.models import issue_token

        return issue_token(self.env, user.id, ttl=3600)

    def _auth_headers(self, user=None):
        user = user or self.env.ref("base.user_admin")
        return {"Authorization": "Bearer %s" % self._bearer(user)}
