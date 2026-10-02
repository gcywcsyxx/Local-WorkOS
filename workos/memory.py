"""Explicit opt-in, read-only Markdown context. Never changes source memories."""
from __future__ import annotations
import hashlib
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

EXCLUDED_PARTS = {'archive', 'archives', 'credentials', 'secrets', 'environment',
                  'node_modules', 'venv', 'corpus', '99-原始归档', '_历史版本'}
SENSITIVE_NAME = re.compile(r'credential|secret|password|passwd|token|api[_ -]?key|environment|archiv|凭据|凭证|勿外发|敏感|机器环境|归档', re.I)
MAX_BYTES = 2_000_000


def _linked(path):
    """Reject symbolic links and Windows junction/reparse points."""
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _safe_root(root):
    if root is None:
        return None
    try:
        path = Path(root).absolute()
        if any(_linked(part) for part in (path, *path.parents)):
            return None
        return path.resolve(strict=True) if path.is_dir() else None
    except (OSError, ValueError, RuntimeError):
        return None


def find_root(app_root: Path):
    """No discovery: only an explicitly configured absolute folder is enabled."""
    configured = os.environ.get('WORKOS_MEMORY_ROOT', '').strip()
    if not configured or not Path(configured).is_absolute():
        return None
    return _safe_root(Path(configured))


def _excluded(name):
    return name.startswith('.') or name.casefold() in EXCLUDED_PARTS or bool(SENSITIVE_NAME.search(name))


def candidates(root: Path | None):
    root = _safe_root(root)
    if root is None:
        return {}
    files = {}
    # Prune excluded folders before descending; do not read their contents.
    for directory, folders, names in os.walk(root, followlinks=False):
        base = Path(directory)
        try:
            folders[:] = [name for name in folders if not _excluded(name) and not _linked(base / name)]
            for name in names:
                if _excluded(name) or Path(name).suffix.casefold() != '.md':
                    continue
                path = base / name
                if _linked(path) or not path.is_file() or path.stat().st_size > MAX_BYTES:
                    continue
                resolved = path.resolve(strict=True)
                if resolved.is_relative_to(root):
                    files[path.relative_to(root).as_posix()] = path
        except (OSError, ValueError, RuntimeError):
            continue
    return files


def category(path: str):
    if 'daily/' in path or 'session-history' in path: return '会话'
    if 'profile' in path or '档案' in path or '协作' in path or 'MEMORY' in path: return '偏好'
    if 'environment' in path or '机器环境' in path: return '环境'
    return '方法'


def scan(root):
    files = []
    for rel, path in sorted(candidates(root).items()):
        try:
            info = path.stat()
            files.append({'path': rel, 'title': path.stem, 'category': category(rel),
                          'size': info.st_size, 'modified': datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat()})
        except OSError:
            continue
    return {'files': files, 'skipped': ['仅显式配置的文件夹内 Markdown 可读取；隐藏、归档、环境、凭证及链接文件排除。导入前仍须人工复核敏感内容。'],
            'root_available': _safe_root(root) is not None}


