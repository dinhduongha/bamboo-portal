{
    'name': 'Bamboo CORS',
    'version': '18.0.1.1.0',
    'category': 'Technical',
    'summary': 'CORS headers on every route, with a configurable origin allowlist',
    'description': """
Answers OPTIONS preflight with a 204 and sets credentialed CORS headers on every
HTTP/JSON-RPC route, for GET, POST, PUT, PATCH, DELETE, OPTIONS and HEAD.

The allowed origin is echoed back rather than `*`, because
`Access-Control-Allow-Credentials: true` forbids the wildcard. Which origins are
allowed is set by `bamboo_cors_allow_origins` in odoo.conf (or the
BAMBOO_CORS_ALLOW_ORIGINS environment variable):

    bamboo_cors_allow_origins = *                       ; default: reflect any Origin
    bamboo_cors_allow_origins = http://localhost:5173,https://app.example.com

Matching is case-insensitive; the value echoed back is the raw header the browser
sent. An origin that is not on the list gets no CORS headers at all and the
request is handled exactly as if this module were absent. The value is read once
at startup, so a change needs a server restart.
""",
    'author': 'Bamboo',
    'license': 'LGPL-3',
    'depends': ['base'],
    'installable': True,
    'auto_install': False,
}
