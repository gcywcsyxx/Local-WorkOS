"""Back up existing workspace databases without changing authentication or originals."""
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from contextlib import closing


def backup(data_dir, destination):
    data_dir, destination = Path(data_dir), Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    saved = []
    for name in ('personal.sqlite3', 'demo.sqlite3', 'workflow-jobs.sqlite3', 'conversations.sqlite3', 'project-artifacts.sqlite3'):
        source = data_dir / name
        if not source.is_file():
            continue
        with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as original:
            with closing(sqlite3.connect(destination / name)) as target:
                original.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Workspace backup integrity check failed')
        saved.append(name)
    configuration = data_dir / 'project-artifacts.json'
    if configuration.is_file():
        raw = configuration.read_bytes()
        json.loads(raw)
        (destination / configuration.name).write_bytes(raw)
    (destination / 'manifest.json').write_text(json.dumps({'databases': saved, 'originals': 'retained-in-place', 'authentication': 'retained-in-place'}), encoding='utf-8')
    return saved


if __name__ == '__main__':
    root = Path(os.environ['LOCALAPPDATA']) / 'LocalWorkOS'
    target = root / 'release-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    print(json.dumps({'backed_up': backup(root, target)}))
