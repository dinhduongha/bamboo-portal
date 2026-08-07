import logging
import os

import werkzeug

import odoo.http as http
from odoo.http import Response, CORS_MAX_AGE
from odoo.tools import config

_logger = logging.getLogger(__name__)

# Every method Odoo routes can declare, so a client is never blocked by the
# preflight for using PUT/PATCH/DELETE on a custom controller.
_ALLOW_METHODS = 'GET, POST, PUT, PATCH, DELETE, OPTIONS, HEAD'


def _load_allowed_origins():
    """`bamboo_cors_allow_origins` from odoo.conf, else the env, else '*'.

    Resolved once at import: this module is loaded server-wide (so config is
    already parsed) and patches `Application.__call__`, which runs before any
    `env` exists — an ir.config_parameter lookup is impossible there, and would
    cost a query per request anyway. Changing the value needs a restart.

    Returns None for '*' — "reflect whatever Origin was sent", today's behaviour
    and the default.
    """
    raw = (config.get('bamboo_cors_allow_origins')
           or os.environ.get('BAMBOO_CORS_ALLOW_ORIGINS')
           or '*')
    raw = str(raw).strip()
    if raw == '*':
        return None
    return {o.strip().lower() for o in raw.split(',') if o.strip()}


_ALLOWED_ORIGINS = _load_allowed_origins()


def _allowed(origin):
    """Is this Origin allowed? Matched case-insensitively (scheme and host are
    case-insensitive per RFC 3986, and browsers do not always normalise)."""
    if not origin:
        return False
    return _ALLOWED_ORIGINS is None or origin.strip().lower() in _ALLOWED_ORIGINS

_original_is_cors_preflight = http.is_cors_preflight


def _is_cors_preflight(request, endpoint):
    if request.httprequest.method == 'OPTIONS':
        return True
    return _original_is_cors_preflight(request, endpoint)


http.is_cors_preflight = _is_cors_preflight

_original_pre_dispatch = http.Dispatcher.pre_dispatch


_FALLBACK_ALLOW_HEADERS = (
    'Origin, X-Requested-With, Content-Type, Accept, Authorization, Range, '
    'X-Odoo-Database'
)


def _cors_pre_dispatch(self, rule, args):
    origin = self.request.httprequest.headers.get('Origin')
    if _allowed(origin):
        set_header = self.request.future_response.headers.set
        # The echoed origin is the raw header, never the lowercased copy used for
        # matching: the browser compares it byte-for-byte with what it sent.
        set_header('access-control-allow-origin', origin)
        set_header('access-control-allow-credentials', 'true')
        set_header('access-control-allow-methods', _ALLOW_METHODS)
        # Reflect whatever headers the client asks for (so custom headers like
        # X-Odoo-Database pass), falling back to a static list that includes it.
        requested = self.request.httprequest.headers.get(
            'Access-Control-Request-Headers'
        )
        set_header(
            'access-control-allow-headers',
            requested or _FALLBACK_ALLOW_HEADERS,
        )
        if self.request.httprequest.method == 'OPTIONS':
            set_header('access-control-max-age', CORS_MAX_AGE)
            werkzeug.exceptions.abort(Response(status=204))
    return _original_pre_dispatch(self, rule, args)


http.Dispatcher.pre_dispatch = _cors_pre_dispatch

_original_call = http.Application.__call__


def _cors_call(self, environ, start_response):
    origin = environ.get('HTTP_ORIGIN')

    if environ.get('REQUEST_METHOD') == 'OPTIONS':
        if _allowed(origin):
            requested = environ.get('HTTP_ACCESS_CONTROL_REQUEST_HEADERS')
            headers = [
                ('access-control-allow-origin', origin),
                ('access-control-allow-credentials', 'true'),
                ('access-control-allow-methods', _ALLOW_METHODS),
                ('access-control-allow-headers',
                 requested or _FALLBACK_ALLOW_HEADERS),
                ('access-control-max-age', str(CORS_MAX_AGE)),
                ('content-length', '0'),
            ]
            start_response('204 NO CONTENT', headers)
            return []
        return _original_call(self, environ, start_response)

    if not _allowed(origin):
        return _original_call(self, environ, start_response)

    # Last word on the CORS headers, whoever else set them. `Request.
    # _inject_future_response` merges with `headers.extend()`, so a controller
    # that sets its own (bamboo_token_auth's sign_in does) would otherwise ship
    # two copies of the same header with two different values.
    requested = environ.get('HTTP_ACCESS_CONTROL_REQUEST_HEADERS')
    _owned = {
        'access-control-allow-origin': origin,
        'access-control-allow-credentials': 'true',
        'access-control-allow-methods': _ALLOW_METHODS,
        'access-control-allow-headers': requested or _FALLBACK_ALLOW_HEADERS,
    }

    def _start_response(status, headers, exc_info=None):
        headers = [(k, v) for k, v in headers if k.lower() not in _owned]
        headers.extend(_owned.items())
        return start_response(status, headers, exc_info)

    return _original_call(self, environ, _start_response)


http.Application.__call__ = _cors_call


# --- cross-origin db selection for plain <img>/asset requests ----------------
# On a multi-db server the db is chosen from the session cookie, the
# X-Odoo-Database header, or monodb. A cross-origin `<img src="/web/image/...">`
# can carry none of those (no cookie, no custom header) → "no database selected"
# 404. Let such requests name the db via a `?db=` query param (gated by the same
# db_filter as the header path, so no new exposure). The Bamboo client appends it
# to image URLs. Header/cookie paths are untouched.
from odoo.http import Request, db_filter

_original_get_session_and_dbname = Request._get_session_and_dbname

# The ?db= stateless db-selection exists ONLY for cross-origin asset/image reads
# (a bare <img>/<link> carries no cookie and no X-Odoo-Database header). It must NOT
# touch interactive routes (/web/login, /web, /odoo, /web/database/*): forcing
# session.can_save=False there drops the session cookie and breaks multi-db web login.
_STATELESS_DB_PATHS = ('/web/image', '/web/content', '/web/assets')


def _get_session_and_dbname_with_query(self):
    session, dbname = _original_get_session_and_dbname(self)
    if not dbname:
        qdb = self.httprequest.args.get('db')
        host = self.httprequest.environ.get('HTTP_HOST')
        path = self.httprequest.path or ''
        if qdb and path.startswith(_STATELESS_DB_PATHS) and db_filter([qdb], host=host):
            session.can_save = False  # stateless, like the header path
            session.db = qdb
            dbname = qdb
    return session, dbname


Request._get_session_and_dbname = _get_session_and_dbname_with_query

_logger.info(
    "bamboo_cors: CORS enabled on all routes, methods=[%s], origins=%s",
    _ALLOW_METHODS,
    "* (any Origin reflected)" if _ALLOWED_ORIGINS is None
    else ", ".join(sorted(_ALLOWED_ORIGINS)),
)
