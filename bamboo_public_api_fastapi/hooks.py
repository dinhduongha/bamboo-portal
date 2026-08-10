import logging

_logger = logging.getLogger(__name__)


def drop_oca_demo_endpoints(env):
    """Unregister OCA fastapi's demo app.

    The `fastapi` module ships two demo `fastapi.endpoint` records (`/fastapi_demo`
    and `/fastapi/demo-multi`). The second sits inside the `/fastapi` namespace this
    module owns, and neither belongs on a deployment. Dropping the records here
    rather than patching the vendored addon means an OCA update cannot bring them
    back — this hook runs again on every install/upgrade.
    """
    demo = env["fastapi.endpoint"].sudo().search([("app", "=", "demo")])
    if not demo:
        return
    paths = demo.mapped("root_path")
    demo.unlink()
    _logger.info("bamboo_public_api_fastapi: removed OCA fastapi demo endpoints %s", paths)


def sync_routes(env):
    """Register this module's FastAPI routes into the routing map.

    `fastapi.endpoint` route registration fires on write(), not on the XML `create`,
    so a fresh install — and any change of `root_path` — must sync explicitly (then
    the routes are live after the next worker/registry load).
    """
    endpoint = env.ref(
        "bamboo_public_api_fastapi.fastapi_endpoint_bamboo_public",
        raise_if_not_found=False,
    )
    if endpoint:
        endpoint.action_sync_registry()
        _logger.info(
            "bamboo_public_api_fastapi: FastAPI routes synced to registry at %s.",
            endpoint.root_path,
        )


def post_init_hook(env):
    drop_oca_demo_endpoints(env)
    sync_routes(env)
