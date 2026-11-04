"""단기 감사 전용 컨테이너. 고정 SELECT, verify-full, 읽기 전용 트랜잭션."""
import datetime as dt
import hashlib
import json
import os
import signal

SCHEMA_SQL = '''SELECT jsonb_build_object(
 'flyway', (SELECT coalesce(jsonb_agg(jsonb_build_array(version, checksum, success)
              ORDER BY installed_rank), '[]'::jsonb) FROM public.flyway_schema_history),
 'columns', (SELECT coalesce(jsonb_agg(jsonb_build_array(table_name, column_name,
              ordinal_position, data_type, is_nullable, column_default)
              ORDER BY table_name, ordinal_position), '[]'::jsonb)
              FROM information_schema.columns WHERE table_schema='public'
              AND table_name IN ('engine_jobs','calculation_runs','calculation_results',
                                 'scenario_results','ai_explanations')))::text'''
JOBS_SQL = "SELECT count(*) FROM public.engine_jobs WHERE status IN ('PENDING', 'SENT')"
ACTIVITY_SQL = 'SELECT open_transactions FROM public.rds_offhours_activity_v1()'
REFERENCE_SQL = '''SELECT jsonb_build_object(
 'run', (SELECT to_jsonb(r) FROM public.calculation_runs r WHERE id = %s),
 'results', (SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY id), '[]'::jsonb)
             FROM public.calculation_results r WHERE run_id = %s),
 'scenarios', (SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY s.id), '[]'::jsonb)
              FROM public.scenario_results s JOIN public.calculation_results r
              ON r.id=s.result_id WHERE r.run_id=%s),
 'explanations', (SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY e.id), '[]'::jsonb)
                 FROM public.ai_explanations e JOIN public.calculation_results r
                 ON r.id=e.result_id WHERE r.run_id=%s))::text'''
LLM_SQL = '''SELECT count(*) FROM public.ai_explanations
 WHERE mode <> 'NONE' OR status <> 'DISABLED' '''


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def collect(connection, reference_run_id):
    if type(reference_run_id) is not int or reference_run_id <= 0:
        raise ValueError('invalid_reference_id')
    with connection.transaction():
        with connection.cursor() as cur:
            cur.execute('SET TRANSACTION READ ONLY')
            cur.execute("SET LOCAL statement_timeout = '15000ms'")
            cur.execute("SET LOCAL idle_in_transaction_session_timeout = '15000ms'")
            cur.execute("""SELECT current_setting('transaction_read_only') = 'on', ssl
                         FROM pg_catalog.pg_stat_ssl WHERE pid = pg_backend_pid()""")
            if cur.fetchone() != (True, True):
                raise ValueError('readonly_tls_not_verified')
            def scalar(sql, params=None):
                cur.execute(sql, params)
                return cur.fetchone()[0]
            schema = scalar(SCHEMA_SQL)
            reference = scalar(REFERENCE_SQL, (reference_run_id,) * 4)
            if json.loads(reference).get('run') is None:
                raise ValueError('reference_missing')
            return {'read_only': True, 'tls_verified': True,
                    'schema_sha256': sha(schema), 'reference_sha256': sha(reference),
                    'active_engine_jobs': scalar(JOBS_SQL),
                    'open_business_transactions': scalar(ACTIVITY_SQL),
                    'llm_explanation_violations': scalar(LLM_SQL)}


def main():
    import boto3
    import psycopg
    from botocore.config import Config
    config = json.loads(os.environ['AUDIT_CONFIG'])
    # workflow/NAS와 별개인 프로세스 상한. 종료 시 연결은 OS가 닫는다.
    signal.alarm(110)
    # Secret 값·DB 행·예외 문자열은 로그나 결과에 담지 않는다.
    secret = json.loads(boto3.client('secretsmanager').get_secret_value(
        SecretId=config['secret_arn'])['SecretString'])
    result = {'key': os.environ['AUDIT_KEY'], 'db_arn': config['db_arn'],
              'observed_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'ok': False}
    try:
        if secret.get('username') != 'ipgo_rds_auditor':
            raise ValueError('unexpected_database_user')
        # 3초 접속 제한, 고정 CA, verify-full. URL DSN/임의 SQL을 받지 않는다.
        with psycopg.connect(host=config['host'], port=5432, dbname=config['database'],
             user=secret['username'], password=secret['password'], connect_timeout=3,
             sslmode='verify-full', sslrootcert='/app/rds-ca.pem',
             application_name='ipgo-rds-audit', options='-c default_transaction_read_only=on') as conn:
            result.update(collect(conn, config['reference_run_id']))
        result['ok'] = True
    except Exception as error:
        result['error_type'] = type(error).__name__
    # 연결이 닫힌 뒤 기록한다. 동일 실행의 최초 결과는 덮어쓰지 않는다.
    boto3.client('s3', config=Config(retries={'total_max_attempts': 1})).put_object(
        Bucket=config['bucket'], Key=f"{config['result_prefix']}/{result['key']}.json",
        Body=json.dumps(result, sort_keys=True).encode(), ContentType='application/json',
        ServerSideEncryption='AES256', IfNoneMatch='*')
    print(json.dumps({'audit_completed': result['ok'], 'key': result['key']}))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    try:
        code = main()
    except Exception as error:
        print(json.dumps({'audit_completed': False, 'error_type': type(error).__name__}))
        code = 1
    raise SystemExit(code)
