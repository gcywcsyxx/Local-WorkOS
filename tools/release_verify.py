"""Read-only deployment probes. Never obtains production passwords or cookies."""
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from launch import configure_saved_env
import os


def main():
    env = dict(os.environ)
    configure_saved_env(env)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    # Match a normal browser entry: edge browser-integrity rules reject Python's default UA.
    # These probes remain anonymous and never attach production cookies or credentials.
    opener.addheaders = [('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36')]
    def get(url):
        with opener.open(url, timeout=20) as response:
            return response.status, response.read()
    _, body = get('http://127.0.0.1:18866/api/workflows')
    if len(json.loads(body).get('workflows', [])) < 11:
        raise ValueError('Workflow catalogue is unavailable')
    origin = env.get('WORKOS_PUBLIC_ORIGIN', '').rstrip('/')
    _, body = get('http://127.0.0.1:18866/api/sync/status')
    sync = json.loads(body)
    if env.get('WORKOS_SYNC_ROOT') and not sync.get('enabled'):
        raise ValueError('The configured project mirror is not enabled')
    if sync.get('error'):
        raise ValueError('Project mirror reported a synchronization error')
    if origin:
        if env.get('WORKOS_PUBLIC_AUTH_MODE') != 'password' or not origin.startswith('https://'):
            raise ValueError('This SOP verifies the configured password-protected HTTPS deployment')
        _, body = get('http://127.0.0.1:18866/api/public/status')
        public = json.loads(body)
        if public.get('origin') != origin or public.get('auth_mode') != 'password' or not public.get('password_configured'):
            raise ValueError('The running service lacks the configured public origin or login account')
        status, body = get(origin + '/auth/login')
        if status != 200 or b'WorkOS' not in body:
            raise ValueError('Public login page unavailable')
        for route in ('/api/state', '/api/workflows', '/api/health'):
            try:
                get(origin + route)
            except urllib.error.HTTPError as exc:
                if exc.code != 401:
                    raise ValueError('Anonymous API denial returned an unexpected status') from None
            else:
                raise ValueError('Anonymous public workspace access was allowed')
    print(json.dumps({'local_workflows': 'ok', 'public_login_and_anonymous_denial': 'ok' if origin else 'not-configured'}))


if __name__ == '__main__':
    main()
