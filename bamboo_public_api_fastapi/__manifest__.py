# -*- coding: utf-8 -*-
{
    'name': 'Bamboo Public API - FastAPI',
    'summary': 'Optional FastAPI implementation of the Bamboo public API',
    # This is the v18.0 copy (bamboo-portal branch 18.0, mounted only on the v18
    # stack). It targets OCA fastapi 18.0 (18.0.1.3.4, from addons-oca/rest-framework).
    # The v19.0 copy lives on branch 19.0 (odoo19/addons) at version 19.0.x — kept as
    # a separate copy. Never merge this version line across branches.
    'version': '18.0.1.0.0',
    'license': 'LGPL-3',
    'author': 'Bamboo',
    'category': 'Website',
    # Bridge module: installed ONLY on Odoo 19 (needs the OCA `fastapi` module).
    # v18 laoone never installs it, so bamboo_public_api stays dual-support.
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
