"""File-based OneDrive mirror; active SQLite/WAL stays on the local disk."""
from __future__ import annotations
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _safe_component(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value or 'item'))
    value = re.sub(r'\s+', '_', value).strip(' ._')[:100]
    return value or 'item'


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')


def _atomic_write(path: Path, payload: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    try:
        with temporary.open('wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _write_if_changed(path: Path, payload: bytes):
    try:
        if path.is_file():
            with path.open('rb') as stream:
                existing = stream.read()
            if existing == payload:
                return False
            digest = hashlib.sha256(existing).hexdigest()[:12]
            conflict = path.with_name(path.stem + '.previous-' + digest + path.suffix)
            if not conflict.exists():
                _atomic_write(conflict, existing)
    except OSError:
        pass
    _atomic_write(path, payload)
    return True


class OneDriveMirror:
    """Versioned JSON backup plus readable per-project files, never a live SQLite copy."""
    def __init__(self, root=None):
        configured = root if root is not None else os.environ.get('WORKOS_SYNC_ROOT')
        self.root = Path(configured).expanduser() if isinstance(configured, (str, os.PathLike)) and str(configured).strip() else None
        if self.root is not None and not self.root.is_absolute():
            raise ValueError('WORKOS_SYNC_ROOT 必须是绝对路径')
        self._status = {'enabled': self.root is not None, 'last_sync': None,
                        'error': None, 'root_name': 'AI Agent/Local WorkOS' if self.root else None,
                        'active_sqlite_in_onedrive': False, 'workspaces': {}}

    def status(self):
        return {**self._status, 'workspaces': dict(self._status.get('workspaces', {}))}

    def _snapshot_path(self, workspace):
        return self.root / 'Sync' / ('workspace-' + workspace + '.json')

    def restore_if_empty(self, store, workspace):
        if self.root is None:
            return False
        snapshot_path = self._snapshot_path(workspace)
        if not snapshot_path.is_file():
            return False
        if any(store.list(collection) for collection in ('projects', 'tasks', 'documents', 'meetings', 'notes', 'deliverables')):
            return False
        with snapshot_path.open('r', encoding='utf-8') as stream:
            backup = json.load(stream)
        if not isinstance(backup, dict) or backup.get('format') != 'local-workos' or backup.get('workspace') != workspace:
            raise ValueError('OneDrive 快照格式或工作区不匹配；本机数据未修改')
        store.restore(backup, workspace)
        return True

    def sync(self, store, workspace):
        if self.root is None:
            return self.status()
        self.root.mkdir(parents=True, exist_ok=True)
        snapshot = store.backup(workspace)
        data = snapshot['data']
        digest = hashlib.sha256(_json_bytes(data)).hexdigest()
        manifest_path = self.root / 'manifest.json'
        try:
            with manifest_path.open('r', encoding='utf-8') as stream:
                manifest = json.load(stream)
        except (OSError, json.JSONDecodeError):
            manifest = {}
        if not isinstance(manifest, dict) or manifest.get('format') != 'Local WorkOS OneDrive mirror':
            manifest = {'format': 'Local WorkOS OneDrive mirror', 'schema_version': 1,
                        'workspace_hashes': {}, 'workspaces': {}, 'active_sqlite_in_onedrive': False}
        hashes = manifest.get('workspace_hashes')
        if not isinstance(hashes, dict):
            hashes = {}; manifest['workspace_hashes'] = hashes
        workspaces = manifest.get('workspaces')
        if not isinstance(workspaces, dict):
            workspaces = {}; manifest['workspaces'] = workspaces
        workspace_info = workspaces.get(workspace) if isinstance(workspaces.get(workspace), dict) else {}
        counts = {collection: len(items) for collection, items in data.items() if isinstance(items, list)}
        data_changed = hashes.get(workspace) != digest or not self._snapshot_path(workspace).is_file()
        snapshot_at = workspace_info.get('snapshot_at') if not data_changed else _utc_now()
        if not snapshot_at: snapshot_at = _utc_now()
        snapshot['exported_at'] = snapshot_at
        _write_if_changed(self._snapshot_path(workspace), _json_bytes(snapshot))
        if data_changed or not workspace_info:
            hashes[workspace] = digest
            workspace_info = {'updated_at': snapshot_at, 'snapshot_at': snapshot_at, 'counts': counts}
            workspaces[workspace] = workspace_info
        changed_files = 0
        if workspace == 'personal':
            projects = {item['id']: item for item in data.get('projects', []) if isinstance(item, dict) and item.get('id')}
            for project_id, project in projects.items():
                slug = _safe_component(project.get('name'))
                folder = self.root / 'Projects' / (project_id + '_' + slug)
                changed_files += _write_if_changed(folder / 'project.json', _json_bytes(project))
                for collection, subdir in (('meetings', 'Meetings'), ('tasks', 'Actions'), ('notes', 'Research'), ('deliverables', 'Outputs')):
                    for item in data.get(collection, []):
                        if isinstance(item, dict) and item.get('project_id') == project_id and item.get('id'):
                            name = _safe_component(item.get('title') or item.get('name') or collection)
                            payload = _json_bytes(item) if collection in ('meetings', 'tasks') else ('# ' + str(item.get('title') or name) + '\n\n' + str(item.get('body') or item.get('content') or '')).encode('utf-8')
                            suffix = '.json' if collection in ('meetings', 'tasks') else '.md'
                            changed_files += _write_if_changed(folder / subdir / (name + '__' + str(item['id']) + suffix), payload)
            for document in data.get('documents', []):
                if not isinstance(document, dict) or not document.get('id'):
                    continue
                project_id = document.get('project_id')
                if project_id in projects:
                    folder = self.root / 'Projects' / (project_id + '_' + _safe_component(projects[project_id].get('name'))) / 'Sources'
                else:
                    folder = self.root / 'Inbox' / 'Sources'
                doc_id = str(document['id'])
                title = _safe_component(document.get('title'))
                metadata = {key: document.get(key) for key in ('id', 'title', 'category', 'kind', 'source_ref', 'filename', 'hash', 'page_count', 'created_at', 'updated_at')}
                body = '# ' + str(document.get('title') or 'Imported source') + '\n\nSource: ' + str(document.get('source_ref') or document.get('filename') or '') + '\n\n' + str(document.get('content') or '')
                changed_files += _write_if_changed(folder / (title + '__' + doc_id + '.meta.json'), _json_bytes(metadata))
                changed_files += _write_if_changed(folder / (title + '__' + doc_id + '.md'), body.encode('utf-8'))
        manifest['active_sqlite_in_onedrive'] = False
        manifest['note'] = 'OneDrive stores project files and rebuildable JSON snapshots. Active SQLite/WAL remains local to avoid sync-lock corruption.'
        _write_if_changed(manifest_path, _json_bytes(manifest))
        last_sync = _utc_now()
        self._status.update({'enabled': True, 'last_sync': last_sync,
                             'error': None, 'root_name': 'AI Agent/Local WorkOS',
                             'active_sqlite_in_onedrive': False})
        self._status.setdefault('workspaces', {})[workspace] = {'last_sync': last_sync,
                                                                 'counts': counts, 'changed_files': changed_files}
        return self.status()
