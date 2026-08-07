import base64
import hashlib
import json
import logging
import os
import secrets
import time
import urllib.parse

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools import config
from odoo.addons.auth_oauth.controllers.main import OAuthLogin

_logger = logging.getLogger(__name__)

# In-process PyJWKClient cache keyed by jwks_uri (each client caches signing keys).
_JWK_CLIENTS = {}

# Resolved jwks_uri per authority. Without this, OIDC discovery is an HTTP GET on
# every single token validation.
_JWKS_URIS = {}


def _config(key, default=None):
    """Read a setting from odoo.conf first, then ir.config_parameter, then default.

    Mirrors laoid_auth's resolver so bamboo_abp_auth is fully standalone — OIDC params
    come from odoo.conf (`openid_*` keys) instead of a database provider record.
    """
    value = config.get(key)
    if value not in (None, ''):
        return value
    try:
        if request and request.env:
            param = request.env['ir.config_parameter'].sudo().get_param(key)
            if param not in (None, ''):
                return param
    except Exception:
        pass
    return default


def _public_base():
    """Return ``scheme://host`` for building OIDC redirect/callback URLs.

    Behind a TLS-terminating reverse proxy ``request.httprequest.host_url`` is
    ``http://``, but the IdP only accepts the registered ``https`` callback.
    Resolution order:
      1. ``openid_redirect_uri`` (explicit full URL) → its scheme+host.
      2. the request host, upgraded to https unless it is localhost/127.0.0.1
         (override either way with ``openid_force_https = True|False`` in odoo.conf).
    """
    explicit = _config('openid_redirect_uri')
    if explicit:
        parts = urllib.parse.urlsplit(explicit)
        if parts.scheme and parts.netloc:
            return '%s://%s' % (parts.scheme, parts.netloc)
    root = request.httprequest.host_url.rstrip('/')
    forced = _config('openid_force_https')
    if forced is None:
        upgrade = ('://localhost' not in root) and ('://127.0.0.1' not in root)
    else:
        upgrade = str(forced).strip().lower() in ('1', 'true', 'yes', 'on')
    if upgrade and root.startswith('http://'):
        root = 'https://' + root[len('http://'):]
    return root


def _json_response(body, status=200):
    """Plain JSON http response (CORS is handled globally by bamboo_cors)."""
    return request.make_response(
        json.dumps(body),
        headers=[('Content-Type', 'application/json')],
        status=status,
    )


