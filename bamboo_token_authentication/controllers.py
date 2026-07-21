# -*- coding: utf-8 -*-
import logging
from odoo import http, api, release
from odoo.http import request
import time
from . import jwt_min as jwt


def make_error(message):
    return dict(success=False, error=message)


def _apply_cors(response):
    """Set credentialed CORS headers by **reflecting the request Origin**.

    `Access-Control-Allow-Credentials: true` (needed so the browser sends/stores
    the session cookie) forbids `Allow-Origin: *`, so we echo the caller's
    Origin. This intentionally accepts any localhost port (and file://, the
    Tauri/native origin, and the deployed domain) instead of a hardcoded
    `localhost:5173` — matching the global behaviour of `bamboo_cors`.
    """
    origin = request.httprequest.headers.get('Origin', '')
    if origin:
        response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['Access-Control-Allow-Headers'] = (
        'origin, x-csrftoken, content-type, accept, x-openerp-session-id, authorization'
    )
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, OPTIONS, DELETE, PATCH'
    return response


def _set_session_cookie(response):
    """Attach the Odoo session cookie so cookie-auth (the session path) works.

    Uses werkzeug's set_cookie (appends a proper Set-Cookie, never clobbers).
    SameSite=None + Secure are required for cross-origin use and imply HTTPS;
    max_age is aligned with the 90-day JWT so the two auth paths expire together.
    """
    response.set_cookie(
        'session_id',
        request.session.sid,
        max_age=90 * 24 * 3600,
        httponly=True,
        samesite='None',
        secure=True,
        path='/',
    )
    return response


