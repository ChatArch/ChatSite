"""ChatSite Hub integration for managed accounts and private static hosting."""
from __future__ import annotations

from dataclasses import asdict
import http.cookies
from importlib import resources
import json
import mimetypes
import os
from pathlib import Path
import re
from urllib.parse import quote, unquote, urlsplit

from chatlogin import AccessDenied, LoginRateLimiter, ManagedError, ManagedUsers, Role, require_csrf, safe_next
from chatlogin.ui import LoginUI

from .hosting import HostingError, HostingStore, MAX_ARCHIVE
from .web import WebError

COOKIE = 'chatsite_hosting_session'
INSTANCE = 'chatsite-hosting'


def user_payload(record):
    data = asdict(record)
    data['role'] = record.role.value
    return data


class HostingApp:
    def __init__(self, store, *, origin, native_owner=None):
        self.store, self.users = store, store.users
        self.origin = origin.rstrip('/')
        self.native_owner = native_owner
        self.limiter = LoginRateLimiter(limit=10, window=60)

    @classmethod
    def from_hub(cls, config):
        users = ManagedUsers.for_instance(INSTANCE, ttl=86400)
        owner = users.authenticate(config.admin_email, config.admin_password)
        if owner is not None and owner.role is not Role.OWNER:
            owner = None
        root = Path(os.getenv('CHATSITE_HOSTING_DATA_DIR') or config.data_dir / 'hosting')
        return cls(HostingStore(root, users), origin=config.public_url, native_owner=owner)


