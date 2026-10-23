"""Explicitly launch only the authorized isolated product demo, or its recovery copy."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import time

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parents[1]
EMAILS = ['buyer-one@customer-service.example', 'buyer-two@customer-service.example', 'admin@customer-service.example']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['launch', 'stop'])
    parser.add_argument('--state-directory', required=True)
    parser.add_argument('--recovery', action='store_true')
    args = parser.parse_args()
    state = Path(args.state_directory).resolve()
    if state.exists():
        if state.is_symlink() or not state.is_dir() or state.stat().st_mode & 0o077:
            raise RuntimeError('State directory must be private')
    else:
        state.mkdir(mode=0o700)
    project = 'shop-customer-service-demo-recovery' if args.recovery else 'shop-customer-service-demo'
    port = '18012' if args.recovery else '18011'
    state_file = state / 'runtime.json'
    started = time.monotonic()
    if args.action == 'launch':
        if state_file.exists():
            raise RuntimeError('Refusing to overwrite existing runtime state')
        image = subprocess.check_output(['docker', 'image', 'inspect', 'shop-customer-service-demo-api:20261023', '--format', '{{.Id}}'], text=True).strip()
        data = {'project': project, 'port': port, 'image': image, 'database_password': secrets.token_urlsafe(32),
                'passwords': {email: secrets.token_urlsafe(24) for email in EMAILS}}
        fd = os.open(state_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream)
        fd = os.open(state / 'passwords.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(data['passwords'], stream)
    else:
        if state_file.stat().st_mode & 0o077:
            raise RuntimeError('Runtime state permissions are too broad')
        data = json.loads(state_file.read_text())
        if data['project'] != project:
            raise RuntimeError('State project mismatch')
    env = {key: value for key, value in os.environ.items() if not key.startswith(('COMPOSE_', 'SHOP_', 'DEMO_'))}
    env.update(DEMO_SHOP_DB_PASSWORD=data['database_password'], DEMO_SHOP_API_IMAGE=data['image'], DEMO_SHOP_PORT=data['port'])
    command = ['docker', 'compose', '--env-file', os.devnull, '-p', project, '-f', str(DIRECTORY / 'compose.products.yaml')]

    def run(arguments, body=None):
        result = subprocess.run(command + arguments, env=env, input=body, capture_output=True, text=True, timeout=90)
        if result.returncode:
            # Do not print raw Compose/SQL output, which can contain credential URLs.
            raise RuntimeError('Isolated demo operation failed: ' + arguments[0])
        return result.stdout

    if args.action == 'stop':
        run(['stop'])
        print('Stopped only ' + project + '; volumes preserved.')
        return
    existing = subprocess.check_output(['docker', 'ps', '-a', '--filter', 'label=com.docker.compose.project=' + project, '--format', '{{.ID}}'], text=True)
    volumes = subprocess.check_output(['docker', 'volume', 'ls', '--filter', 'label=com.docker.compose.project=' + project, '--format', '{{.Name}}'], text=True)
    if existing.strip() or volumes.strip():
        raise RuntimeError('Refusing existing project resources; use a new reviewed recovery scope')
    run(['up', '-d', '--wait', 'shop-db'])
    provision = "import os; p='/var/log/shop-customer-service'; os.chown(p,10001,10001); os.chmod(p,0o700)"
    run(['run', '--rm', '--no-deps', '-T', '--user', '0:0', '--entrypoint', 'python', 'shop-api', '-c', provision])
    run(['run', '--rm', '--no-deps', '-T', '--entrypoint', 'alembic', 'shop-api', 'upgrade', 'head'])
    initialize = """import json,os,sys
from shop_api.customer_service_demo import initialize_customer_service_demo
initialize_customer_service_demo(os.environ['SHOP_DATABASE_URL'],os.environ['SHOP_CUSTOMER_SERVICE_FIXTURE_PATH'],os.environ['SHOP_CUSTOMER_SERVICE_FIXTURE_SHA256'],json.load(sys.stdin),allow_migration_seed=True)
print('Isolated fixture initialized')
"""
    run(['run', '--rm', '--no-deps', '-T', '--entrypoint', 'python', 'shop-api', '-c', initialize], json.dumps(data['passwords']))
    run(['up', '-d', '--wait', 'shop-api', 'shop-web'])
    report = {'project': project, 'origin': 'http://127.0.0.1:' + port, 'image': data['image'],
              'provision_seconds': round(time.monotonic() - started, 3), 'paid_calls': 0}
    (state / 'launch-result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
