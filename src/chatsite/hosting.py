"""Private static sites, immutable releases and explicit dev/prod promotion."""
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import stat
import time
import uuid
import zipfile
from chatlogin import AccessDenied, ManagedError, Role
from .hosting_archive import HostingError, MAX_ARCHIVE, MAX_EXPANDED, MAX_FILES, make_archive, safe_path, valid_slug


class HostingStore:
    def __init__(self, root: Path, users):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.users = users
        self.database = self.root / 'hosting.sqlite3'
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sites (
                  slug TEXT PRIMARY KEY, title TEXT NOT NULL, owner TEXT NOT NULL,
                  alias TEXT UNIQUE, trusted INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS grants (
                  slug TEXT NOT NULL REFERENCES sites(slug), user_id TEXT NOT NULL,
                  role TEXT NOT NULL CHECK(role IN ('viewer','publisher')),
                  PRIMARY KEY(slug,user_id));
                CREATE TABLE IF NOT EXISTS releases (
                  id TEXT PRIMARY KEY, slug TEXT NOT NULL REFERENCES sites(slug),
                  creator TEXT NOT NULL, created REAL NOT NULL, manifest TEXT NOT NULL,
                  digest TEXT NOT NULL, UNIQUE(slug,id));
                CREATE TABLE IF NOT EXISTS channels (
                  slug TEXT NOT NULL REFERENCES sites(slug), environment TEXT NOT NULL,
                  release TEXT NOT NULL REFERENCES releases(id), PRIMARY KEY(slug,environment));
                CREATE TABLE IF NOT EXISTS events (
                  id INTEGER PRIMARY KEY, slug TEXT NOT NULL, actor TEXT NOT NULL,
                  action TEXT NOT NULL, release TEXT, created REAL NOT NULL);
            ''')
        self.database.chmod(0o600)

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.database, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def live(self, actor):
        try:
            return self.users.current_user(actor)
        except (ManagedError, TypeError, AttributeError):
            raise AccessDenied(403, 'Account is not permitted') from None

    def admin(self, actor):
        record = self.live(actor)
        if record.role not in {Role.OWNER, Role.ADMIN}:
            raise AccessDenied(403, 'Administrator permission required')

    def _site(self, db, slug):
        valid_slug(slug)
        row = db.execute('SELECT * FROM sites WHERE slug=?', (slug,)).fetchone()
        if row is None:
            raise HostingError(404, 'Site not found')
        return dict(row)

    def _check(self, db, actor, slug, operation='viewer'):
        record = self.live(actor)
        site = self._site(db, slug)
        if record.role not in {Role.OWNER, Role.ADMIN}:
            row = db.execute('SELECT role FROM grants WHERE slug=? AND user_id=?', (slug, actor.user_id)).fetchone()
            if not row or (operation == 'publisher' and row['role'] != 'publisher'):
                raise AccessDenied(403, 'Site permission required')
        return site

    def check(self, actor, slug, operation='viewer'):
        with self.connection() as db:
            return self._check(db, actor, slug, operation)

    def create_site(self, actor, slug, title, *, owner=None, alias=None, trusted=False):
        self.admin(actor)
        valid_slug(slug)
        if not isinstance(title, str) or not 1 <= len(title) <= 160 or type(trusted) is not bool:
            raise HostingError(400, 'Invalid site settings')
        if alias is not None:
            valid_slug(alias)
        owner = actor.user_id if owner is None else owner
        if not self.users.get_user(actor, owner).enabled:
            raise HostingError(400, 'Site owner must be enabled')
        try:
            with self.connection(write=True) as db:
                db.execute('INSERT INTO sites VALUES(?,?,?,?,?,?)', (slug, title, owner, alias, int(trusted), time.time()))
                db.execute('INSERT INTO grants VALUES(?,?,?)', (slug, owner, 'publisher'))
                self._event(db, slug, actor, 'create', None)
        except sqlite3.IntegrityError:
            raise HostingError(409, 'Site or alias already exists') from None
        return self.site(actor, slug)

    def grant(self, actor, slug, user_id, role):
        self.admin(actor)
        if role not in {'viewer', 'publisher', 'none'}:
            raise HostingError(400, 'Invalid site role')
        self.users.get_user(actor, user_id)
        with self.connection(write=True) as db:
            self._site(db, slug)
            db.execute('DELETE FROM grants WHERE slug=? AND user_id=?', (slug, user_id))
            if role != 'none':
                db.execute('INSERT INTO grants VALUES(?,?,?)', (slug, user_id, role))
            self._event(db, slug, actor, 'grant:' + role, None)
        return {'site': slug, 'user_id': user_id, 'role': role}

    def site(self, actor, slug):
        with self.connection() as db:
            site = self._check(db, actor, slug)
            site['trusted'] = bool(site['trusted'])
            site['channels'] = {r['environment']: r['release'] for r in db.execute('SELECT * FROM channels WHERE slug=?', (slug,))}
            site['grants'] = [dict(r) for r in db.execute('SELECT user_id,role FROM grants WHERE slug=?', (slug,))]
            site['urls'] = {e: f'/sites/{slug}/{e}/' for e in ['dev', 'prod']}
            return site

    def list_sites(self, actor):
        record = self.live(actor)
        with self.connection() as db:
            if record.role in {Role.OWNER, Role.ADMIN}:
                slugs = [r[0] for r in db.execute('SELECT slug FROM sites ORDER BY slug LIMIT 1000')]
            else:
                slugs = [r[0] for r in db.execute('SELECT slug FROM grants WHERE user_id=? ORDER BY slug LIMIT 1000', (actor.user_id,))]
        return [self.site(actor, s) for s in slugs]

    def resolve_alias(self, alias):
        with self.connection() as db:
            row = db.execute('SELECT slug FROM sites WHERE alias=?', (alias,)).fetchone()
            return row[0] if row else None

    def upload(self, actor, slug, data):
        self.check(actor, slug, 'publisher')
        if not isinstance(data, bytes) or len(data) > MAX_ARCHIVE:
            raise HostingError(413, 'Archive exceeds the upload limit')
        release = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + uuid.uuid4().hex[:12]
        parent = self.root / 'sites' / slug / 'releases'
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        staging = parent / ('.' + release)
        final = parent / release
        staging.mkdir(mode=0o700)
        manifest = []
        names = set()
        total = 0
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if len(archive.infolist()) > MAX_FILES:
                    raise HostingError(413, 'Too many archive entries')
                for info in archive.infolist():
                    name = info.filename.rstrip('/') if info.is_dir() else info.filename
                    path = safe_path(name)
                    mode = info.external_attr >> 16
                    if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}):
                        raise HostingError(400, 'Archive contains a non-regular entry')
                    if name in names or info.flag_bits & 1:
                        raise HostingError(400, 'Archive contains duplicate or encrypted entries')
                    names.add(name)
                    if info.is_dir():
                        continue
                    total += info.file_size
                    if total > MAX_EXPANDED:
                        raise HostingError(413, 'Expanded archive exceeds the upload limit')
                    target = staging / str(path)
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    with archive.open(info) as source:
                        content = source.read(min(info.file_size + 1, MAX_EXPANDED + 1))
                    if len(content) != info.file_size:
                        raise HostingError(400, 'Archive size mismatch')
                    target.write_bytes(content)
                    target.chmod(0o600)
                    manifest.append({'path': name, 'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
            if not (staging / 'index.html').is_file():
                raise HostingError(400, 'Archive must contain index.html')
            manifest.sort(key=lambda item: item['path'])
            serialized = json.dumps(manifest, separators=(',', ':'), ensure_ascii=True)
            digest = hashlib.sha256(serialized.encode()).hexdigest()
            with self.connection(write=True) as db:
                self._check(db, actor, slug, 'publisher')
                if db.execute('SELECT count(*) FROM releases WHERE slug=?', (slug,)).fetchone()[0] >= 200:
                    raise HostingError(409, 'Release capacity reached; contact the administrator')
                staging.rename(final)
                db.execute('INSERT INTO releases VALUES(?,?,?,?,?,?)', (release, slug, actor.user_id, time.time(), serialized, digest))
                db.execute('INSERT INTO channels VALUES(?,?,?) ON CONFLICT(slug,environment) DO UPDATE SET release=excluded.release', (slug, 'dev', release))
                self._event(db, slug, actor, 'upload-dev', release)
            return {'id': release, 'site': slug, 'sha256': digest, 'files': len(manifest), 'bytes': total, 'dev_url': f'/sites/{slug}/dev/'}
        except (zipfile.BadZipFile, OSError, RuntimeError, ValueError) as exc:
            if isinstance(exc, HostingError):
                raise
            raise HostingError(400, 'Invalid static archive') from None
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def versions(self, actor, slug):
        with self.connection() as db:
            self._check(db, actor, slug)
            rows = db.execute('SELECT * FROM releases WHERE slug=? ORDER BY created DESC LIMIT 200', (slug,)).fetchall()
            return [{**dict(r), 'manifest': json.loads(r['manifest'])} for r in rows]

    def publish(self, actor, slug, release, *, rollback=False):
        with self.connection(write=True) as db:
            self._check(db, actor, slug, 'publisher')
            row = db.execute('SELECT * FROM releases WHERE id=? AND slug=?', (release, slug)).fetchone()
            if row is None:
                raise HostingError(404, 'Release not found in this site')
            if rollback and not db.execute("SELECT 1 FROM events WHERE slug=? AND release=? AND action IN ('publish','rollback')", (slug, release)).fetchone():
                raise HostingError(409, 'Rollback requires a previously published release')
            prior = db.execute("SELECT release FROM channels WHERE slug=? AND environment='prod'", (slug,)).fetchone()
            db.execute('INSERT INTO channels VALUES(?,?,?) ON CONFLICT(slug,environment) DO UPDATE SET release=excluded.release', (slug, 'prod', release))
            self._event(db, slug, actor, 'rollback' if rollback else 'publish', release)
            return {'site': slug, 'release': release, 'previous': prior[0] if prior else None, 'prod_url': f'/sites/{slug}/prod/'}

    def read_file(self, actor, slug, environment, name):
        if environment not in {'dev', 'prod'}:
            raise HostingError(404, 'Environment not found')
        path = safe_path(name or 'index.html')
        with self.connection() as db:
            site = self._check(db, actor, slug)
            row = db.execute('SELECT release FROM channels WHERE slug=? AND environment=?', (slug, environment)).fetchone()
            if row is None:
                raise HostingError(404, 'No release in this environment')
        root = self.root / 'sites' / slug / 'releases' / row['release']
        target = root / str(path)
        if target.is_dir():
            target = target / 'index.html'
        if not target.resolve().is_relative_to(root.resolve()) or not target.is_file():
            raise HostingError(404, 'Static file not found')
        return target.read_bytes(), {**site, 'trusted': bool(site['trusted']), 'release': row['release'], 'path': target.relative_to(root).as_posix()}

    @staticmethod
    def _event(db, slug, actor, action, release):
        db.execute('INSERT INTO events(slug,actor,action,release,created) VALUES(?,?,?,?,?)', (slug, actor.user_id, action, release, time.time()))
