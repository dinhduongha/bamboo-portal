from odoo import fields, models

from ..routers.blog import blog_router
from ..routers.courses import courses_router
from ..routers.health import health_router
from ..routers.meta import meta_router


class FastapiEndpoint(models.Model):
    _inherit = "fastapi.endpoint"

    app = fields.Selection(
        selection_add=[("bamboo_public", "Bamboo Public API")],
        ondelete={"bamboo_public": "cascade"},
    )

    def _get_fastapi_routers(self):
        if self.app == "bamboo_public":
            return [meta_router, health_router, courses_router, blog_router]
        return super()._get_fastapi_routers()


# Monkey-patch FastApiDispatcher so errors under the bamboo FastAPI root return
# the SAME {success, data, error, meta} envelope the controllers use (so the React
# client's `Envelope<T>` unwrap works identically in both modes).
from odoo.addons.fastapi.fastapi_dispatcher import FastApiDispatcher  # noqa: E402
from odoo.addons.fastapi.error_handlers import (  # noqa: E402
    convert_exception_to_status_body,
)
from odoo.addons.bamboo_public_api.controllers.common import FASTAPI_ROOT  # noqa: E402
from odoo.http import request  # noqa: E402

_original_handle_error = FastApiDispatcher.handle_error


def _bamboo_handle_error(self, exc):
    if request and request.httprequest and request.httprequest.path:
        path = request.httprequest.path
        if path == FASTAPI_ROOT or path.startswith(FASTAPI_ROOT + "/"):
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
