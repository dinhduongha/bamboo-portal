# -*- coding: utf-8 -*-
{
    'name': 'Bamboo Public API - FastAPI',
    'summary': 'Optional FastAPI implementation of the Bamboo public API',
    # This is the v19.0 copy (bamboo-portal branch 19.0, mounted only on the v19
    # stack). It targets OCA fastapi 19.0 (19.0.1.0.2, from odoo19/addons-oca).
    # The v18.0 copy lives on branch 18.0 at version 18.0.x — kept as a separate
    # copy. Never merge this version line across branches.
    'version': '19.0.1.1.0',
    'license': 'LGPL-3',
    'author': 'dinhduongha@gmail.com',
    'website': "https://github.com/dinhduongha/bamboo-portal",
    'category': 'Technical',
    # Bridge module: optional everywhere, needs the OCA `fastapi` module (which
    # pulls in `endpoint_route_handler` itself, so it is not listed here).
    # bamboo_public_api works without it — the controllers are the default mode.
    'depends': ['bamboo_public_api', 'fastapi'],
    'external_dependencies': {
        'python': ['fastapi', 'a2wsgi', 'pydantic'],
    },
    'data': [
        'data/fastapi_endpoint_data.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'auto_install': False,
}
