{
    'name': 'Bamboo ABP Auth',
    'version': '18.0.1.0.0',
    'category': 'Technical',
    'summary': 'Standalone ABP AuthServer SSO: OIDC/JWT Bearer auth, params from odoo.conf (openid_*), tenant via res.company.tenant_uuid, roles via res.groups.role_code',
    'author': 'dinhduongha@gmail.com',
    'website': "https://github.com/dinhduongha/bamboo-portal",    
    'license': 'LGPL-3',
    'depends': ['auth_oauth'],
    'external_dependencies': {
        'python': ['PyJWT'],
    },
    'data': [
        'data/role_codes.xml',
        'views/res_users_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
