"""Refresh only committed public source in the configured project mirror."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from launch import configure_saved_env
from workos import __version__


def main():
    env = dict(os.environ)
    configure_saved_env(env)
    configured = env.get('WORKOS_SYNC_ROOT')
    if not configured:
        print(json.dumps({'source_mirror': 'not-configured'}))
        return
    mirror = Path(configured)
    if not mirror.is_absolute():
        raise ValueError('Source mirror must use the configured absolute project root')
    target = mirror / 'Source'
    if target.is_symlink() or (target / '.git').exists():
        raise ValueError('Source mirror is a link or independent checkout; refusing to overwrite')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    paths = subprocess.check_output(['git', 'ls-tree', '-rz', '--name-only', revision], cwd=ROOT).split(b'\0')
    count = 0
    for raw in paths:
        if not raw:
            continue
        relative = Path(raw.decode('utf-8'))
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe tracked source path')
        destination = target / relative
        if not destination.resolve().is_relative_to(target.resolve()):
            raise ValueError('Source mirror contains an unsafe link')
        content = subprocess.check_output(['git', 'show', revision + ':' + relative.as_posix()], cwd=ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists() or destination.read_bytes() != content:
            destination.write_bytes(content)
        count += 1
    (target / 'workos-release.json').write_text(json.dumps({'version': __version__, 'source_revision': revision}), encoding='utf-8')
    print(json.dumps({'source_mirror': 'updated-committed-files', 'files': count, 'source_revision': revision}))


if __name__ == '__main__':
    main()
