"""Content-negotiation helpers so existing routes can also answer as a JSON API."""
from flask import request, jsonify


def wants_json():
    """True if the client is asking for JSON rather than an HTML page.

    Triggers on ?format=json, a JSON request body, or an Accept header that
    prefers application/json over text/html (including no Accept header at
    all, which is how most non-browser API clients — curl, requests, etc. —
    behave by default).

    A real browser page navigation (a <form> submit or link click) is always
    treated as wanting HTML, even if its Accept header is a bare "*/*" (common
    on mobile browsers/webviews) that would otherwise tie with application/json.
    Browsers mark these with Sec-Fetch-Mode: navigate; curl/requests/fetch never
    send that header, so it doesn't affect real API clients.
    """
    if request.path.startswith('/api/'):
        return True
    if request.args.get('format') == 'json':
        return True
    if request.is_json:
        return True
    if request.headers.get('Sec-Fetch-Mode') == 'navigate':
        return False
    return request.accept_mimetypes['application/json'] >= request.accept_mimetypes['text/html']


def api_ok(data=None, status=200, **extra):
    payload = {'success': True}
    if data is not None:
        payload['data'] = data
    payload.update(extra)
    return jsonify(payload), status


def api_error(message, status=400, **extra):
    payload = {'success': False, 'error': message}
    payload.update(extra)
    return jsonify(payload), status


def form_value(name, default=None, cast=None):
    """Read a request parameter from a JSON body (if sent) or form/query string,
    so the same endpoint accepts both an HTML form post and a JSON API call."""
    if request.is_json:
        value = (request.get_json(silent=True) or {}).get(name, default)
    else:
        value = request.values.get(name, default)
    if value is not None and cast is not None and not isinstance(value, cast):
        try:
            value = cast(value)
        except (TypeError, ValueError):
            return default
    return value


def form_list(name, cast=None):
    if request.is_json:
        values = (request.get_json(silent=True) or {}).get(name, []) or []
    else:
        values = request.form.getlist(name)
    if cast is not None:
        values = [cast(v) for v in values]
    return values
