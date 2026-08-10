"""Generic ORM RPC served by the FastAPI app.

Two transports, both mirroring an Odoo core route so an existing client only has
to change the base path:

    POST /fastapi/v1/dataset/call_kw/<model>/<method>   ← /web/dataset/call_kw
    POST /fastapi/v1/json2/<model>/<method>             ← /json/2/<model>/<method>

`json2` is Odoo 19+ only (it is the FastAPI equivalent of core's `rpc` addon,
which does not exist on 18); `call_kw` is served on both branches. The path
segment is `json2`, not `json/2`, so it stays a single mount point inside the app.

Neither route is enveloped: `call_kw` speaks JSON-RPC and `json2` returns the raw
value, exactly as the core routes do — the `{success, data, error, meta}` wrapper
belongs to the public API under `/fastapi/v1/public` only.

Dispatch itself is core's, not ours: `get_public_method` is the private-method /
`@api.private` guard, and `call_kw` resolves `@api.model` vs recordset calling
convention. ACLs and record rules are enforced inside the ORM as usual. What this
module adds is the transport and the identity, nothing about *what* may be called.

Two deliberate differences from core:

* No read-only cursor routing. Core picks one from `method._readonly`
  (`_call_kw_readonly`); the OCA route this app is mounted on is registered once,
  as `type="fastapi"`, so there is no per-call hook to do that. Every call runs
  on a read/write cursor.
* Core's `/json/2` authenticates with `auth='bearer'` (an `res.users.apikeys`
  key). Here an API key still works, but so do the bamboo JWT and the session
  cookie, because those are what this deployment's clients carry.
"""

import inspect
import json
import logging
from typing import Annotated, Any, Dict, Optional

import werkzeug.exceptions
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from odoo import release
from odoo.api import Environment
from odoo.exceptions import UserError
from odoo.http import SessionExpiredException, serialize_exception
from odoo.http import request as odoo_request
from odoo.models import BaseModel
from odoo.service.model import get_public_method
from odoo.tools import json_default

from ._common import current_user
from ..dependencies import authenticated_odoo_env

try:  # Odoo 19 moved call_kw next to get_public_method (and it guards internally).
    from odoo.service.model import call_kw
except ImportError:  # Odoo 18
    from odoo.api import call_kw

_logger = logging.getLogger(__name__)

# JSON-RPC "error.code" is arbitrary and ignored by clients, but the two branches
# emit a different default and the parity tests compare bodies.
_JSONRPC_BASE_CODE = 0 if release.version_info[0] >= 19 else 200


def _json_response(payload: Any, status_code: int = 200) -> Response:
    """`request.make_json_response`'s encoder, as a FastAPI response.

    Not `JSONResponse`: ORM results routinely contain `date`/`datetime`/`bytes`,
    which plain `json.dumps` refuses and `json_default` handles the way every
    other Odoo endpoint does.
    """
    return Response(
        content=json.dumps(payload, ensure_ascii=False, default=json_default),
        status_code=status_code,
        media_type="application/json; charset=utf-8",
    )


def _apikey_uid(env: Environment) -> Optional[int]:
    """The uid behind an `Authorization: Bearer <odoo-api-key>`, or None.

    Core's `_auth_method_bearer` does this for `/json/2`. It runs too late for us
    (the FastAPI app is mounted on an `auth='public'` route), so an API key that
    core would accept arrives here as the public user unless we check it too.
    """
    header = ""
    try:
        header = odoo_request.httprequest.headers.get("Authorization") or ""
    except Exception:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        return env["res.users.apikeys"].sudo()._check_credentials(scope="rpc", key=token) or None
    except Exception:
        return None


def rpc_env(
    env: Annotated[Environment, Depends(authenticated_odoo_env)],
) -> Environment:
    """Identity for the RPC routes: bamboo JWT / ABP / session, else an API key.

    Anonymous callers are refused outright. The ORM would block most of what the
    public user can reach anyway, but "any model, any public method" is not a
    surface to leave open to an unauthenticated request — core gates the same
    thing behind `auth='user'` / `auth='bearer'`.
    """
    if current_user(env) is None:
        uid = _apikey_uid(env)
        if uid:
            env = env(user=uid)
    if current_user(env) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required, use a Bearer token or an API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return env


RpcEnv = Annotated[Environment, Depends(rpc_env)]


async def _json_body(request: Request) -> Dict[str, Any]:
    """Parse the request body, or raise the same errors core's dispatchers do."""
    if (request.headers.get("content-type") or "").partition(";")[0].strip() != "application/json":
        raise werkzeug.exceptions.UnsupportedMediaType(
            "Content-Type must be application/json"
        )
    raw = await request.body()
    if not raw:
        return {}
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise werkzeug.exceptions.BadRequest(
            "could not parse the body as json: %s" % exc.args[0]
        ) from exc
    if not isinstance(body, dict):
        raise werkzeug.exceptions.BadRequest("the body must be a json object")
    return body


# --- /dataset/call_kw -------------------------------------------------------

call_kw_router = APIRouter(tags=["RPC"])


