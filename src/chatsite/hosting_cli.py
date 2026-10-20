"""Thin command adapters for the reusable hosting client and account bootstrap."""
import json
import os
import sys

import click
from chatstyle import ask_confirm, prompt_sensitive_value

from .hosting_archive import HostingError
from .hosting_client import HostingClient


def output(value):
    click.echo(json.dumps(value, ensure_ascii=False, indent=2))


def client(ctx):
    return HostingClient.from_profile(ctx.obj['hosting_profile'], home=ctx.obj['hosting_home'])


def boundary(function):
    import functools
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except HostingError as exc:
            raise click.ClickException(str(exc)) from None
    return wrapped


def password_value(key):
    if key:
        value = os.environ.get(key)
        if not value:
            raise click.ClickException('Password environment variable is missing or empty')
        return value
    if not sys.stdin.isatty():
        raise click.ClickException('Supply --password-env KEY for non-interactive use')
    value = prompt_sensitive_value('Password', None)
    if not value:
        raise click.ClickException('Password is required')
    return value


@click.group()
@click.option('--profile', default='default', show_default=True, help='Select a CLI session without changing other profiles.')
@click.option('--home', type=click.Path(file_okay=False), help='ChatArch home for profiles and sessions.')
@click.pass_context
def hosting(ctx, profile, home):
    """Upload dev sites, publish reviewed versions, and manage site access."""
    ctx.ensure_object(dict)
    ctx.obj.update(hosting_profile=profile, hosting_home=home)


@hosting.command()
@click.option('--url', required=True, help='Hosting HTTPS origin, e.g. https://chat.example.com')
@click.option('--username', required=True)
@click.option('--password-env', help='Name of the environment variable containing the password.')
@click.pass_context
@boundary
def login(ctx, url, username, password_env):
    """Sign in with an administrator-provisioned account; save a private session."""
    api = HostingClient(url)
    result = api.login(username, password_value(password_env))
    api.save(ctx.obj['hosting_profile'], home=ctx.obj['hosting_home'])
    output({'authenticated': True, 'url': api.url, 'principal': result['principal']})


@hosting.command()
@click.pass_context
@boundary
def logout(ctx):
    """Revoke this CLI session on the server."""
    output(client(ctx).request('/logout', payload={}, method='POST'))


@hosting.command('whoami')
@click.pass_context
@boundary
def whoami(ctx):
    """Show the current account without session or CSRF values."""
    output(client(ctx).request('/session')['principal'])


@hosting.command('sites')
@click.pass_context
@boundary
def sites(ctx):
    """List sites this account may read."""
    output(client(ctx).request('/sites'))


@hosting.command('create')
@click.argument('site')
@click.option('--title', default=None)
@click.option('--owner', help='Managed user id to grant publishing access.')
@click.option('--alias', help='Optional short production prefix, such as /my-notes/.')
@click.option('--trusted', is_flag=True, help='Administrator explicitly trusts site scripts with same-origin account access.')
@click.pass_context
@boundary
def create(ctx, site, title, owner, alias, trusted):
    """Administrator: register a private site, with isolated scripts by default."""
    output(client(ctx).request('/sites', payload={'slug': site, 'title': title or site, 'owner': owner, 'alias': alias, 'trusted': trusted}, method='POST'))


@hosting.command('upload')
@click.argument('site')
@click.argument('directory', type=click.Path(exists=True, file_okay=False))
@click.pass_context
@boundary
def upload(ctx, site, directory):
    """Upload a static directory to dev; production is unchanged."""
    output(client(ctx).upload(site, directory))


@hosting.command('versions')
@click.argument('site')
@click.pass_context
@boundary
def versions(ctx, site):
    """List immutable versions for a site."""
    from .hosting_archive import valid_slug
    valid_slug(site)
    output(client(ctx).request(f'/sites/{site}/releases'))


def confirmed(action, site, release, yes):
    if not yes and (not sys.stdin.isatty() or not ask_confirm(f'{action} {site}: {release}?', default=False)):
        raise click.ClickException('Explicit confirmation required; pass --yes after reviewing the version')


@hosting.command('publish')
@click.argument('site')
@click.option('--release', required=True, help='Exact version reviewed on dev.')
@click.option('--yes', is_flag=True, help='Confirm publication of this exact version.')
@click.pass_context
@boundary
def publish(ctx, site, release, yes):
    """Publish an explicitly selected version to production."""
    confirmed('Publish', site, release, yes)
    output(client(ctx).publish(site, release))


@hosting.command('rollback')
@click.argument('site')
@click.option('--release', required=True, help='Previously published version to restore.')
@click.option('--yes', is_flag=True)
@click.pass_context
@boundary
def rollback(ctx, site, release, yes):
    """Restore a previously published production version; dev is unchanged."""
    confirmed('Rollback', site, release, yes)
    output(client(ctx).publish(site, release, rollback=True))


@hosting.group('users')
def users():
    """Administrator account provisioning; public registration stays closed."""


@users.command('list')
@click.pass_context
@boundary
def list_users(ctx):
    """List safe account metadata."""
    output(client(ctx).request('/users'))


@users.command('create')
@click.argument('username')
@click.option('--password-env', help='Environment variable containing the initial password.')
@click.option('--role', type=click.Choice(['user', 'admin']), default='user')
@click.pass_context
@boundary
def create_user(ctx, username, password_env, role):
    """Create an account; the password is never printed or stored in the repository."""
    output(client(ctx).request('/users', payload={'username': username, 'password': password_value(password_env), 'role': role}, method='POST'))


@users.command('disable')
@click.argument('user_id')
@click.pass_context
@boundary
def disable_user(ctx, user_id):
    """Disable a user and revoke all of their hosting sessions."""
    if len(user_id) != 32 or any(c not in '0123456789abcdef' for c in user_id):
        raise click.ClickException('Invalid managed user id')
    output(client(ctx).request('/users/' + user_id, payload={'enabled': False}, method='POST'))


@hosting.command('grant')
@click.argument('site')
@click.option('--user-id', required=True)
@click.option('--role', type=click.Choice(['viewer', 'publisher', 'none']), required=True)
@click.pass_context
@boundary
def grant(ctx, site, user_id, role):
    """Administrator: grant or revoke access to one private site."""
    from .hosting_archive import valid_slug
    valid_slug(site)
    output(client(ctx).request(f'/sites/{site}/grants', payload={'user_id': user_id, 'role': role}, method='POST'))


@hosting.command('bootstrap')
@click.option('--username', required=True)
@click.option('--password-env', required=True, help='Environment variable containing the existing owner password.')
@click.pass_context
def bootstrap(ctx, username, password_env):
    """Server operator only: create the first hosting owner in an empty account directory."""
    from chatlogin import ManagedError, ManagedUsers
    from dataclasses import asdict
    INSTANCE = "chatsite-hosting"
    service = ManagedUsers.for_instance(INSTANCE, home=ctx.obj['hosting_home'])
    try:
        record = service.bootstrap_owner(username, password_value(password_env))
        output({**asdict(record), "role": record.role.value})
    except ManagedError as exc:
        raise click.ClickException(str(exc)) from None
    finally:
        service.close()
