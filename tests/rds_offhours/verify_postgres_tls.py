"""로컬 Docker PostgreSQL16에서 TLS/권한/고정 SELECT를 실제 검사한다.

AWS/개발 DB에는 접속하지 않는다. 생성한 컨테이너·임시 인증서만 finally에서 정리한다.
"""
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'runtime/rds_offhours'))
from audit import collect


def command(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout.strip()


def main():
    container = None
    passed = []
    with tempfile.TemporaryDirectory(prefix='ipgo-rds-tls-') as temp:
        folder = Path(temp)
        password = secrets.token_urlsafe(32)
        envfile = folder / 'postgres-env'
        envfile.write_text('POSTGRES_PASSWORD=' + password + '\nPOSTGRES_DB=ipgo\n')
        envfile.chmod(0o600)
        command('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                '-keyout', str(folder/'server.key'), '-out', str(folder/'server.crt'),
                '-days', '1', '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost')
        # Alpine postgres uid70가 읽을 수 있는 전용 임시 키. 상위 폴더는 임시 mount 전용.
        (folder/'server.key').chmod(0o644)
        # entrypoint가 소유권/0600을 설정하도록 별도 복사한 뒤 postgres를 시작한다.
        bootstrap = ('cp /tls/server.key /tmp/server.key; cp /tls/server.crt /tmp/server.crt; '
                     'chown postgres:postgres /tmp/server.key /tmp/server.crt; chmod 600 /tmp/server.key; '
                     'exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/tmp/server.crt '
                     '-c ssl_key_file=/tmp/server.key')
        try:
            image = command('docker', 'image', 'inspect', 'postgres:16-alpine', '--format', '{{.Id}}')
            container = command('docker', 'run', '-d', '--memory=256m', '--cpus=1',
                                '--env-file', str(envfile), '-p', '127.0.0.1::5432',
                                '-v', f'{folder}:/tls:ro', '--entrypoint', 'sh', image, '-ec', bootstrap)
            port = command('docker', 'port', container, '5432/tcp').rsplit(':', 1)[1]
            args = dict(host='localhost', port=int(port), dbname='ipgo', user='postgres',
                        password=password, sslmode='verify-full', sslrootcert=str(folder/'server.crt'),
                        connect_timeout=2)
            for attempt in range(40):
                try:
                    admin = psycopg.connect(**args, autocommit=True)
                    break
                except psycopg.OperationalError:
                    if attempt == 39:
                        raise RuntimeError('local_postgres_not_ready') from None
                    time.sleep(0.5)
            with admin:
                admin.execute('CREATE TABLE public.flyway_schema_history(installed_rank int, version text, checksum int, success bool)')
                admin.execute("INSERT INTO public.flyway_schema_history VALUES (1,'14',123,true)")
                admin.execute('CREATE TABLE public.engine_jobs(job_id text, status text)')
                admin.execute('CREATE TABLE public.calculation_runs(id bigint, status text)')
                admin.execute('CREATE TABLE public.calculation_results(id bigint, run_id bigint, risk_basis text)')
                admin.execute('CREATE TABLE public.scenario_results(id bigint, result_id bigint)')
                admin.execute('CREATE TABLE public.ai_explanations(id bigint, result_id bigint, mode text, status text)')
                admin.execute("INSERT INTO public.calculation_runs VALUES(1,'DONE')")
                admin.execute("INSERT INTO public.calculation_results VALUES(1,1,'POOLED')")
                admin.execute("INSERT INTO public.ai_explanations VALUES(1,1,'NONE','DISABLED')")
                admin.execute((ROOT/'runtime/rds_offhours/audit-role.sql').read_text())
                audit_password = secrets.token_urlsafe(32)
                admin.execute(sql.SQL('ALTER ROLE ipgo_rds_auditor LOGIN PASSWORD {}').format(sql.Literal(audit_password)))
                reader = dict(args, user='ipgo_rds_auditor', password=audit_password,
                              options='-c default_transaction_read_only=on')
                with psycopg.connect(**reader) as conn:
                    good = collect(conn, 1)
                    assert good['read_only'] and good['tls_verified']
                    assert good['active_engine_jobs'] == good['open_business_transactions'] == 0
                    assert good['llm_explanation_violations'] == 0
                passed.append('verify_full_readonly_fixed_queries')
                for bad in (dict(reader, host='127.0.0.1'), dict(reader, sslrootcert=str(folder/'absent.crt'))):
                    try:
                        psycopg.connect(**bad)
                    except psycopg.OperationalError:
                        pass
                    else:
                        raise AssertionError('invalid_tls_accepted')
                passed.append('hostname_and_ca_failure')
                with psycopg.connect(**reader, autocommit=True) as conn:
                    try:
                        conn.execute("INSERT INTO public.engine_jobs VALUES('forbidden','PENDING')")
                    except (psycopg.errors.ReadOnlySqlTransaction, psycopg.errors.InsufficientPrivilege):
                        pass
                    else:
                        raise AssertionError('write_accepted')
                    conn.execute('SET default_transaction_read_only=off')
                    try:
                        conn.execute("INSERT INTO public.engine_jobs VALUES('forbidden','PENDING')")
                    except psycopg.errors.InsufficientPrivilege:
                        pass
                    else:
                        raise AssertionError('write_privilege_present')
                    assert not conn.execute("SELECT pg_has_role(current_user, 'postgres', 'MEMBER')").fetchone()[0]
                passed.append('write_and_admin_role_denied')
                # 다른 실제 트랜잭션이 있으면 제한된 집계 함수가 이를 숨기지 않아야 한다.
                with psycopg.connect(**args) as writer:
                    writer.execute('SELECT 1')
                    with psycopg.connect(**reader) as conn:
                        assert collect(conn, 1)['open_business_transactions'] >= 1
                passed.append('other_session_transaction_visible')
                admin.execute("INSERT INTO public.engine_jobs VALUES('pending','PENDING')")
                admin.execute("UPDATE public.ai_explanations SET mode='REAL', status='DONE'")
                with psycopg.connect(**reader) as conn:
                    changed = collect(conn, 1)
                    assert changed['active_engine_jobs'] == changed['llm_explanation_violations'] == 1
                    assert changed['reference_sha256'] != good['reference_sha256']
                    try:
                        collect(conn, 999)
                    except ValueError:
                        pass
                    else:
                        raise AssertionError('missing_reference_accepted')
                passed.append('jobs_llm_reference_change_detected')
            print(json.dumps({'source': 'LOCAL_POSTGRES16_TLS', 'passed': passed,
                              'production_db_tested': False, 'llm_calls': 0}))
        finally:
            if container:
                command('docker', 'rm', '-f', container)


if __name__ == '__main__':
    main()
