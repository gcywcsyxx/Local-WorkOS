"""Versioned project outputs; runtime paths and bindings never belong in source.

Directory discovery reads names and metadata only. Business folders are used
only after a unique strong name match or an explicit confined binding.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import threading
import unicodedata
import uuid

FORMATS = {'html', 'docx', 'pptx', 'xlsx', 'md', 'txt', 'pdf'}
COLLECTIONS = {'deliverables', 'meetings', 'notes', 'documents'}
MAX_FILE_BYTES = 32_000_000
MAX_TOTAL_BYTES = 80_000_000
OUTPUT_FOLDER = 'WorkOS产物'
# Microsoft lists these Cloud Files tags (including the numbered variants) as
# sync-engine placeholders, without the NameSurrogate bit used by path links:
# https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fscc/c8e77b37-3909-4fe6-a4ea-2b9d423b1ee4
CLOUD_REPARSE_TAGS = frozenset(0x9000001A + (variant << 12) for variant in range(16))


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))


def _linked(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return True
    if not (getattr(info, 'st_file_attributes', 0) & 0x400):
        return False
    tag = getattr(info, 'st_reparse_tag', 0)
    # Allow only the exact known cloud-placeholder tags. Unknown reparse points,
    # junctions and symlinks stay blocked even when they occur beneath a root.
    return not (isinstance(tag, int) and not isinstance(tag, bool)
                and not (tag & 0x20000000) and tag in CLOUD_REPARSE_TAGS)


def _plain(path):
    """Reject links/junctions in every existing component before resolving."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('文件夹必须是没有上级跳转的绝对路径')
    for component in reversed((path, *path.parents)):
        try:
            if _linked(component):
                raise ValueError('路径包含链接或重解析点，未读写项目文件')
        except FileNotFoundError:
            continue
    return path.resolve(strict=False)


def _confined(base, target):
    base, target = _plain(base), _plain(target)
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError('文件路径超出允许的项目文件夹') from exc
    return target


def _mkdir(base, target):
    target = _confined(base, target)
    target.mkdir(parents=True, exist_ok=True)
    _confined(base, target)
    if not target.is_dir():
        raise ValueError('产物目标不是文件夹')
    return target


def _name(value, fallback='项目', limit=45):
    value = unicodedata.normalize('NFKC', str(value or ''))
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', value).strip(' .')[:limit].strip(' .')
    if not value or value in ('.', '..'):
        value = fallback
    if re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', value, re.I):
        value = '_' + value
    return value


def _project(project):
    if not isinstance(project, dict):
        raise ValueError('项目必须是记录对象')
    project_id = project.get('id') or ''
    name = project.get('name') or '未关联项目'
    if not isinstance(project_id, str) or len(project_id) > 200 or not isinstance(name, str):
        raise ValueError('项目编号或名称不正确')
    return project_id, name


def _strong(folder_name, aliases):
    folder = unicodedata.normalize('NFKC', folder_name).casefold()
    compact = re.sub(r'[^\w\u3400-\u9fff]', '', folder)
    generic = {'项目', '公司', '科技', '研究', 'project', 'company', 'technology'}
    for alias in aliases:
        text = unicodedata.normalize('NFKC', alias).strip().casefold()
        normalized = re.sub(r'[^\w\u3400-\u9fff]', '', text)
        if not normalized or normalized in generic:
            continue
        if normalized == compact:
            return True
        if text.isascii() and len(normalized) >= 4:
            if re.search(r'(?<![a-z0-9])' + re.escape(text) + r'(?![a-z0-9])', folder):
                return True
        elif len(normalized) >= 3 and normalized in compact:
            return True
    return False


