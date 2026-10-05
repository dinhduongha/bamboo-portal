import json

from odoo.tests import HttpCase, new_test_user, tagged

from ..models import issue_token


@tagged('post_install', '-at_install')
class TestBearerRevocation(HttpCase):
    """A bearer dies with the credentials it was minted against."""

    def setUp(self):
        super().setUp()
        self.user = new_test_user(self.env, login='tok_user', password='tok_user_pw1')

    def _call(self, token):
        return self.url_open(
            '/json/2/res.users/context_get', data=json.dumps({}),
            headers={'Authorization': 'Bearer %s' % token,
                     'Content-Type': 'application/json'})

    def test_fresh_token_works(self):
        self.assertEqual(self._call(issue_token(self.env, self.user.id)).status_code, 200)

    def test_password_change_revokes(self):
        token = issue_token(self.env, self.user.id)
        self.user.password = 'tok_user_pw2'
        self.env.flush_all()
        self.assertEqual(self._call(token).status_code, 401)

    def test_archive_revokes(self):
        token = issue_token(self.env, self.user.id)
        self.user.active = False
        self.env.flush_all()
        self.assertEqual(self._call(token).status_code, 401)

    def test_token_without_stk_is_refused(self):
        from .. import jwt_min as jwt
        secret = self.env['ir.config_parameter'].sudo().get_param('database.secret')
        bare = jwt.encode({'uid': self.user.id, 'jti': 'x'}, secret)
        self.assertEqual(self._call(bare).status_code, 401)
