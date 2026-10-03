"""Immutable, workspace-scoped uploaded originals; filenames never become paths."""
from __future__ import annotations
import hashlib
import os
import re
import uuid
from pathlib import Path

MAX_ORIGINAL_BYTES = 20_000_000


class OriginalUnavailable(KeyError):
    """A valid material record exists, but this host has no original bytes."""


def original_path(data_dir, workspace, digest):
    if workspace not in ('personal', 'demo') or not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise ValueError('原文件编号无效')
    base = Path(data_dir).resolve()
    folder = base / 'originals' / workspace
    if folder.resolve() != folder or (base / 'originals').is_symlink() or folder.is_symlink():
        raise ValueError('原文件目录无效')
    path = folder / digest
    if path.is_symlink() or path.resolve().parent != folder:
        raise ValueError('原文件路径无效')
    return path


def save_original(data_dir, workspace, raw, name):
    if not isinstance(raw, bytes) or len(raw) > MAX_ORIGINAL_BYTES:
        raise ValueError('单份原文件最多20MB')
    if not isinstance(name, str):
        raise ValueError('文件名无效')
    digest = hashlib.sha256(raw).hexdigest()
    target = original_path(data_dir, workspace, digest)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != raw:
            raise ValueError('原文件完整性校验失败')
    else:
        temporary = target.with_name(digest + '.tmp-' + uuid.uuid4().hex)
        try:
            with temporary.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    filename = name.replace('\\', '/').rsplit('/', 1)[-1]
    return {'attachment_ref': digest, 'attachment_hash': digest,
            'attachment_name': filename[:200] or 'original'}


def read_original(data_dir, workspace, record):
    if record.get('kind') == 'memory' or not record.get('attachment_ref'):
        raise OriginalUnavailable('这份材料没有保留原文件；可阅读已提取的文字')
    digest = record.get('attachment_hash')
    if digest != record.get('attachment_ref'):
        raise ValueError('原文件编号不一致')
    target = original_path(data_dir, workspace, digest)
    if not target.is_file():
        raise OriginalUnavailable('原文件在此主机不可用；JSON备份不包含原文件字节，可尝试OneDrive同步恢复')
    with target.open('rb') as stream:
        raw = stream.read(MAX_ORIGINAL_BYTES + 1)
    if len(raw) > MAX_ORIGINAL_BYTES or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('原文件完整性校验失败')
    return raw
