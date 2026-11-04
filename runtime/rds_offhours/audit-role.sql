-- 적용은 별도 승인. 업무 테이블/기존 앱 role/자격증명을 변경하지 않는다.
-- 관리자가 로그인 자격증명을 Secret으로 별도 제공한 후 NOLOGIN을 변경한다.
BEGIN;
CREATE ROLE ipgo_rds_auditor NOLOGIN;
GRANT CONNECT ON DATABASE ipgo TO ipgo_rds_auditor;
GRANT USAGE ON SCHEMA public TO ipgo_rds_auditor;
GRANT SELECT ON public.flyway_schema_history, public.engine_jobs,
  public.calculation_runs, public.calculation_results, public.scenario_results,
  public.ai_explanations TO ipgo_rds_auditor;
CREATE FUNCTION public.rds_offhours_activity_v1()
RETURNS TABLE(open_transactions bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog
AS $$ SELECT count(*) FROM pg_catalog.pg_stat_activity
      WHERE datname = current_database() AND pid <> pg_backend_pid()
        AND backend_type = 'client backend' AND xact_start IS NOT NULL $$;
REVOKE ALL ON FUNCTION public.rds_offhours_activity_v1() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.rds_offhours_activity_v1() TO ipgo_rds_auditor;
ALTER ROLE ipgo_rds_auditor SET default_transaction_read_only = on;
ALTER ROLE ipgo_rds_auditor SET statement_timeout = '15s';
COMMIT;
