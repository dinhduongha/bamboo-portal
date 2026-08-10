from odoo import fields, models

from ..routers import bamboo_routers


class FastapiEndpoint(models.Model):
    _inherit = "fastapi.endpoint"

    app = fields.Selection(
        selection_add=[("bamboo_public", "Bamboo Public API")],
        ondelete={"bamboo_public": "cascade"},
    )

    def _get_fastapi_routers(self):
        if self.app == "bamboo_public":
            return bamboo_routers()
        return super()._get_fastapi_routers()

    def _get_app_dependencies_overrides(self):
        """Let the Bearer token decide who the app answers as.

        `odoo_env` is replaced wholesale rather than wrapped: every existing
        router already depends on it, so one override makes the whole app
        identity-aware instead of each route opting in and the ones nobody
        remembered staying anonymous. See ../dependencies.py for why the token
        never reaches the app on its own.
        """
        overrides = super()._get_app_dependencies_overrides()
        if self.app != "bamboo_public":
            return overrides

        from odoo.addons.fastapi import dependencies as oca_deps

        from .. import dependencies as bamboo_deps

        overrides.update({
            oca_deps.odoo_env: bamboo_deps.authenticated_odoo_env,
            oca_deps.authenticated_partner_impl:
                bamboo_deps.authenticated_partner_impl,
            oca_deps.optionally_authenticated_partner_impl:
                bamboo_deps.optionally_authenticated_partner_impl,
        })
        return overrides


# Monkey-patch FastApiDispatcher so errors under the PUBLIC FastAPI root return
# the SAME {success, data, error, meta} envelope the controllers use (so the React
# client's `Envelope<T>` unwrap works identically in both modes).
#
# Scoped to FASTAPI_PUBLIC_ROOT, not the whole app: the RPC routes are siblings of
# it and must NOT be enveloped — `dataset/call_kw` answers with a JSON-RPC error
# body and `json2` with a bare `serialize_exception`, matching the core routes they
# mirror. Widening this prefix silently breaks both.
from odoo.addons.fastapi.fastapi_dispatcher import FastApiDispatcher  # noqa: E402
from odoo.addons.fastapi.error_handlers import (  # noqa: E402
    convert_exception_to_status_body,
)
from odoo.addons.bamboo_public_api.controllers.common import (  # noqa: E402
    FASTAPI_PUBLIC_ROOT,
)
from odoo.http import request  # noqa: E402

_original_handle_error = FastApiDispatcher.handle_error


def _bamboo_handle_error(self, exc):
    if request and request.httprequest and request.httprequest.path:
        path = request.httprequest.path
        if path == FASTAPI_PUBLIC_ROOT or path.startswith(FASTAPI_PUBLIC_ROOT + "/"):
            headers = getattr(exc, "headers", None)
            status_code, body = convert_exception_to_status_body(exc)
            detail = body.get("detail", "An error occurred")
            error = "Validation failed" if isinstance(detail, list) else str(detail)
            enveloped = {"success": False, "data": None, "error": error, "meta": {}}
            return self.request.make_json_response(
                enveloped, status=status_code, headers=headers
            )
    return _original_handle_error(self, exc)


FastApiDispatcher.handle_error = _bamboo_handle_error
