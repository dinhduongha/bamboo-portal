{
    'name': 'Bamboo DMS - Omnichannel Social Commerce',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',
    'category': 'Supply Chain/Dms',
    'summary': 'Channel accounts, webhook identity and external order mapping',
    'description': """
        Sub-plan 18 of the DMS completion plan. 18A owns the three things
        plan 18 section 4 names as this plan's: the channel account with its
        secret reference, the external identity mapping, and the external
        order mapping keyed by (channel account, external order id).
    """,
    'author': 'dinhduongha@gmail.com',
    # Optional, like `dms_portal`: section 14 requires that a channel which is
    # not switched on adds nothing to the critical path or to core's
    # dependencies.
    'depends': [
        'dms',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/dms_omnichannel_security.xml',
        'data/dms_channel_retention.xml',
        'views/dms_omnichannel_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