def decorate_handler(native_handler, app):
    class HostingHandler(native_handler):
        hosting = app

        def _dispatch(self, method):
            parsed = urlsplit(self.path)
            path = parsed.path
            managed = path == '/hosting' or path.startswith(('/hosting/', '/api/hosting/', '/sites/')) or path == '/api/hosting'
            alias = None
            if not managed:
                first = path.lstrip('/').split('/', 1)[0]
                alias = app.store.resolve_alias(first) if first else None
            if not managed and alias is None:
                return super()._dispatch(method)
            try:
                if method not in {'GET', 'HEAD'}:
                    # Retain native origin policy for all cookie and CLI writes.
                    self._check_origin(method)
                return self._hosting_dispatch(method, parsed, alias)
            except (AccessDenied, ManagedError, HostingError, WebError) as exc:
                status = getattr(exc, 'status_code', getattr(exc, 'status', 400))
                return self._json(status, {'error': 'hosting_error', 'message': str(exc)})
            except (ValueError, TypeError, KeyError):
                return self._json(400, {'error': 'invalid_request'})

        def _hosting_cookie(self):
            cookie = http.cookies.SimpleCookie()
            try:
                cookie.load(self.headers.get('Cookie', ''))
            except http.cookies.CookieError:
                return None
            value = cookie.get(COOKIE)
            return value.value if value else None

        def _hosting_auth(self, *, write=False):
            authorization = self.headers.get('Authorization', '')
            bearer = authorization.startswith('Bearer ')
            if write and not bearer:
                origins = self.headers.get_all('Origin', [])
                if len(origins) != 1 or origins[0].rstrip('/') not in self.config.allowed_origins:
                    raise AccessDenied(403, 'A permitted Origin is required for cookie writes')
            token = authorization[7:] if bearer else self._hosting_cookie()
            if token:
                session = app.users.sessions.resolve(token)
                if session is None:
                    raise AccessDenied(401, 'Sign in required')
                app.store.live(session.principal)
                if write and not bearer:
                    require_csrf(session, self.headers.get('X-CSRF-Token'))
                return session.principal, session.csrf_token
            # The original single-owner Hub session also opens the hosting console.
            native = self.auth.session_payload(self._session_token())
            if native is not None and app.native_owner is not None:
                app.store.live(app.native_owner)
                if write:
                    self.auth.require_write(self._session_token(), self.headers.get('X-CSRF-Token'))
                return app.native_owner, native['csrf_token']
            raise AccessDenied(401, 'Sign in required')

        def _hosting_bytes(self, code, data, content_type, *, extra=None, head=False):
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'private, no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Robots-Tag', 'noindex, nofollow')
            self.send_header('Referrer-Policy', 'same-origin')
            pairs = extra.items() if isinstance(extra, dict) else (extra or [])
            for key, value in pairs:
                self.send_header(key, value)
            self.end_headers()
            if not head:
                self.wfile.write(data)

        def _hosting_redirect(self, url):
            return self._hosting_bytes(303, b'', 'text/plain', extra={'Location': url})

        def _hosting_login(self):
            payload = self._read_json()
            username = payload.get('username', payload.get('email'))
            password = payload.get('password')
            if not isinstance(username, str) or not isinstance(password, str):
                raise HostingError(400, 'Account and password required')
            if not app.limiter.allow(self.client_address[0] + ':' + username[:80]):
                raise HostingError(429, 'Too many login attempts; retry later')
            principal = app.users.authenticate(username, password)
            if principal is None:
                raise AccessDenied(401, 'Account or password not accepted')
            prior = self._hosting_cookie()
            if prior and app.users.sessions.resolve(prior) is not None:
                require_csrf(app.users.sessions.resolve(prior), self.headers.get('X-CSRF-Token'))
            issued = app.users.sessions.issue(principal, previous_token=prior)
            data = {'authenticated': True, 'principal': principal.as_dict(), 'email': username,
                    'csrf_token': issued.session.csrf_token, 'next': safe_next(payload.get('next'), '/hosting/')}
            if self.headers.get('X-ChatSite-Client') == 'cli':
                data['token'] = issued.token
            cookie = http.cookies.SimpleCookie()
            cookie[COOKIE] = issued.token
            cookie[COOKIE]['path'] = '/'
            cookie[COOKIE]['httponly'] = True
            cookie[COOKIE]['samesite'] = 'Lax'
            cookie[COOKIE]['secure'] = app.origin.startswith('https://')
            cookies = [('Set-Cookie', cookie.output(header='').strip())]
            # Matching original-owner credentials also establish the native Hub
            # session needed by existing private extensions such as comments.
            # Other managed users/admins never receive legacy Hub access.
            if (self.headers.get('X-ChatSite-Client') != 'cli' and principal.role is Role.OWNER
                    and username.casefold() == self.config.admin_email.casefold()
                    and self.auth.backend.authenticate(self.config.admin_email, password) is not None):
                _, native_token = self.auth.login({'email': self.config.admin_email, 'password': password},
                                                  self._session_token(), None)
                cookies.append(('Set-Cookie', self._session_cookie(native_token)))
            return self._hosting_bytes(200, json.dumps(data).encode(), 'application/json; charset=utf-8',
                                       extra=cookies)

        def _hosting_dispatch(self, method, parsed, alias):
            path = parsed.path
            if path == '/api/hosting/register':
                raise AccessDenied(403, 'Public registration is closed; contact the administrator')
            if path == '/api/hosting/login' and method == 'POST':
                return self._hosting_login()
            if path == '/hosting/login' and method == 'GET':
                from urllib.parse import parse_qs
                next_url = (parse_qs(parsed.query).get('next') or ['/hosting/'])[0]
                context = {'login_url': '/api/hosting/login', 'session_url': '/hosting/login/session',
                           'logout_url': '/api/hosting/logout', 'assets_path': '/login/assets',
                           'next': safe_next(next_url, '/hosting/')}
                html = LoginUI(title='ChatSite 托管', subtitle='仅限管理员开通的账号。', guest_url=None).render(context)
                return self._hosting_bytes(200, html.encode(), 'text/html; charset=utf-8')
            if path == '/hosting/login/session' and method == 'GET':
                try:
                    actor, csrf = self._hosting_auth()
                    return self._json(200, {'authenticated': True, 'principal': actor.as_dict(), 'csrf_token': csrf})
                except AccessDenied:
                    return self._json(200, {'authenticated': False})
            if path.startswith('/hosting/assets/') and method in {'GET', 'HEAD'}:
                name = path.removeprefix('/hosting/assets/')
                if name not in {'hosting.css', 'hosting.js'}:
                    raise HostingError(404, 'Asset not found')
                data = resources.files('chatsite').joinpath('hosting_static', name).read_bytes()
                return self._hosting_bytes(200, data, mimetypes.guess_type(name)[0], head=method == 'HEAD')
            if path in {'/hosting', '/hosting/'} and method in {'GET', 'HEAD'}:
                try:
                    self._hosting_auth()
                except AccessDenied as exc:
                    if exc.status_code == 401:
                        return self._hosting_redirect('/hosting/login?next=%2Fhosting%2F')
                    raise
                if path == '/hosting':
                    return self._hosting_redirect('/hosting/')
                data = resources.files('chatsite').joinpath('hosting_static', 'index.html').read_bytes()
                return self._hosting_bytes(200, data, 'text/html; charset=utf-8', head=method == 'HEAD')
            if path.startswith('/api/hosting/'):
                actor, csrf = self._hosting_auth(write=method not in {'GET', 'HEAD'})
                if path == '/api/hosting/session' and method == 'GET':
                    return self._json(200, {'authenticated': True, 'principal': actor.as_dict(), 'username': app.users.current_user(actor).username, 'csrf_token': csrf})
                if path == '/api/hosting/logout' and method == 'POST':
                    token = self.headers.get('Authorization', '').removeprefix('Bearer ') or self._hosting_cookie()
                    if token:
                        app.users.sessions.revoke(token)
                    native_token = self._session_token()
                    if native_token:
                        self.auth.sessions.revoke(native_token)
                    return self._hosting_bytes(200, b'{"ok":true}', 'application/json', extra=[
                        ('Set-Cookie', self._expired_session_cookie()),
                        ('Set-Cookie', COOKIE + '=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax')])
                if path == '/api/hosting/users':
                    app.store.admin(actor)
                    if method == 'GET':
                        from urllib.parse import parse_qs
                        offset = int((parse_qs(parsed.query).get('offset') or ['0'])[0])
                        return self._json(200, {'users': [user_payload(r) for r in app.users.list_users(actor, offset=offset)]})
                    if method == 'POST':
                        p = self._read_json()
                        record = app.users.create_user(actor, p['username'], p['password'], role=p.get('role', 'user'), display_name=p.get('display_name', ''))
                        return self._json(201, user_payload(record))
                if match := re.fullmatch(r'/api/hosting/users/([0-9a-f]{32})', path):
                    app.store.admin(actor)
                    if method == 'POST':
                        p = self._read_json()
                        return self._json(200, user_payload(app.users.update_user(actor, match[1], enabled=p['enabled'])))
                if path == '/api/hosting/sites':
                    if method == 'GET':
                        return self._json(200, {'sites': app.store.list_sites(actor)})
                    if method == 'POST':
                        p = self._read_json()
                        return self._json(201, app.store.create_site(actor, p['slug'], p.get('title', p['slug']), owner=p.get('owner'), alias=p.get('alias'), trusted=p.get('trusted', False)))
                if match := re.fullmatch(r'/api/hosting/sites/([a-z0-9-]+)(?:/(releases|publish|rollback|grants))?', path):
                    slug, action = match.groups()
                    if action is None and method == 'GET':
                        return self._json(200, app.store.site(actor, slug))
                    if action == 'releases' and method == 'GET':
                        releases = app.store.versions(actor, slug)
                        return self._json(200, {'releases': [{k: v for k, v in r.items() if k != 'manifest'} for r in releases]})
                    if action == 'releases' and method == 'POST':
                        app.store.check(actor, slug, 'publisher')
                        length = int(self.headers.get('Content-Length', '0'))
                        if self.headers.get('Transfer-Encoding') or not 0 < length <= MAX_ARCHIVE:
                            raise HostingError(413, 'Upload requires a bounded Content-Length')
                        if self.headers.get_content_type() != 'application/zip':
                            raise HostingError(415, 'Upload must be application/zip')
                        data = self.rfile.read(length)
                        if len(data) != length:
                            raise HostingError(400, 'Incomplete upload')
                        return self._json(201, app.store.upload(actor, slug, data))
                    if action in {'publish', 'rollback'} and method == 'POST':
                        p = self._read_json()
                        return self._json(200, app.store.publish(actor, slug, p['release'], rollback=action == 'rollback'))
                    if action == 'grants' and method == 'POST':
                        p = self._read_json()
                        return self._json(200, app.store.grant(actor, slug, p['user_id'], p['role']))
                raise HostingError(404, 'Hosting API route not found')
            # All static files, including data/scripts, require current site permission.
            match = re.fullmatch(r'/sites/([a-z0-9-]+)/(dev|prod)(/.*)?', path)
            if alias:
                slug, environment = alias, 'prod'
                suffix = '/' + path.lstrip('/').partition('/')[2] if '/' in path.lstrip('/') else None
            elif match:
                slug, environment, suffix = match.groups()
            else:
                raise HostingError(404, 'Static site route not found')
            try:
                actor, _ = self._hosting_auth()
            except AccessDenied as exc:
                if exc.status_code == 401 and method in {'GET', 'HEAD'}:
                    return self._hosting_redirect('/hosting/login?next=' + quote(self.path, safe=''))
                raise
            if method not in {'GET', 'HEAD'}:
                raise HostingError(405, 'Static sites support GET and HEAD only')
            if suffix is None:
                return self._hosting_redirect(path + '/')
            name = unquote(suffix.lstrip('/')).rstrip('/')
            data, metadata = app.store.read_file(actor, slug, environment, name)
            if metadata['path'] != (name or 'index.html') and not path.endswith('/'):
                return self._hosting_redirect(path + '/')
            content_type = mimetypes.guess_type(metadata['path'])[0] or 'application/octet-stream'
            if content_type.startswith('text/') or content_type == 'application/javascript':
                content_type += '; charset=utf-8'
            policy = "object-src 'none'; base-uri 'self'; worker-src 'none'; frame-ancestors 'self'"
            if not metadata['trusted']:
                policy = "sandbox allow-scripts allow-downloads; object-src 'none'; base-uri 'none'; worker-src 'none'; frame-ancestors 'self'"
            return self._hosting_bytes(200, data, content_type, head=method == 'HEAD', extra={
                'Content-Security-Policy': policy, 'X-Hosting-Release': metadata['release']})

        def do_HEAD(self):
            return self._dispatch('HEAD')

    return HostingHandler