def sanitize(text):
    # Best-effort minimization, not a guarantee of complete anonymization.
    text = re.sub(r'\b(?:sk-|sk_)[A-Za-z0-9_-]{16,}', '[凭证已隐藏]', text)
    text = re.sub(r'\bBearer\s+[A-Za-z0-9._~+/=-]{12,}', 'Bearer [凭证已隐藏]', text, flags=re.I)
    text = re.sub(r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[凭证已隐藏]', text)
    text = re.sub(r'\b[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', '[邮箱已隐藏]', text)
    text = re.sub(r'(?i)\b[A-Z]:[\\/]Users[\\/][^\r\n`"<>]+|/(?:home|Users)/[^\s`"<>]+', '[用户路径已隐藏]', text)
    lines = []
    for line in text.splitlines():
        sensitive = re.search(r'(?:api[_ -]?key|access[_ -]?token|authorization|password|passwd|密码|密钥|口令)\s*[=:：]\s*[`"\x27]?\S+', line, re.I)
        lines.append('[含认证信息的原文行已隐藏]' if sensitive else line)
    return '\n'.join(lines)


def safe_upload_source(source_ref: str):
    """Accept only a browser-supplied relative path; reject secret/archive trees."""
    if not isinstance(source_ref, str) or not source_ref.strip() or len(source_ref) > 1000 or "\x00" in source_ref:
        raise ValueError('记忆来源路径不正确')
    normalized = source_ref.replace('\\', '/')
    parts = normalized.split('/')
    if (normalized.startswith('/') or re.match(r'^[A-Za-z]:', normalized)
            or any(part in ('', '.', '..') for part in parts)
            or any(_excluded(part) for part in parts)):
        raise ValueError('记忆路径包含绝对路径、隐藏目录、凭证或归档位置')
    return '/'.join(parts)


def import_uploaded_memory(store, parsed, filename, source_ref):
    """Store a user-selected file as a local, redacted, non-exportable memory item."""
    from .engine import chunk_text
    source = safe_upload_source(source_ref)
    pages = parsed.get('pages') if isinstance(parsed, dict) else None
    clean_pages = None
    if isinstance(pages, list) and pages:
        clean_pages = []
        for page in pages:
            if not isinstance(page, dict) or not isinstance(page.get('text'), str):
                raise ValueError('记忆文件页码结构不正确')
            clean_pages.append({**page, 'text': sanitize(page['text'])})
        content = '\n\n'.join(page['text'] for page in clean_pages)
    else:
        content = sanitize(parsed.get('content', '') if isinstance(parsed, dict) else '')
    if not content.strip():
        raise ValueError('没有提取到可导入的文字')
    if len(content.encode('utf-8')) > MAX_BYTES:
        raise ValueError('记忆文本超过2MB限制')
    digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
    existing = next((item for item in store.list('documents')
                     if item.get('kind') == 'memory' and item.get('source_ref') == source), None)
    if existing and existing.get('hash') == digest:
        return {**existing, 'unchanged': True}
    data = {'title': Path(filename).stem[:200] or '记忆文件', 'kind': 'memory',
            'category': category(source), 'source_ref': source, 'content': content,
            'filename': Path(filename).name, 'private': True,
            'page_count': parsed.get('page_count') if isinstance(parsed, dict) else 1,
            'hash': digest, 'chunks': chunk_text(content, clean_pages)}
    if existing:
        return {**store.update('documents', existing['id'], data), 'updated': True}
    return {**store.create('documents', data), 'imported': True}


def import_memories(root, paths, store):
    from .engine import chunk_text
    if not isinstance(paths, list) or not paths or len(paths) > 150:
        raise ValueError('请选择1至150份记忆文件')
    found = candidates(root)
    if any(not isinstance(path, str) or path not in found for path in paths):
        raise ValueError('请求包含不在允许列表内的文件')
    existing = {obj.get('source_ref'): obj for obj in store.list('documents') if obj.get('kind') == 'memory'}
    result = {'imported': 0, 'updated': 0, 'unchanged': 0, 'skipped': []}
    for rel in dict.fromkeys(paths):
        try:
            # Revalidate before opening to reject links changed since enumeration.
            path = candidates(root).get(rel)
            if path is None:
                raise ValueError('文件不再位于允许列表')
            before = path.lstat()
            with path.open('rb') as source:
                opened = os.fstat(source.fileno())
                if (not stat.S_ISREG(opened.st_mode) or _linked(path)
                        or not os.path.samestat(before, opened)
                        or candidates(root).get(rel) != path):
                    raise ValueError('仅允许未变更的普通文件')
                raw = source.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError('文件超过大小限制')
            content = sanitize(raw.decode('utf-8-sig'))
            digest = hashlib.sha256(content.encode()).hexdigest()
            if rel in existing and existing[rel].get('hash') == digest:
                result['unchanged'] += 1
                continue
            data = {'title': path.stem, 'kind': 'memory', 'category': category(rel), 'source_ref': rel,
                    'content': content, 'filename': path.name, 'private': True, 'page_count': 1,
                    'hash': digest, 'chunks': chunk_text(content)}
            if rel in existing:
                store.update('documents', existing[rel]['id'], data)
                result['updated'] += 1
            else:
                store.create('documents', data)
                result['imported'] += 1
        except (OSError, UnicodeError, ValueError):
            result['skipped'].append({'path': rel, 'reason': '文件不可读取或不满足安全约束'})
    return result