class AuthTokenController(http.Controller):
    @http.route('/bamboo/v1/sign_in', type='http', auth='none', csrf=False, methods=['POST', 'OPTIONS'])
    def get_token(self, **args):
        import logging
        import json
        from werkzeug.wrappers import Response
        
        _logger = logging.getLogger(__name__)
        
        # Handle OPTIONS preflight requests
        if request.httprequest.method == 'OPTIONS':
            response = _apply_cors(Response(''))
            _logger.info('BAMBOO AUTH: Handled OPTIONS preflight for sign-in')
            return response

        # Parse JSON data from POST request
        try:
            data = json.loads(request.httprequest.get_data(as_text=True))
            # Frontend sends data directly, not wrapped in 'params'
            params = data if isinstance(data, dict) else {}
            _logger.info(f'Received data: {data}')
            _logger.info(f'Parsed params: {params}')
        except Exception as e:
            _logger.error(f'Failed to parse JSON data: {e}')
            response = Response(json.dumps(make_error('Invalid JSON data')), content_type='application/json')
            return _apply_cors(response)

        # Database: the X-Odoo-Database header is how this db-bound route is
        # reached under multi-db (the params/session are only fallbacks).
        db_name = (
            request.httprequest.headers.get('X-Odoo-Database')
            or params.get('db')
            or request.session.db
        )
        _logger.info(f'db_name extracted: {db_name}')

        if not db_name:
            response = Response(json.dumps(make_error('Database name is required')), content_type='application/json')
            return _apply_cors(response)

        # Default so the token block can reference it even if no config_id given.
        client_metadata = {}
        
        request.session.db = db_name
        _logger.info(f'Set session.db to: {request.session.db}')
        
        # Use Odoo's native password verification
        from odoo.modules import registry
        from odoo import SUPERUSER_ID
        
        try:
            _logger.info(f'NATIVE AUTH: Starting authentication for login: {params.get("login")}')
            
            # Use Odoo's native authentication system with correct parameters
            credential = {
                'type': 'password',
                'login': params.get('login'),
                'password': params.get('password')
            }
            # Session.authenticate signature differs by Odoo version: 18 takes
            # (db_name, credential); 19 takes (env, credential). For 19 mirror
            # Odoo's own /web/session/authenticate: authenticate against a fresh
            # anonymous Environment (uid=None) on the target db, not request.env
            # (which is bound to the public user and would reject valid creds).
            if release.version_info[0] >= 19:
                import odoo
                auth_env = odoo.api.Environment(request.env.cr, None, {})
                auth_info = request.session.authenticate(auth_env, credential)
            else:
                auth_info = request.session.authenticate(db_name, credential)
            user_id = auth_info.get('uid') if auth_info else None
            _logger.info(f'NATIVE AUTH: Authentication result - auth_info: {auth_info}, user_id: {user_id}')
            
            if user_id:
                _logger.info(f'NATIVE AUTH: Success - authenticated user ID: {user_id} in session: {request.session.sid}')

                # Optional feature metadata for the full-featured client (NOT
                # POS-only). Keyed by feature so new features add their own block
                # without another top-level field; POS lives under ['pos']. It is
                # attached to the single response built in the token block below
                # (do NOT build a throwaway response here — its Set-Cookie/headers
                # would be lost when that block rebuilds the response).
                config_id = params.get('config_id')
                if config_id:
                    try:
                        user = request.env.user
                        company = user.company_id

                        # Get POS config and sessions
                        pos_config_model = request.env['pos.config']
                        config = pos_config_model.browse(int(config_id))

                        if config and config.exists():
                            # Get current session for this config
                            session_model = request.env['pos.session']
                            current_session = session_model.search([
                                ('config_id', '=', config.id),
                                ('state', 'in', ['opening_control', 'opened'])
                            ], limit=1)

                            client_metadata['pos'] = {
                                'userContext': {
                                    'uid': user.id,
                                    'user_name': user.name,
                                    'company_id': company.id,
                                    'company_name': company.name,
                                    'lang': user.lang or 'en_US',
                                    'tz': user.tz or 'UTC'
                                },
                                'config': {
                                    'id': config.id,
                                    'name': config.name,
                                    'currency': config.currency_id.name if config.currency_id else None,
                                    'current_session_id': current_session.id if current_session else None,
                                    'current_session_state': current_session.state if current_session else None
                                }
                            }
                            _logger.info(f'BAMBOO AUTH: Added POS metadata for config_id: {config_id}')
                    except Exception as e:
                        _logger.error(f'Failed to get POS metadata: {e}')
                        # Don't fail auth if metadata fails, just log the error
            else:
                _logger.info(f'NATIVE AUTH: Failed - invalid credentials for {params.get("login")}')
                user_id = None
                    
        except Exception as e:
            _logger.error(f'Authentication system error: {e}', exc_info=True)
            user_id = None

        if user_id:
            # Session already set above, just proceed with token generation

            user = request.env['res.users'].sudo().browse(user_id)
            user._update_last_login()
            secret_key = request.env['ir.config_parameter'].sudo(
            ).get_param('database.secret')
            now = int(time.time())
            token = jwt.encode({
                'uid': user_id,
                'iat': now,
                'exp': now + 90 * 24 * 3600,
            }, secret_key, algorithm="HS256")
            response_data = {
                'success': True,
                # Top-level fields the Bamboo client reads directly.
                'user_id': user_id,
                'login': user.login,
                'access_token': token,
                'userContext': {
                    'lang': user.lang or 'en_US',
                    'tz': user.tz or 'UTC',
                    'company_id': user.company_id.id,
                    'company_name': user.company_id.name,
                },
                # General, feature-keyed metadata for the full-featured client.
                'metadata': client_metadata,
                # Kept for backward compatibility with older client builds.
                'pos_metadata': client_metadata.get('pos'),
                'data': {
                    'access_token': token,
                    'db_name': db_name,
                    'uid': user_id,
                    "name": user.name,
                    "username": user.login,
                },
            }

            # Single response: JSON body + credentialed CORS + the session cookie
            # (so BOTH the JWT and the cookie/session auth paths are usable).
            json_response = json.dumps(response_data)
            response = Response(json_response, content_type='application/json')
            _apply_cors(response)
            _set_session_cookie(response)
            _logger.info('BAMBOO AUTH: sign-in OK — returned access_token + session cookie')
            return response

        # Return error response with CORS headers
        response = Response(json.dumps(make_error('Incorrect login name or password')), content_type='application/json')
        _logger.info('BAMBOO AUTH: invalid credentials')
        return _apply_cors(response)