@call_kw_router.post(
    "/dataset/call_kw/{model}/{method}",
    responses={401: {"description": "No valid Bearer token, API key or session"}},
)
async def dataset_call_kw(model: str, method: str, request: Request, env: RpcEnv):
    """`/web/dataset/call_kw/<model>/<method>` over the FastAPI app.

    Unlike core, the path segments are authoritative — core accepts the bare
    `/web/dataset/call_kw` and reads the model from the body, which makes the URL
    useless for logs, ACLs and rate limits. `params.model`/`params.method` may
    still be sent (the existing client does), they just have to agree.
    """
    body = await _json_body(request)
    params = body.get("params") or {}
    if not isinstance(params, dict):
        raise HTTPException(status_code=422, detail="'params' must be an object")

    for key, path_value in (("model", model), ("method", method)):
        sent = params.get(key)
        if sent is not None and sent != path_value:
            raise HTTPException(
                status_code=422,
                detail="params.%s (%r) does not match the path (%r)" % (key, sent, path_value),
            )

    args = params.get("args") or []
    kwargs = params.get("kwargs") or {}
    request_id = body.get("id")

    try:
        with env.cr.savepoint():
            recs = env[model]
            get_public_method(recs, method)  # 18's call_kw does not guard by itself
            result = call_kw(recs, method, args, kwargs)
    except Exception as exc:  # noqa: BLE001 — every failure is a JSON-RPC error body
        return _json_response(_jsonrpc_error(exc, request_id))
    return _json_response({"jsonrpc": "2.0", "id": request_id, "result": result})


def _jsonrpc_error(exc: Exception, request_id: Any) -> Dict[str, Any]:
    """`JsonRPCDispatcher.handle_error`'s body — HTTP 200 with the error inside."""
    error = {
        "code": _JSONRPC_BASE_CODE,
        "message": "Odoo Server Error",
        "data": serialize_exception(exc),
    }
    if isinstance(exc, (KeyError, werkzeug.exceptions.NotFound)):
        error["code"] = 404
        error["message"] = "404: Not Found"
    elif isinstance(exc, SessionExpiredException):
        error["code"] = 100
        error["message"] = "Odoo Session Expired"
    else:
        _logger.info("bamboo rpc call_kw failed", exc_info=True)
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


# --- /json2 (Odoo 19+) ------------------------------------------------------

json2_router = APIRouter(tags=["RPC"])


@json2_router.post(
    "/json2/{model}/{method}",
    responses={401: {"description": "No valid Bearer token, API key or session"}},
)
async def json2_rpc(model: str, method: str, request: Request, env: RpcEnv):
    """Behavioural equivalent of core `POST /json/2/<model>/<method>`.

    Body: `{"ids": [...], "context": {...}, <named method arguments>}`. There is no
    positional `args` list — arguments are bound by name, which is what makes this
    the documented external API rather than an RPC wire format.
    """
    try:
        body = await _json_body(request)
        kwargs = dict(body)
        ids = kwargs.pop("ids", ())
        context = kwargs.pop("context", {})
        if not isinstance(ids, (list, tuple)):
            raise werkzeug.exceptions.UnprocessableEntity("'ids' must be a list")
        if not isinstance(context, dict):
            raise werkzeug.exceptions.UnprocessableEntity("'context' must be an object")

        with env.cr.savepoint():
            # Core replaces the context wholesale (`with_context(context)`); so do
            # we, except for `allowed_company_ids` — `authenticated_odoo_env`
            # computes it from the caller's own companies, and dropping it makes
            # every multi-company read pick the alphabetically-first company.
            ctx = dict(context)
            allowed = env.context.get("allowed_company_ids")
            if allowed and "allowed_company_ids" not in ctx:
                ctx["allowed_company_ids"] = allowed
            try:
                Model = env[model].with_context(ctx)
            except KeyError as exc:
                raise werkzeug.exceptions.NotFound(
                    "the model %r does not exist" % model
                ) from exc
            try:
                func = get_public_method(Model, method)
            except AttributeError as exc:
                raise werkzeug.exceptions.NotFound(exc.args[0]) from exc
            if getattr(func, "_api_model", False) and ids:
                raise werkzeug.exceptions.UnprocessableEntity(
                    "cannot call %s.%s with ids" % (model, method)
                )

            records = Model.browse(ids)
            try:
                inspect.signature(func).bind(records, **kwargs)
            except TypeError as exc:
                raise werkzeug.exceptions.UnprocessableEntity(exc.args[0]) from exc

            result = func(records, **kwargs)
            if isinstance(result, BaseModel):
                result = result.ids
    except Exception as exc:  # noqa: BLE001 — mirrors Json2Dispatcher.handle_error
        status_code, payload = _json2_error(exc)
        return _json_response(payload, status_code)
    return _json_response(result)


def _json2_error(exc: Exception):
    """`Json2Dispatcher.handle_error`: the real status code, `serialize_exception`
    as the body — no envelope, no JSON-RPC wrapper."""
    if isinstance(exc, (UserError, SessionExpiredException)):
        status_code = getattr(exc, "http_status", 400)
    elif isinstance(exc, werkzeug.exceptions.HTTPException):
        status_code = exc.code
    else:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        _logger.info("bamboo rpc json2 failed", exc_info=True)
    return status_code, serialize_exception(exc)


@json2_router.api_route(
    "/json2",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    include_in_schema=False,
)
@json2_router.api_route(
    "/json2/{subpath:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    include_in_schema=False,
)
async def json2_404(subpath: str = ""):
    """Core's `web_json_2_404` — anything else under /json2 says what to call."""
    return _json_response(
        serialize_exception(
            werkzeug.exceptions.NotFound(
                "Did you mean POST /fastapi/v1/json2/<model>/<method>?"
            )
        ),
        status.HTTP_404_NOT_FOUND,
    )


def rpc_routers():
    """The RPC routers this Odoo version serves."""
    if release.version_info[0] >= 19:
        return [call_kw_router, json2_router]
    return [call_kw_router]
