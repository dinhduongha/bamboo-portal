{
    'name': 'Bamboo DMS - B2B Self-Service Portal',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',
    'category': 'Supply Chain/Dms',
    'summary': 'Portal and Zalo Mini App self-service for Distributor and Outlet',
    'description': """
        Sub-plan 16 of the DMS completion plan. Identity and entitlement first;
        catalog, order, documents, returns and payment follow in 16B/16C/16D.
    """,
    'author': 'dinhduongha@gmail.com',
    # Plan 16 section 12: "Optional module can remain uninstalled without
    # breaking core DMS." That is only achievable from a SEPARATE addon --
    # putting `portal` into `dms`'s own depends would force every DMS install
    # to carry it. Master section 3 says the same thing from the other side:
    # "portal, website_sale, payment, delivery chi bat buoc khi bat B2B
    # self-service."
    #
    # `website_sale` and `payment` are NOT here yet. They arrive in 16B and
    # 16C, when a screen actually needs them.
    'depends': [
        'dms',
        'portal',
        # 16C: the payment framework, not a provider. Core Odoo ships no
        # Vietnamese provider (no VNPay, no MoMo), and the parts that matter
        # -- callback verification, deduplication, the transaction state
        # machine -- belong to `payment` itself.
        'payment',
        # 16D. Plan 16 section 5.1 forbids this plan from defining a second
        # staging model for external orders: the channel account and the
        # identity/order mappings belong to plan 18, and the self-service
        # flow REUSES them. That reuse is a dependency.
        'dms_omnichannel',
    ],
    'data': [
        # Security first, views after — same discipline as `dms`'s manifest.
        'security/ir.model.access.csv',
        'security/dms_portal_security.xml',
        'views/portal_templates.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
