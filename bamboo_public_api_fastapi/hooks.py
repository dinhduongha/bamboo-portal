import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Register the FastAPI endpoint's routes into the routing map on install.
    The `fastapi.endpoint` route registration fires on write(), not on the XML
    `create`, so a fresh install must sync explicitly (then the routes are live
    after the next worker/registry load)."""
    endpoint = env.ref(
        "bamboo_public_api_fastapi.fastapi_endpoint_bamboo_public",
        raise_if_not_found=False,
    )
    if endpoint:
        endpoint.action_sync_registry()
        _logger.info("bamboo_public_api_fastapi: FastAPI routes synced to registry.")