class ProjectArtifacts:
    def __init__(self, data_dir, *, max_depth=4, max_directories=3000, max_entries=30000):
        self.data_dir = _plain(Path(data_dir).absolute())
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.max_depth, self.max_directories, self.max_entries = max_depth, max_directories, max_entries
        self.config_path = _confined(self.data_dir, self.data_dir / 'project-artifacts.json')
        self.managed = _mkdir(self.data_dir, self.data_dir / 'project-artifacts')
        self.config = {'schema_version': 1, 'roots': [], 'aliases': {}, 'bindings': {}}
        if self.config_path.exists():
            try:
                raw = json.loads(self.config_path.read_text(encoding='utf-8'))
                if not isinstance(raw, dict): raise ValueError()
                self.config.update(raw)
                self._validate_config(self.config)
            except (OSError, ValueError, TypeError) as exc:
                raise ValueError('项目文件夹配置无法读取；没有选择业务文件夹') from exc
        database = _confined(self.data_dir, self.data_dir / 'project-artifacts.sqlite3')
        for suffix in ('-wal', '-shm'):
            _confined(self.data_dir, Path(str(database) + suffix))
        self.db = sqlite3.connect(database, check_same_thread=False, timeout=20)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS archives ('
                        'id TEXT PRIMARY KEY, workspace TEXT NOT NULL, collection TEXT NOT NULL, '
                        'record_id TEXT NOT NULL, project_id TEXT NOT NULL, digest TEXT NOT NULL, '
                        'folder TEXT NOT NULL, receipt TEXT NOT NULL)')
        self.db.commit()

    def close(self):
        with self.lock:
            self.db.close()

    def _validate_config(self, config):
        if not isinstance(config.get('roots'), list) or len(config['roots']) > 10:
            raise ValueError('最多配置10个项目根文件夹')
        for root in config['roots']:
            if not isinstance(root, str): raise ValueError('项目根文件夹必须是路径')
            _plain(root)
        aliases, bindings = config.get('aliases'), config.get('bindings')
        if not isinstance(aliases, dict) or not isinstance(bindings, dict):
            raise ValueError('项目别名或绑定配置不正确')
        for key, names in aliases.items():
            if not isinstance(key, str) or not isinstance(names, list) or len(names) > 20 or any(
                    not isinstance(name, str) or not name.strip() or len(name) > 200 for name in names):
                raise ValueError('项目别名必须是非空文本列表')
        for key, binding in bindings.items():
            if not isinstance(key, str) or not isinstance(binding, dict) or not isinstance(binding.get('folder'), str):
                raise ValueError('项目文件夹绑定不正确')

    def _save_config(self):
        temporary = _confined(self.data_dir, self.data_dir / ('.project-artifacts-' + uuid.uuid4().hex + '.tmp'))
        try:
            with temporary.open('xb') as stream:
                stream.write(_json(self.config).encode('utf-8')); stream.flush(); os.fsync(stream.fileno())
            _confined(self.data_dir, self.config_path)
            os.replace(temporary, self.config_path)
        finally:
            if temporary.exists(): temporary.unlink()

    def configure(self, roots=None, aliases=None):
        with self.lock:
            updated = copy.deepcopy(self.config)
            if roots is not None:
                if not isinstance(roots, list): raise ValueError('项目根文件夹必须是列表')
                updated['roots'] = list(dict.fromkeys(str(_plain(root)) for root in roots))
            if aliases is not None: updated['aliases'] = copy.deepcopy(aliases)
            self._validate_config(updated)
            self.config = updated
            self._save_config()
            return {'roots': copy.deepcopy(updated['roots']), 'aliases': copy.deepcopy(updated['aliases'])}

    def _business_path(self, folder):
        folder = _plain(folder)
        for raw in self.config['roots']:
            try:
                candidate = _confined(raw, folder)
            except ValueError:
                continue
            if candidate.is_dir(): return candidate
        raise ValueError('项目文件夹必须位于配置的根文件夹内，且不能包含链接')

    def _fallback(self, workspace, project):
        project_id, name = _project(project)
        key = hashlib.sha256((project_id or 'unlinked').encode()).hexdigest()[:10]
        return _mkdir(self.managed, self.managed / workspace / (_name(name, '未关联项目') + '-' + key))

    def _scan(self, aliases):
        candidates, limited, entries, directories = [], False, 0, 0
        queue = [(Path(root), 0) for root in self.config['roots']]
        seen = set()
        while queue:
            folder, depth = queue.pop(0)
            try:
                folder = _plain(folder)
                if not folder.is_dir(): limited = True; continue
                if str(folder) in seen: continue
                seen.add(str(folder)); directories += 1
                if directories > self.max_directories: limited = True; break
                if depth and _strong(folder.name, aliases):
                    candidates.append({'folder': str(folder), 'name': folder.name, 'confidence': 'high'})
                if depth >= self.max_depth: continue
                children = []
                with os.scandir(folder) as stream:
                    for entry in stream:
                        entries += 1
                        if entries > self.max_entries: limited = True; break
                        if entry.name in (OUTPUT_FOLDER, '.git', 'node_modules', '__pycache__'): continue
                        if entry.is_dir(follow_symlinks=False) and not _linked(Path(entry.path)):
                            children.append(Path(entry.path))
                queue.extend((child, depth + 1) for child in sorted(children, key=lambda value: value.name.casefold()))
                if entries > self.max_entries: break
            except (OSError, ValueError):
                limited = True
        return sorted(candidates, key=lambda item: item['folder'].casefold()), limited

    def resolve(self, workspace, project):
        if workspace not in ('personal', 'demo'): raise ValueError('工作区选择不正确')
        project_id, name = _project(project)
        with self.lock:
            if workspace == 'demo' or not project_id:
                return {'status': 'managed', 'folder': str(self._fallback(workspace, project)),
                        'managed': True, 'candidates': [], 'scan_limited': False}
            existing = self.config['bindings'].get(project_id)
            if existing:
                try:
                    folder = self._business_path(existing['folder'])
                    return {'status': 'bound', 'folder': str(folder), 'managed': False, 'candidates': [],
                            'source': existing.get('source', 'manual'), 'scan_limited': False}
                except (OSError, ValueError):
                    # An unavailable/unsafe explicit binding is never silently replaced.
                    return {'status': 'pending', 'folder': str(self._fallback(workspace, project)), 'managed': True,
                            'candidates': [], 'scan_limited': True, 'error': '已绑定文件夹不可用，请检查或重新绑定'}
            aliases = [name, *self.config['aliases'].get(project_id, []), *self.config['aliases'].get(name, [])]
            aliases.extend(part.strip() for part in re.split(r'[/|;；，,]', name) if part.strip())
            # Registered names often append a translated name or project code;
            # retain both explicit variants for existing folder-name matching.
            expanded = unicodedata.normalize('NFKC', name)
            aliases.extend(part.strip() for part in re.split(r'[()]', expanded) if part.strip())
            candidates, limited = self._scan(aliases)
            if len(candidates) == 1 and not limited:
                folder = self._business_path(candidates[0]['folder'])
                self.config['bindings'][project_id] = {'folder': str(folder), 'source': 'automatic'}
                self._save_config()
                return {'status': 'matched', 'folder': str(folder), 'managed': False,
                        'candidates': candidates, 'scan_limited': False, 'source': 'automatic'}
            return {'status': 'pending' if candidates or limited else 'unmatched',
                    'folder': str(self._fallback(workspace, project)), 'managed': True,
                    'candidates': candidates, 'scan_limited': limited}

    def bind(self, workspace, project, folder):
        if workspace != 'personal': raise ValueError('演示区只使用本机托管文件夹')
        project_id, _ = _project(project)
        if not project_id: raise ValueError('请先选择项目')
        with self.lock:
            target = self._business_path(folder)
            self.config['bindings'][project_id] = {'folder': str(target), 'source': 'manual'}
            self._save_config()
            return self.resolve(workspace, project)

    @staticmethod
    def _exporters(collection, record):
        from .exports import html_report, docx_report, pptx_report, markdown, expert_minutes_docx, valuation_xlsx
        if collection == 'deliverables':
            callbacks = {'html': html_report, 'docx': docx_report, 'pptx': pptx_report, 'md': markdown}
            if record.get('method') and record.get('assumptions') and record.get('result'):
                from .valuation import calculate_valuation
                callbacks['xlsx'] = lambda item: valuation_xlsx(item['method'], item['assumptions'],
                    calculate_valuation(item['method'], item['assumptions']))
            return callbacks
        if collection == 'meetings':
            return {'html': lambda item: html_report({**item, 'body': item.get('summary', '')}),
                    'docx': lambda item: expert_minutes_docx(item['title'], item.get('summary', ''),
                        item.get('participants', ''), item.get('date', ''), item.get('experts'),
                        item.get('matrix'), item.get('contents'))}
        body_field = 'content' if collection == 'documents' else 'body'
        return {'md': lambda item: markdown({**item, 'body': item.get(body_field, '')}),
                'html': lambda item: html_report({**item, 'body': item.get(body_field, '')})}

    def _put(self, receipt, digest):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO archives VALUES (?,?,?,?,?,?,?,?)',
                (receipt['archive_id'], receipt['workspace'], receipt['collection'], receipt['record_id'],
                 receipt['project_id'], digest, receipt['folder'], _json(receipt)))

    def _reserve(self, workspace, collection, record, project_id, digest, binding):
        rows = self.db.execute('SELECT receipt FROM archives WHERE workspace=? AND collection=? AND record_id=?',
                               (workspace, collection, record['id'])).fetchall()
        number = max((json.loads(row[0]).get('version_number', 0) for row in rows), default=0) + 1
        topic = _name(record.get('task_group') or record.get('workflow_key') or collection, limit=32)
        identity = hashlib.sha256((collection + ':' + record['id']).encode()).hexdigest()[:10]
        folder = Path(binding['folder'])
        parent = folder / OUTPUT_FOLDER / topic / (_name(record.get('title'), '产物') + '-' + identity)
        target = parent / f'v{number:03d}-{digest[:10]}'
        receipt = {'archive_id': uuid.uuid4().hex, 'workspace': workspace, 'collection': collection,
            'record_id': record['id'], 'project_id': project_id, 'version': f'v{number:03d}',
            'version_number': number, 'folder': str(folder), 'artifact_folder': str(target),
            'managed': binding['managed'], 'binding_status': binding['status'],
            'status': 'pending', 'files': [], 'error': '', 'retryable': True}
        self._put(receipt, digest)
        return receipt

    def archive(self, workspace, collection, record, project, exporters=None):
        if workspace not in ('personal', 'demo'): raise ValueError('工作区选择不正确')
        if collection not in COLLECTIONS: raise ValueError('这类记录没有项目文件产物')
        if not isinstance(record, dict) or not isinstance(record.get('id'), str) or not record['id']:
            raise ValueError('产物需要有效的已保存记录')
        project_id, _ = _project(project)
        if (record.get('project_id') or '') != project_id: raise ValueError('记录不属于本次项目')
        if collection == 'documents' and record.get('kind') == 'memory':
            return {'status': 'skipped', 'folder': '', 'files': [], 'version': '', 'error': '个人记忆不保存到项目产物',
                    'retryable': False, 'managed': True, 'archive_id': '', 'collection': collection,
                    'record_id': record['id'], 'project_id': project_id, 'workspace': workspace}
        snapshot = copy.deepcopy(record)
        material = {key: value for key, value in snapshot.items() if key not in ('created_at', 'updated_at')}
        callbacks = exporters if exporters is not None else self._exporters(collection, snapshot)
        if not isinstance(callbacks, dict) or not callbacks or set(callbacks) - FORMATS:
            raise ValueError('产物格式不正确')
        digest = hashlib.sha256(_json({'record': material, 'formats': sorted(callbacks)}).encode()).hexdigest()
        with self.lock:
            binding = self.resolve(workspace, project)
            folder = Path(binding['folder'])
            row = self.db.execute('SELECT receipt FROM archives WHERE workspace=? AND collection=? '
                'AND record_id=? AND digest=? AND folder=? ORDER BY rowid DESC LIMIT 1',
                (workspace, collection, record['id'], digest, str(folder))).fetchone()
            if row:
                receipt = json.loads(row[0])
                if receipt.get('files'):
                    try:
                        for index in range(len(receipt['files'])): self.read_file(workspace, receipt['archive_id'], index)
                        receipt.update(status='saved_local' if binding['managed'] else 'saved', error='', retryable=False)
                        self._put(receipt, digest)
                        return receipt
                    except (OSError, ValueError, KeyError):
                        if receipt['status'] in ('saved', 'saved_local'):
                            receipt.update(status='failed', error='已保存产物缺失或被改动；可另存新版本，不会覆盖已有文件', retryable=True)
                            self._put(receipt, digest)
                            return receipt
                        if Path(receipt['artifact_folder']).exists():
                            receipt = self._reserve(workspace, collection, record, project_id, digest, binding)
            else:
                receipt = self._reserve(workspace, collection, record, project_id, digest, binding)
            staging = None
            try:
                payloads, total = [], 0
                for extension, callback in callbacks.items():
                    if not callable(callback): raise ValueError('产物导出器不正确')
                    payload = callback(copy.deepcopy(snapshot))
                    if isinstance(payload, str): payload = payload.encode('utf-8')
                    if not isinstance(payload, bytes) or not payload: raise ValueError('导出器没有返回有效文件')
                    total += len(payload)
                    if len(payload) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES: raise ValueError('产物超过文件大小上限')
                    payloads.append((extension, payload))
                target = _confined(folder, receipt['artifact_folder'])
                parent = _mkdir(folder, target.parent)
                if target.exists(): raise ValueError('该版本文件夹已存在；不会覆盖已有版本')
                staging = _mkdir(folder, parent / ('.pending-' + uuid.uuid4().hex))
                files = []
                for index, (extension, payload) in enumerate(payloads):
                    filename = _name(record.get('title'), '产物') + '.' + extension
                    destination = _confined(folder, staging / filename)
                    with destination.open('xb') as stream:
                        stream.write(payload); stream.flush(); os.fsync(stream.fileno())
                    files.append({'name': filename, 'path': str(target / filename), 'format': extension,
                        'index': index, 'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload)})
                # Persist recovery metadata before making the entire version visible.
                receipt['files'] = files
                self._put(receipt, digest)
                _confined(folder, staging); _confined(folder, target)
                os.rename(staging, target); staging = None
                receipt.update(status='saved_local' if binding['managed'] else 'saved', error='', retryable=False)
                self._put(receipt, digest)
            except Exception as exc:
                receipt.update(status='failed', error='项目文件保存未完成；原记录已保留，可重试导出（' + type(exc).__name__ + '）', retryable=True)
                self._put(receipt, digest)
            finally:
                if staging is not None:
                    # Staging belongs to this attempt; never remove version/original directories.
                    try: shutil.rmtree(_confined(folder, staging))
                    except (OSError, ValueError): pass
            return copy.deepcopy(receipt)

    def status(self, workspace, project):
        project_id, _ = _project(project)
        with self.lock:
            binding = self.resolve(workspace, project)
            rows = self.db.execute('SELECT receipt FROM archives WHERE workspace=? AND project_id=? ORDER BY rowid DESC LIMIT 100',
                                   (workspace, project_id)).fetchall()
            return {'binding': binding, 'archives': [json.loads(row[0]) for row in rows]}

    def read_file(self, workspace, archive_id, index):
        if workspace not in ('personal', 'demo') or not isinstance(archive_id, str) or type(index) is not int or index < 0:
            raise KeyError('产物文件不存在')
        with self.lock:
            row = self.db.execute('SELECT receipt FROM archives WHERE workspace=? AND id=?', (workspace, archive_id)).fetchone()
            if not row: raise KeyError('产物文件不存在')
            receipt = json.loads(row[0])
            if index >= len(receipt['files']): raise KeyError('产物文件不存在')
            item = receipt['files'][index]
            folder = _confined(self.managed, receipt['folder']) if receipt['managed'] else self._business_path(receipt['folder'])
            artifact = _confined(folder / OUTPUT_FOLDER, receipt['artifact_folder'])
            file = _confined(artifact, item['path'])
            if not file.is_file() or file.stat().st_size > MAX_FILE_BYTES:
                raise ValueError('产物文件缺失或超过上限')
            payload = file.read_bytes()
            if len(payload) != item.get('bytes') or hashlib.sha256(payload).hexdigest() != item.get('sha256'):
                raise ValueError('产物文件已被改动；未覆盖原文件')
            return payload, item['name']
