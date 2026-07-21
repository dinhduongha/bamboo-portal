# -*- coding: utf-8 -*-
{
    'name': 'Bamboo Public API - FastAPI',
    'summary': 'Optional FastAPI implementation of the Bamboo public API (Odoo 19 only)',
    # Seriesless on purpose: adapt_version() yields 19.0.x on v19 and 18.0.x on v18,
    # so the manifest stays load-valid in BOTH worktrees. Odoo 18 rejects an explicit
    # 19.0.x string outright. The real v18 guard is the missing `fastapi` dependency,
    # which makes this module uninstallable on 18 (never breaks module loading).
    'version': '1.0.0',
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
