{
    'name': 'Bamboo CORS',
    'version': '18.0.1.0.0',
    'category': 'Technical',
    'summary': 'Enable CORS headers for local Flutter Web dev clients',
    'description': """
Reflects the request Origin header back as Access-Control-Allow-Origin (with
credentials allowed) on every HTTP/JSON-RPC route, and answers OPTIONS
preflight requests with a 204. Intended for local development only.
""",
    'author': 'Bamboo',
    'depends': ['base'],
    'installable': True,
    'auto_install': False,
}
