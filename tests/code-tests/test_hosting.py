import io
from pathlib import Path
import stat
import zipfile

import pytest
from chatlogin import AccessDenied, ManagedUsers

from chatsite.hosting import HostingStore, HostingError, make_archive


def archive(text):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr('index.html', text)
        z.writestr('assets/style.css', 'body{color:green}')
    return stream.getvalue()


@pytest.fixture
def setup(tmp_path):
    users = ManagedUsers.in_memory('hosting-test')
    owner = users.bootstrap_owner('owner@example.test', 'owner-password')
    actor = users.authenticate(owner.username, 'owner-password')
    member = users.create_user(actor, 'member@example.test', 'member-password')
    outsider = users.create_user(actor, 'outsider@example.test', 'other-password')
    store = HostingStore(tmp_path / 'hosting', users)
    yield store, actor, users.authenticate(member.username, 'member-password'), users.authenticate(outsider.username, 'other-password')
    users.close()


def test_two_sites_dev_promotion_rollback_and_acl(setup):
    store, owner, member, outsider = setup
    store.create_site(owner, 'first', 'First')
    store.create_site(owner, 'second', 'Second')
    store.grant(owner, 'second', member.user_id, 'publisher')
    first = store.upload(owner, 'first', archive('private-first'))
    store.publish(owner, 'first', first['id'])
    a = store.upload(member, 'second', archive('version-A'))
    with pytest.raises(HostingError) as absent:
        store.read_file(member, 'second', 'prod', 'index.html')
    assert absent.value.status == 404
    store.publish(member, 'second', a['id'])
    b = store.upload(member, 'second', archive('version-B'))
    assert store.read_file(member, 'second', 'dev', 'index.html')[0] == b'version-B'
    assert store.read_file(member, 'second', 'prod', 'index.html')[0] == b'version-A'
    store.publish(member, 'second', b['id'])
    store.publish(member, 'second', a['id'], rollback=True)
    assert store.read_file(member, 'second', 'prod', 'index.html')[0] == b'version-A'
    assert store.read_file(member, 'second', 'dev', 'index.html')[0] == b'version-B'
    for actor in [member, outsider]:
        with pytest.raises(AccessDenied):
            store.read_file(actor, 'first', 'prod', 'index.html')
        with pytest.raises(AccessDenied):
            store.upload(actor, 'first', archive('bad'))
    assert len(store.list_sites(outsider)) == 0
    assert len(store.list_sites(member)) == 1
    with pytest.raises(AccessDenied):
        store.create_site(member, 'unapproved', 'Bad')


def test_permissions_are_live_and_revocable(setup):
    store, owner, member, outsider = setup
    store.create_site(owner, 'demo', 'Demo')
    release = store.upload(owner, 'demo', archive('private'))
    store.publish(owner, 'demo', release['id'])
    store.grant(owner, 'demo', member.user_id, 'viewer')
    assert store.read_file(member, 'demo', 'prod', 'index.html')[0] == b'private'
    with pytest.raises(AccessDenied):
        store.upload(member, 'demo', archive('bad'))
    store.grant(owner, 'demo', member.user_id, 'none')
    with pytest.raises(AccessDenied):
        store.read_file(member, 'demo', 'prod', 'index.html')
    store.grant(owner, 'demo', outsider.user_id, 'publisher')
    store.users.update_user(owner, outsider.user_id, enabled=False)
    with pytest.raises(AccessDenied):
        store.upload(outsider, 'demo', archive('bad'))


@pytest.mark.parametrize('name', ['../outside', '/etc/passwd', 'assets/../../bad', 'a\\b', '.env', '.git/config', '.hg/store/data', '.svn/wc.db'])
def test_archive_and_path_boundary(setup, name):
    store, owner, *_ = setup
    store.create_site(owner, 'demo', 'Demo')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr('index.html', 'valid')
        z.writestr(name, 'forbidden')
    with pytest.raises(HostingError):
        store.upload(owner, 'demo', stream.getvalue())
    assert store.versions(owner, 'demo') == []


def test_symlink_rejected_and_alias_is_not_hardcoded(setup, tmp_path):
    store, owner, member, _ = setup
    store.create_site(owner, 'another', 'Another', alias='my-notes', trusted=True)
    assert store.resolve_alias('my-notes') == 'another'
    r = store.upload(owner, 'another', archive('A'))
    store.publish(owner, 'another', r['id'])
    assert store.read_file(owner, 'another', 'prod', '')[1]['trusted'] is True
    with pytest.raises(HostingError):
        store.read_file(owner, 'another', 'prod', '../../hosting.sqlite3')
    d = tmp_path / 'input'
    d.mkdir()
    (d / 'index.html').write_text('hello')
    (d / 'link').symlink_to('/etc/passwd')
    with pytest.raises(HostingError):
        make_archive(d)
