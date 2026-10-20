"""Reusable HTTPS client; CLI sessions use ChatEnv's private TokenStore."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request

from chatenv.tokens import TokenStore
from .hosting_archive import HostingError, make_archive, valid_slug


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HostingClient:
    def __init__(self, url, token=None):
        parsed = urlsplit(url)
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in {'', '/'}):
            raise HostingError(400, 'Server URL must be an HTTPS origin')
        if parsed.scheme == 'http' and parsed.hostname not in {'localhost', '127.0.0.1', '::1'}:
            raise HostingError(400, 'Remote hosting requires HTTPS')
        self.url = url.rstrip('/')
        self.token = token
        self.opener = build_opener(NoRedirect())

    def request(self, path, *, payload=None, data=None, method='GET'):
        headers = {'Accept': 'application/json', 'Origin': self.url, 'X-ChatSite-Client': 'cli'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        if payload is not None:
            data = json.dumps(payload).encode()
            headers['Content-Type'] = 'application/json'
        elif data is not None:
            headers['Content-Type'] = 'application/zip'
        try:
            with self.opener.open(Request(self.url + '/api/hosting' + path, data=data, headers=headers, method=method), timeout=45) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise HostingError(413, 'Hosting response exceeds the client limit')
                return json.loads(raw)
        except HTTPError as exc:
            # Do not echo server bodies: an upstream response can contain credentials.
            raise HostingError(exc.code, f'Hosting request rejected (HTTP {exc.code})') from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise HostingError(502, 'Could not reach the hosting server') from None

    def login(self, username, password):
        result = self.request('/login', payload={'username': username, 'password': password}, method='POST')
        self.token = result['token']
        return result

    def upload(self, slug, directory):
        valid_slug(slug)
        return self.request(f'/sites/{slug}/releases', data=make_archive(Path(directory)), method='POST')

    def publish(self, slug, release, *, rollback=False):
        valid_slug(slug)
        return self.request(f'/sites/{slug}/' + ('rollback' if rollback else 'publish'), payload={'release': release}, method='POST')

    @classmethod
    def from_profile(cls, profile='default', *, home=None):
        values = TokenStore(home=home).read('ChatSite', profile).get('values', {})
        if not values.get('url') or not values.get('token'):
            raise HostingError(401, 'Run chatsite hosting login first for this profile')
        return cls(values['url'], values['token'])

    def save(self, profile='default', *, home=None):
        return TokenStore(home=home).write('ChatSite', profile, values={'url': self.url, 'token': self.token}, token_type='session', source='chatsite-hosting-login', summary={'url': self.url})
