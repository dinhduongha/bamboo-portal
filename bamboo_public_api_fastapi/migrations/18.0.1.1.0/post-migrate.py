"""Move the endpoint from /bamboo/fastapi/v1 to /fastapi/v1 and drop the OCA demo.

`root_path` itself is updated by the reloaded XML data, but OCA's
`endpoint.route.sync.mixin.write` only schedules a registry sync when
`registry_sync` is written — so without this the record points at the new path
while the registered werkzeug rule still matches the old one.
"""

from odoo import SUPERUSER_ID, api

from odoo.addons.bamboo_public_api_fastapi.hooks import (
    drop_oca_demo_endpoints,
    sync_routes,
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    drop_oca_demo_endpoints(env)
    sync_routes(env)
