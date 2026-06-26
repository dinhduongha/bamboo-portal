import logging

import werkzeug

import odoo.http as http
from odoo.http import Response, CORS_MAX_AGE

_logger = logging.getLogger(__name__)

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
    if origin:
        set_header = self.request.future_response.headers.set
        set_header('Access-Control-Allow-Origin', origin)
        set_header('Access-Control-Allow-Credentials', 'true')
        set_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        # Reflect whatever headers the client asks for (so custom headers like
        # X-Odoo-Database pass), falling back to a static list that includes it.
        requested = self.request.httprequest.headers.get(
            'Access-Control-Request-Headers'
        )
        set_header(
            'Access-Control-Allow-Headers',
            requested or _FALLBACK_ALLOW_HEADERS,
        )
        if self.request.httprequest.method == 'OPTIONS':
            set_header('Access-Control-Max-Age', CORS_MAX_AGE)
            werkzeug.exceptions.abort(Response(status=204))
    return _original_pre_dispatch(self, rule, args)


http.Dispatcher.pre_dispatch = _cors_pre_dispatch

_original_call = http.Application.__call__


def _cors_call(self, environ, start_response):
    origin = environ.get('HTTP_ORIGIN')

    if environ.get('REQUEST_METHOD') == 'OPTIONS':
        if origin:
            requested = environ.get('HTTP_ACCESS_CONTROL_REQUEST_HEADERS')
            headers = [
                ('Access-Control-Allow-Origin', origin),
                ('Access-Control-Allow-Credentials', 'true'),
                ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
                ('Access-Control-Allow-Headers',
                 requested or _FALLBACK_ALLOW_HEADERS),
                ('Access-Control-Max-Age', str(CORS_MAX_AGE)),
                ('Content-Length', '0'),
            ]
            start_response('204 NO CONTENT', headers)
            return []
        return _original_call(self, environ, start_response)

    if not origin:
        return _original_call(self, environ, start_response)

    def _start_response(status, headers, exc_info=None):
        headers = [
            (k, v) for k, v in headers
            if k.lower() not in ('access-control-allow-origin', 'access-control-allow-credentials')
        ]
        headers.append(('Access-Control-Allow-Origin', origin))
        headers.append(('Access-Control-Allow-Credentials', 'true'))
        return start_response(status, headers, exc_info)

    return _original_call(self, environ, _start_response)


http.Application.__call__ = _cors_call

_logger.info("bamboo_cors: CORS headers enabled for all routes (dev mode)")