class AbpOidc:
    """Stateless OIDC helper — all params from odoo.conf `openid_*` keys.

    Replaces the former `res.auth.provider` database model. Validates RS256
    Bearer/JWT tokens via the AuthServer's JWKS.
    """

    @classmethod
    def authority(cls):
        url = _config('openid_authority')
        return url.rstrip('/') if url else None

    @classmethod
    def client_id(cls):
        return _config('openid_client_id')

    @classmethod
    def client_secret(cls):
        return _config('openid_client_secret')

    @classmethod
    def scope(cls):
        return _config('openid_scope', 'openid email profile roles')

    @classmethod
    def audience(cls):
        return _config('openid_audience') or cls.client_id()

    @classmethod
    def issuers(cls):
        """Accepted `iss` claim values, trailing slash stripped.

        `openid_issuer` (comma-separated) when set, else the authority. A list
        rather than one value because an AuthServer behind a reverse proxy often
        issues tokens naming its internal URL while clients reach it by the
        public one; both are the same issuer and both must be accepted.
        """
        raw = _config('openid_issuer') or cls.authority() or ''
        return [i.strip().rstrip('/') for i in str(raw).split(',') if i.strip()]

    @classmethod
    def issued_here(cls, iss):
        """Whether `iss` names this AuthServer."""
        return bool(iss) and str(iss).rstrip('/') in cls.issuers()

    @classmethod
    def jwks_uri(cls):
        """Explicit `openid_jwks_uri`, else OIDC-discover from the authority.

        The discovery result is cached per authority: this runs on every token
        validation, and an HTTP GET per request is not a lookup, it is a
        dependency on the IdP being up for each of our own API calls.
        """
        uri = _config('openid_jwks_uri')
        if uri:
            return uri
        base = cls.authority()
        if not base:
            return None
        if base in _JWKS_URIS:
            return _JWKS_URIS[base]
        uri = '%s/.well-known/jwks' % base
        try:
            import requests
            disco = requests.get('%s/.well-known/openid-configuration' % base, timeout=5)
            if disco.ok:
                uri = disco.json().get('jwks_uri', uri)
                _JWKS_URIS[base] = uri
        except Exception:
            # Not cached: a transient IdP outage must not pin the fallback URI
            # for the life of the process.
            pass
        return uri

    @classmethod
    def is_configured(cls):
        return bool(cls.authority() and cls.client_id())

    # ---- tokens this module issues itself ---------------------------------
    #
    # After an SSO round-trip the client should not have to keep presenting
    # ABP's token: it expires on the AuthServer's schedule, it means a JWKS
    # fetch on our side, and it ties every API call to the IdP being reachable.
    # So `/api/v1/auth/callback` (POST) hands back a token of our own.
    #
    # `iss` is what separates the two flavours everywhere else in this module —
    # ours are HS256 with this issuer, ABP's are RS256 with the AuthServer's.
    # bamboo_token_auth's tokens carry no `iss` at all, so nothing collides.
    SELF_ISSUER = 'bamboo_abp_auth'

    @classmethod
    def jwt_secret(cls, env=None):
        """HMAC key for our own tokens: `openid_jwt_secret`, else database.secret.

        The default shares Odoo's own secret, which is what makes this work with
        no configuration. Set `openid_jwt_secret` to give SSO tokens a key of
        their own — then revoking them does not mean rotating database.secret.

        `env` is explicit so this is callable outside a request (tests, cron).
        """
        secret = _config('openid_jwt_secret')
        if not secret:
            env = env if env is not None else request.env
            secret = env['ir.config_parameter'].sudo().get_param('database.secret')
        if not secret:
            raise UserError('No signing secret available (database.secret is empty).')
        return secret

    @classmethod
    def jwt_ttl(cls):
        """Lifetime of our tokens in seconds; `openid_jwt_ttl`, default 24h.

        Short by default on purpose: the SSO round-trip that mints it is cheap
        to repeat, and a long-lived bearer that outlives the IdP session is the
        thing SSO was supposed to avoid.
        """
        try:
            return int(_config('openid_jwt_ttl') or 86400)
        except (TypeError, ValueError):
            return 86400

    @classmethod
    def issue_token(cls, user, claims=None):
        """Mint an HS256 JWT identifying `user`. Returns (token, expires_in)."""
        import jwt

        claims = claims or {}
        now = int(time.time())
        ttl = cls.jwt_ttl()
        payload = {
            'iss': cls.SELF_ISSUER,
            'sub': str(user.id),
            'uid': user.id,
            'login': user.login,
            'iat': now,
            'exp': now + ttl,
        }
        # Kept for audit: which ABP identity this token was minted from.
        if claims.get('sub'):
            payload['abp_sub'] = claims['sub']
        if claims.get('tenantid'):
            payload['tenantid'] = claims['tenantid']
        return jwt.encode(payload, cls.jwt_secret(user.env), algorithm='HS256'), ttl

    @classmethod
    def validate_self_token(cls, token, env=None):
        """Verify one of our own tokens. Returns the claims dict or raises."""
        import jwt

        try:
            return jwt.decode(
                token, cls.jwt_secret(env), algorithms=['HS256'],
                issuer=cls.SELF_ISSUER, options={'verify_exp': True},
            )
        except jwt.ExpiredSignatureError:
            raise UserError('Token has expired.')
        except jwt.InvalidTokenError as exc:
            raise UserError('Invalid token: %s' % exc)

    @classmethod
    def validate_token(cls, token):
        """Validate an RS256 JWT Bearer token. Returns the claims dict or raises.

        Requires PyJWT[crypto]. Tries audience=client_id (id_token), falling back
        to no-audience verification for access tokens (aud = resource name).
        """
        try:
            import jwt
            from jwt import PyJWKClient
        except ImportError:
            raise UserError('PyJWT is not installed. Run: pip install "PyJWT[crypto]"')

        jwks_uri = cls.jwks_uri()
        if not jwks_uri:
            raise UserError('openid_authority / openid_jwks_uri is not configured.')

        jwks_client = _JWK_CLIENTS.get(jwks_uri)
        if jwks_client is None:
            jwks_client = PyJWKClient(jwks_uri)
            _JWK_CLIENTS[jwks_uri] = jwks_client
        try:
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            try:
                claims = jwt.decode(
                    token, signing_key.key, algorithms=['RS256'],
                    audience=cls.audience(), options={'verify_exp': True},
                )
            except jwt.InvalidAudienceError:
                _logger.warning(
                    'bamboo_abp_auth: audience mismatch for aud=%s, retrying without '
                    'audience check (access_token fallback)', cls.audience(),
                )
                claims = jwt.decode(
                    token, signing_key.key, algorithms=['RS256'],
                    options={'verify_exp': True, 'verify_aud': False},
                )
        except jwt.ExpiredSignatureError:
            raise UserError('JWT token has expired.')
        except jwt.InvalidTokenError as exc:
            raise UserError('Invalid JWT token: %s' % exc)

        # Verified last because `issuers()` may hold several values and PyJWT's
        # own `issuer=` takes one. Without this the only thing tying a token to
        # this AuthServer is the JWKS it happened to be signed with.
        if not cls.issued_here(claims.get('iss')):
            raise UserError(
                'JWT issuer %r is not %s.' % (claims.get('iss'), cls.issuers()))
        return claims

    @classmethod
    def exchange_code(cls, code, code_verifier, redirect_uri):
        """Exchange an authorization code (PKCE) for tokens at /connect/token.

        Shared by the web callback and the SPA token endpoint. Returns the token
        response dict; raises UserError on failure. ``redirect_uri`` MUST match the
        one sent to /connect/authorize.
        """
        import requests
        post_data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
            'client_id': cls.client_id(),
            'code_verifier': code_verifier,
        }
        if cls.client_secret():
            post_data['client_secret'] = cls.client_secret()
        resp = requests.post(
            '%s/connect/token' % cls.authority(), data=post_data, timeout=15)
        if not resp.ok:
            _logger.error('bamboo_abp_auth: Token exchange failed [%s]: %s',
                          resp.status_code, resp.text)
            raise UserError('Token exchange failed (%s)' % resp.status_code)
        return resp.json()


