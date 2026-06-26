# -*- coding: utf-8 -*-
{
    'name': "Token Authentication",

    'summary': """
        Bamboo Token Authentication""",

    'description': """
        Bamboo Token Authentication
    """,

    'author': "Hieu Tran",
    'website': "https://www.fibotree.com",
    'category': 'Uncategorized',
    'version': '19.0.1.0',
    # `website` so this module loads AFTER it — our `_auth_method_public`
    # override must outrank website's in the ir.http MRO (so the Bearer token is
    # honoured on public routes, e.g. the mail edit/reaction controllers).
    'depends': ['base', 'website'],
    'license': 'LGPL-3',
    'data': [
    ],
    'demo': [
    ],
}
