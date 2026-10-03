"""Check tracked source and reachable history without displaying sensitive values.

Private literals can be set locally with `git config --add privacy.blockedLiteral ...`.
That configuration is never checked into source or sent to the CI runner.
"""
import argparse
import re
import subprocess
from pathlib import Path

RULES = {
    "GitHub credential": rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b",
    "provider credential": rb"\bsk-(?:proj-|ant-|svcacct-)?[A-Za-z0-9_-]{30,}\b",
    "AWS credential": rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    "private key": rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
    "personal home path": rb"(?i)(?:[A-Z]:[\\/](?:Users|Documents and Settings)[\\/]|/(?:Users|home)/)(?!synthetic-user(?:[\\/]|\b)|example-user(?:[\\/]|\b)|<|\$)[A-Za-z0-9_.-]+[\\/]",
}
PRIVATE_FILE = re.compile(r"(?i)(?:^|/)(?:\.env(?:\.|$)|password-account\.json$|sessions\.sqlite3$|credentials[^/]*$|secrets[^/]*$|data/|backups/|exports/)|\.(?:db|sqlite3?|pfx|p12|pem|key|log)$")


def git(*args, cwd=None):
    return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL)


def scan(data, blocked=()):
    results = [(name, data[:match.start()].count(b"\n") + 1)
               for name, expression in RULES.items()
               for match in re.finditer(expression, data)]
    lowered = data.lower()
    for value in blocked:
        offset = lowered.find(value.lower())
        if offset >= 0:
            results.append(("locally blocked personal literal", data[:offset].count(b"\n") + 1))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="Also scan every object reachable from HEAD")
    args = parser.parse_args()
    root = Path(git("rev-parse", "--show-toplevel").decode().strip())
    config = subprocess.run(["git", "config", "--get-all", "privacy.blockedLiteral"], cwd=root, capture_output=True)
    blocked = tuple(value for value in config.stdout.splitlines() if value)
    failures = []
    for raw in git("ls-files", "-z", cwd=root).split(b"\0"):
        if not raw:
            continue
        name = raw.decode("utf-8")
        if PRIVATE_FILE.search(name):
            failures.append((name, "private runtime file", 0))
        path = root / name
        if path.is_file():
            failures.extend((name, rule, line) for rule, line in scan(path.read_bytes(), blocked))
    if args.history:
        objects = git("rev-list", "--objects", "HEAD", cwd=root).splitlines()
        for item in objects:
            oid, _, raw_name = item.partition(b" ")
            kind = git("cat-file", "-t", oid.decode(), cwd=root).strip()
            if kind not in (b"blob", b"commit"):
                continue
            name = raw_name.decode("utf-8", "replace") or "commit metadata"
            label = f"{oid.decode()[:12]}:{name}"
            if kind == b"blob" and PRIVATE_FILE.search(name):
                failures.append((label, "private runtime file", 0))
            content = git("cat-file", "-p", oid.decode(), cwd=root)
            failures.extend((label, rule, line) for rule, line in scan(content, blocked))
            if kind == b"commit":
                header = content.split(b"\n\n", 1)[0]
                for identity in re.findall(rb"^(?:author|committer) .*?<([^<>]+)>", header, re.M):
                    if not identity.endswith(b"@users.noreply.github.com"):
                        failures.append((label, "non-noreply commit email", 0))
    for name, rule, line in sorted(set(failures)):
        print(f"{name}:{line}: {rule} (value withheld)")
    if failures:
        raise SystemExit(1)
    print("Public privacy checks passed: tracked source" + (" and reachable history." if args.history else "."))


if __name__ == "__main__":
    main()