class AbpAuthLogin(OAuthLogin):
    """Inject a single ABP AuthServer button into the standard /web/login page."""

    def list_providers(self):
        result = super().list_providers()
        if AbpOidc.is_configured():
            result.append({
                'id': -1,
                'name': 'ABP AuthServer',
                'body': 'Login with SSO',
                'css_class': 'fa fa-fw fa-shield text-primary',
                'auth_link': '/api/v1/auth/login',
            })
        return result


class AbpAuthController(http.Controller):
    """ABP AuthServer OIDC Authorization Code + PKCE flow endpoints."""

    @http.route('/api/v1/auth/login', type='http', auth='public', methods=['GET'],
                csrf=False, readonly=False)
    def login(self, redirect_uri=None, **kwargs):
        """Redirect the browser to the ABP AuthServer authorization endpoint."""
        if not AbpOidc.is_configured():
            return request.make_response(
                json.dumps({'success': False, 'error': 'No SSO provider configured'}),
                headers=[('Content-Type', 'application/json')],
                status=503,
            )

        # PKCE (S256) — required by ABP and best practice for Authorization Code flow
        code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode()
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b'=').decode()

        nonce = secrets.token_urlsafe(16)
        base = _public_base()
        callback_url = base + '/api/v1/auth/callback'
        redirect_to = redirect_uri or (base + '/odoo')

        # readonly=False ensures these session writes are persisted.
        # spa=True when the caller passed its own return URL → the callback hands the
        # token back via that URL instead of creating an Odoo web session.
        request.session['abp_oauth_state_nonce'] = nonce
        request.session['abp_oauth_state_data'] = json.dumps({
            'redirect': redirect_to,
            'code_verifier': code_verifier,
            'spa': bool(redirect_uri),
        })

        params = urllib.parse.urlencode({
            'response_type': 'code',
            'client_id': AbpOidc.client_id(),
            'redirect_uri': callback_url,
            'scope': AbpOidc.scope(),
            'state': nonce,
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256',
            'prompt': 'login',
        })
        return request.redirect(
            '%s/connect/authorize?%s' % (AbpOidc.authority(), params),
            local=False,
        )

    @http.route('/api/v1/auth/callback', type='http', auth='public', methods=['GET'],
                csrf=False, readonly=False)
    def callback(self, code=None, state=None, error=None, **kwargs):
        """Handle the OIDC authorization code callback from ABP AuthServer."""
        if error:
            _logger.warning('bamboo_abp_auth: OIDC callback error: %s', error)
            return request.redirect('/web/login?oauth_error=2')

        # CSRF validation via nonce stored in session
        stored_nonce = request.session.pop('abp_oauth_state_nonce', None)
        state_data_raw = request.session.pop('abp_oauth_state_data', None)

        if not stored_nonce or stored_nonce != state:
            _logger.warning(
                'bamboo_abp_auth: OAuth state mismatch (stored=%s, received=%s) — '
                'possible CSRF or session loss', stored_nonce, state
            )
            return request.redirect('/web/login?oauth_error=2')

        try:
            state_data = json.loads(state_data_raw or '{}')
        except Exception:
            state_data = {}

        redirect_url = state_data.get('redirect') or '/odoo'
        code_verifier = state_data.get('code_verifier', '')

        if not AbpOidc.is_configured():
            return request.redirect('/web/login?oauth_error=2')

        # Exchange authorization code for tokens (include PKCE code_verifier).
        # redirect_uri MUST match the one sent to /connect/authorize in login().
        try:
            token_data = AbpOidc.exchange_code(
                code, code_verifier, _public_base() + '/api/v1/auth/callback')
        except Exception as exc:
            _logger.error('bamboo_abp_auth: Token exchange exception: %s', exc)
            return request.redirect('/web/login?oauth_error=2')

        id_token = token_data.get('id_token') or token_data.get('access_token')
        if not id_token:
            _logger.error('bamboo_abp_auth: No id_token or access_token in provider response: %s', token_data)
            return request.redirect('/web/login?oauth_error=2')

        # Validate JWT and provision user (does not touch session)
        try:
            from odoo.addons.bamboo_abp_auth.models.ir_http import IrHttp
            user, claims = IrHttp._validate_and_provision(id_token)
        except Exception as exc:
            _logger.error('bamboo_abp_auth: Token validation / provisioning failed: %s', exc)
            return request.redirect('/web/login?oauth_error=3')

        # SPA flow: hand the ABP access_token back to the frontend via its return URL;
        # the SPA then calls Odoo APIs with it as a Bearer (validated by ir_http). No
        # Odoo web session is created here.
        if state_data.get('spa'):
            request.env.cr.commit()
            access_token = token_data.get('access_token') or id_token
            sep = '&' if '?' in redirect_url else '?'
            return request.redirect(
                '%s%saccess_token=%s&uid=%s' % (
                    redirect_url, sep, urllib.parse.quote(access_token), user.id),
                303)

        # Web flow: authenticate session through Odoo's credential pipeline
        # (respects MFA, session token computation, last_login update)
        credential = {
            'type': 'abp_token',
            'login': user.login,
            'abp_sub': claims.get('sub'),
        }
        try:
            # Odoo 18 Session.authenticate(dbname, credential) — first arg is the DB
            # NAME (used for Registry(dbname)), not an Environment.
            db_name = request.session.db or request.env.cr.dbname
            request.session.authenticate(db_name, credential)
        except Exception as exc:
            _logger.error('bamboo_abp_auth: Session authentication failed: %s', exc)
            return request.redirect('/web/login?oauth_error=3')

        return request.redirect(redirect_url, 303)

    @http.route('/api/v1/auth/callback', type='http', auth='public',
                methods=['POST', 'OPTIONS'], csrf=False)
    def callback_post(self, **kwargs):
        """Exchange an ABP identity for one of ours, and hand back our own JWT.

        Two ways in, whichever the client already has:

        * ``code`` (+ ``code_verifier``, ``redirect_uri``) — the client did the
          /connect/authorize redirect itself and holds an authorization code.
        * ``token`` — the client already holds an ABP id_token/access_token.

        Either way the token is verified against the AuthServer, the Odoo user
        is provisioned exactly as on the browser callback, and the response
        carries a token this module issued. From then on the client presents
        ours: no JWKS fetch per request, no expiry on the IdP's schedule, and
        nothing breaks when the AuthServer is briefly unreachable.

        This is the GET callback's sibling on the same path — that one is the
        browser redirect and ends in a session cookie; this one is for a client
        that wants a token back in the response body.

        Body may be JSON, form-urlencoded or multipart: Odoo hands form fields
        in as kwargs, and a JSON body is merged over them.
        """
        if request.httprequest.method == 'OPTIONS':
            return _json_response({}, status=204)
        if not AbpOidc.is_configured():
            return _json_response(
                {'success': False, 'error': 'No SSO provider configured'}, 503)

        payload = dict(kwargs)
        try:
            raw = request.httprequest.get_data(as_text=True)
            if raw:
                payload.update(json.loads(raw))
        except Exception:
            pass

        code = (payload.get('code') or payload.get('authorization_code') or '').strip()
        abp_token = (payload.get('token') or payload.get('access_token')
                     or payload.get('id_token') or '').strip()
        if not code and not abp_token:
            return _json_response(
                {'success': False, 'error': 'Provide either "code" or "token".'}, 400)

        token_data = {}
        try:
            if code:
                redirect_uri = (payload.get('redirect_uri')
                                or payload.get('redirectUri')
                                or (_public_base() + '/api/v1/auth/callback'))
                code_verifier = (payload.get('code_verifier')
                                 or payload.get('codeVerifier') or '')
                token_data = AbpOidc.exchange_code(code, code_verifier, redirect_uri)
                abp_token = token_data.get('id_token') or token_data.get('access_token')
                if not abp_token:
                    return _json_response(
                        {'success': False,
                         'error': 'No token in provider response.'}, 502)

            from odoo.addons.bamboo_abp_auth.models.ir_http import IrHttp
            user, claims = IrHttp._validate_and_provision(abp_token)
            access_token, expires_in = AbpOidc.issue_token(user, claims)
        except Exception as exc:
            _logger.error('bamboo_abp_auth: callback POST failed: %s', exc)
            return _json_response({'success': False, 'error': str(exc)}, 401)

        # The exchange and the provisioning both wrote; a client that got a
        # token back must find the user there on its next request.
        request.env.cr.commit()

        data = {
            'access_token': access_token,
            'token_type': 'Bearer',
            'expires_in': expires_in,
            'uid': user.id,
            'user': {
                'id': user.id,
                'login': user.login,
                'name': user.name,
                'email': user.email or '',
            },
        }
        if token_data:
            # The AuthServer's own tokens, for a client that still needs to talk
            # to ABP directly (refresh, logout, its other APIs).
            data['abp'] = {
                'access_token': token_data.get('access_token', ''),
                'refresh_token': token_data.get('refresh_token', ''),
                'id_token': token_data.get('id_token', ''),
                'expires_in': token_data.get('expires_in', 0),
            }
        return _json_response({'success': True, 'data': data})

    @http.route('/api/v1/auth/abp/token', type='http', auth='public',
                methods=['POST', 'OPTIONS'], csrf=False)
    def spa_token(self, **kwargs):
        """SPA login: exchange an authorization code (PKCE) for the ABP access_token.

        The frontend performs the /connect/authorize redirect itself, then POSTs the
        returned code here (JSON or form). Response: {success, data:{access_token,…}}.
        The SPA uses access_token as a Bearer on Odoo API calls (validated by ir_http).
        """
        if request.httprequest.method == 'OPTIONS':
            return _json_response({}, status=204)
        if not AbpOidc.is_configured():
            return _json_response({'success': False, 'error': 'No SSO provider configured'}, 503)

        payload = dict(kwargs)
        try:
            raw = request.httprequest.get_data(as_text=True)
            if raw:
                payload.update(json.loads(raw))
        except Exception:
            pass

        code = payload.get('code') or payload.get('authorization_code')
        code_verifier = payload.get('code_verifier') or payload.get('codeVerifier') or ''
        redirect_uri = payload.get('redirect_uri') or payload.get('redirectUri') \
            or (_public_base() + '/api/v1/auth/callback')
        if not code:
            return _json_response({'success': False, 'error': 'Missing authorization code.'}, 400)

        try:
            token_data = AbpOidc.exchange_code(code, code_verifier, redirect_uri)
            id_token = token_data.get('id_token') or token_data.get('access_token')
            if not id_token:
                return _json_response({'success': False, 'error': 'No token in provider response.'}, 502)
            from odoo.addons.bamboo_abp_auth.models.ir_http import IrHttp
            user, claims = IrHttp._validate_and_provision(id_token)
        except Exception as exc:
            _logger.error('bamboo_abp_auth: SPA token exchange failed: %s', exc)
            return _json_response({'success': False, 'error': str(exc)}, 500)

        access_token = token_data.get('access_token') or id_token
        return _json_response({
            'success': True,
            'data': {
                'access_token': access_token,
                'id_token': token_data.get('id_token', ''),
                'token_type': token_data.get('token_type', 'Bearer'),
                'expires_in': token_data.get('expires_in', 0),
                'uid': user.id,
                'user': {
                    'id': user.id,
                    'login': user.login,
                    'name': user.name,
                    'email': user.email,
                },
            },
        })

    @http.route('/api/v1/auth/logout', type='json', auth='user', methods=['POST'], csrf=False)
    def logout(self, **kwargs):
        """Invalidate the current Odoo session."""
        request.session.logout(keep_db=True)
        return {'success': True}
