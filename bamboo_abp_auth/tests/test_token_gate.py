# -*- coding: utf-8 -*-
"""The one check worth keeping: which Bearer tokens this module claims.

`_token_is_ours` decides whether a request is handled here or handed to the next
Bearer handler (bamboo_token_auth). Get it wrong in one direction and ABP logins
stop working; wrong in the other and every bamboo JWT pays a JWKS fetch and a
failed RS256 verification before falling through.
"""

from odoo.tests import TransactionCase, tagged
from odoo.tools import config

AUTHORITY = 'https://authserver.test/abp'


@tagged('post_install', '-at_install')
class TestTokenGate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        try:
            import jwt  # noqa: F401
            from cryptography.hazmat.primitives.asymmetric import rsa
        except ImportError:
            cls.skipTest(cls, 'PyJWT[crypto] is not installed')
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.IrHttp = cls.env['ir.http']

    def _config(self, **values):
        """Set odoo.conf options for one test and put them back afterwards."""
        for key, value in values.items():
            old = config.get(key)
            config[key] = value
            self.addCleanup(config.__setitem__, key, old)

    def _rs256(self, iss):
        import jwt
        return jwt.encode({'sub': 'u1', 'iss': iss}, self.key, algorithm='RS256')

    def test_gate(self):
        import jwt
        self._config(openid_authority=AUTHORITY, openid_client_id='bamboo-test')

        # An HS256 token is bamboo_token_auth's; never ours, whatever it claims.
        hs256 = jwt.encode({'uid': 2, 'iss': AUTHORITY}, 'secret', algorithm='HS256')
        self.assertFalse(self.IrHttp._token_is_ours(hs256))

        self.assertTrue(self.IrHttp._token_is_ours(self._rs256(AUTHORITY)))
        # AuthServers are inconsistent about the trailing slash.
        self.assertTrue(self.IrHttp._token_is_ours(self._rs256(AUTHORITY + '/')))

        self.assertFalse(self.IrHttp._token_is_ours(self._rs256('https://evil.test')))
        self.assertFalse(self.IrHttp._token_is_ours(self._rs256('')))
        # Opaque/reference token, or plain garbage: not a JWT, not ours.
        self.assertFalse(self.IrHttp._token_is_ours('opaque-reference-token'))

    def test_openid_issuer_overrides_authority(self):
        """An AuthServer behind a proxy issues tokens naming its internal URL."""
        internal = 'http://authserver:8080'
        self._config(
            openid_authority=AUTHORITY, openid_client_id='bamboo-test',
            openid_issuer='%s,%s' % (AUTHORITY, internal),
        )
        self.assertTrue(self.IrHttp._token_is_ours(self._rs256(internal)))
        self.assertTrue(self.IrHttp._token_is_ours(self._rs256(AUTHORITY)))
        self.assertFalse(self.IrHttp._token_is_ours(self._rs256('https://evil.test')))

    def test_unconfigured_claims_nothing(self):
        """No AuthServer configured: every token belongs to somebody else."""
        self._config(openid_authority='', openid_client_id='', openid_issuer='')
        self.assertFalse(self.IrHttp._token_is_ours(self._rs256(AUTHORITY)))
