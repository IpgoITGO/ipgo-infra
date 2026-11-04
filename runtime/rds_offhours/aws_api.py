"""실제 연결 어댑터. AWS 호출은 배포된 Lambda entrypoint에서만 생성한다."""
import datetime as dt
import json

from policy import KST, digest, fresh, timestamp

EXPECTED_DB_CONFIGURATION = {
    'Engine': 'postgres', 'EngineVersion': '16.15', 'DBInstanceClass': 'db.t4g.micro',
    'AllocatedStorage': 20, 'StorageType': 'gp3', 'StorageEncrypted': True,
    'MultiAZ': False, 'PubliclyAccessible': False, 'DeletionProtection': True,
    'BackupRetentionPeriod': 7, 'AutoMinorVersionUpgrade': True,
    'PreferredBackupWindow': '17:47-18:17',
    'PreferredMaintenanceWindow': 'sat:16:26-sat:16:56',
}


class AWS:
    def __init__(self, config, client):
        self.c = config
        self.client = client

    def now(self):
        return dt.datetime.now(dt.timezone.utc)

    def database(self):
        return self.client('rds').describe_db_instances(
            DBInstanceIdentifier=self.c['db_id'])['DBInstances'][0]

    def start(self):
        self.client('rds').start_db_instance(DBInstanceIdentifier=self.c['db_id'])

    def stop(self):
        self.client('rds').stop_db_instance(DBInstanceIdentifier=self.c['db_id'])

    def warn(self, key, reason):
        self.client('sns').publish(TopicArn=self.c['alarm_topic_arn'],
            Subject='RDS prestart needs attention',
            Message=json.dumps({'execution_key': key, 'reason': reason,
                                'existing_schedules_changed': False}))

    def read_json(self, key, version=None):
        args = {'Bucket': self.c['bucket'], 'Key': key}
        if version:
            args['VersionId'] = version
        response = self.client('s3').get_object(**args)
        raw = response['Body'].read(65537)
        if len(raw) > 65536:
            raise ValueError('oversized_evidence')
        return json.loads(raw)

    def manifest(self, now):
        m = self.read_json(self.c['manifest_key'], self.c['manifest_version'])
        if type(m.get('schema')) is not int or m['schema'] != 1:
            raise ValueError('unknown_manifest_schema')
        if digest(m) != self.c['manifest_sha256'] or m['revision'] != self.c['revision']:
            raise ValueError('manifest_digest_or_revision_mismatch')
        if not timestamp(m['valid_from']) <= now < timestamp(m['valid_until']):
            raise ValueError('manifest_expired')
        if m['db_arn'] != self.c['db_arn']:
            raise ValueError('manifest_target_mismatch')
        if m.get('db_configuration') != EXPECTED_DB_CONFIGURATION:
            raise ValueError('manifest_configuration_incomplete_or_changed')
        if not m.get('origins_sha256') or any(type(v) is not str or len(v) != 64
                or any(c not in '0123456789abcdef' for c in v) for v in m['origins_sha256'].values()):
            raise ValueError('original_evidence_missing')
        return m

    def proof(self, db, now, own_task=None, key=None):
        m = self.manifest(now)
        proof = dict(m['prerequisites'])
        proof['observed_at'] = now.isoformat()
        proof['rds_configuration_matches'] = all(db.get(k) == v for k, v in m['db_configuration'].items())
        proof['rds_configuration_matches'] &= (
            not db.get('PendingModifiedValues') and not db.get('ReadReplicaDBInstanceIdentifiers')
            and not db.get('ReadReplicaSourceDBInstanceIdentifier'))
        actions = self.client('rds').describe_pending_maintenance_actions(
            ResourceIdentifier=self.c['db_arn'])['PendingMaintenanceActions']
        proof['maintenance_not_pending'] = not actions
        snapshots = self.pages('rds', 'describe_db_snapshots', 'DBSnapshots',
                               DBInstanceIdentifier=self.c['db_id'], SnapshotType='automated')
        earliest = now.astimezone(KST).replace(hour=2, minute=47, second=0, microsecond=0)
        latest = db.get('LatestRestorableTime')
        proof['backup_completed_today'] = (latest is not None and earliest <= latest <= now
            and any(s['Status'] == 'available' and earliest <= s['SnapshotCreateTime'] <= now
                    for s in snapshots))
        hosts = self.client('ec2').describe_instances(InstanceIds=self.c['writer_instance_ids'])
        actual_hosts = {i['InstanceId']: i['State']['Name'] for r in hosts['Reservations'] for i in r['Instances']}
        proof['all_writer_hosts_stopped'] = (set(actual_hosts) == set(self.c['writer_instance_ids'])
                                                            and set(actual_hosts.values()) == {'stopped'})
        # 모든 live/pending task를 본다. 종료한 호스트 위 EC2 task의 오래된 RUNNING은 별도 판정.
        tasks = set()
        for status in ('RUNNING', 'PENDING'):
            tasks.update(self.pages('ecs', 'list_tasks', 'taskArns', token='nextToken',
                                    cluster=self.c['cluster_arn'], desiredStatus=status))
        proof['no_standalone_writer'] = True
        for arn in sorted(tasks):
            if arn == own_task:
                self.owned_task(arn, key)
                continue
            t = self.client('ecs').describe_tasks(cluster=self.c['cluster_arn'], tasks=[arn])['tasks']
            if len(t) != 1:
                raise ValueError('task_not_visible')
            t = t[0]
            if t.get('launchType') == 'FARGATE':
                # 그 외 Fargate 작업은 용도를 추정하지 않고 중지를 차단한다.
                proof['no_standalone_writer'] = False
                continue
            if t.get('launchType') != 'EC2' or not t.get('group', '').startswith('service:'):
                proof['no_standalone_writer'] = False
                continue
            ci = self.client('ecs').describe_container_instances(
                cluster=self.c['cluster_arn'], containerInstances=[t['containerInstanceArn']])['containerInstances']
            if len(ci) != 1 or actual_hosts.get(ci[0]['ec2InstanceId']) != 'stopped':
                proof['no_standalone_writer'] = False
        proof['source_matches'], proof['llm_disabled'] = self.sources_match(m)
        proof['registry_matches'] = self.schedules_match(m)
        executions = self.pages('stepfunctions', 'list_executions', 'executions', token='nextToken',
                                stateMachineArn=self.c['state_machine_arn'], statusFilter='RUNNING')
        proof['no_conflicting_lease'] = (len(executions) == 1 and key is not None
                                        and executions[0].get('name') == key)
        # 비동기 failure guard 지연/전달 실패만으로 중지를 재개하지 않는다.
        reviewed = set(m.get('reviewed_failed_execution_arns', []))
        for status in ('FAILED', 'TIMED_OUT', 'ABORTED'):
            failures = self.pages('stepfunctions', 'list_executions', 'executions', token='nextToken',
                                  stateMachineArn=self.c['state_machine_arn'], statusFilter=status)
            proof['no_conflicting_lease'] &= all(x['executionArn'] in reviewed for x in failures)
        return proof

    def sources_match(self, manifest):
        expected_services = {arn.rsplit('/', 1)[-1] for arn in self.c['service_arns']}
        if set(manifest['service_definitions']) != expected_services:
            return False, False
        actual = {}
        llm_off, explicit_disable = True, False
        for service, expected in manifest['service_definitions'].items():
            s = self.client('ecs').describe_services(cluster=self.c['cluster_arn'], services=[service])['services']
            if len(s) != 1 or s[0]['taskDefinition'] not in self.c['service_task_arns']:
                return False, False
            td = self.client('ecs').describe_task_definition(taskDefinition=s[0]['taskDefinition'])['taskDefinition']
            actual[service] = digest(td['containerDefinitions'])
            for container in td['containerDefinitions']:
                for e in container.get('environment', []):
                    if 'LLM' in e['name'] or 'OPENAI' in e['name']:
                        if e['name'] in ('LLM_ENABLED', 'OPENAI_ENABLED'):
                            llm_off &= e['value'].lower() == 'false'
                            explicit_disable |= e['value'].lower() == 'false'
                        elif 'KEY' in e['name'] or 'TOKEN' in e['name']:
                            llm_off = False
                llm_off &= not any(('OPENAI' in e['name'] or 'LLM' in e['name'])
                                    for e in container.get('secrets', []))
        return bool(actual) and actual == manifest['service_definitions'], bool(actual) and llm_off and explicit_disable

    def schedules_match(self, manifest):
        # 기존 group은 실측 manifest에서 명시한다. default로 추정하지 않는다.
        expected = {tuple(arn.split(':schedule/', 1)[1].split('/', 1))
                    for arn in self.c['existing_schedule_arns']}
        actual_bindings = {(s['group'], s['name']) for s in manifest['existing_schedules']}
        if len(expected) != 2 or len(manifest['existing_schedules']) != 2 or actual_bindings != expected:
            return False
        for s in manifest['existing_schedules']:
            actual = self.client('scheduler').get_schedule(Name=s['name'], GroupName=s['group'])
            binding = {k: actual[k] for k in ('State', 'ScheduleExpression', 'ScheduleExpressionTimezone', 'Target')}
            if digest(binding) != s['sha256']:
                return False
        return True

    def pages(self, service, method, field, token='Marker', **kwargs):
        result = []
        while True:
            response = getattr(self.client(service), method)(**kwargs)
            result += response[field]
            marker = response.get(token)
            if not marker:
                return result
            kwargs[token] = marker

    def empty_queues(self):
        if len(set(self.c['queue_urls'])) != 4:
            return False
        for url in self.c['queue_urls']:
            a = self.client('sqs').get_queue_attributes(QueueUrl=url, AttributeNames=[
                'ApproximateNumberOfMessages', 'ApproximateNumberOfMessagesNotVisible',
                'ApproximateNumberOfMessagesDelayed'])['Attributes']
            expected = {'ApproximateNumberOfMessages', 'ApproximateNumberOfMessagesNotVisible', 'ApproximateNumberOfMessagesDelayed'}
            if set(a) != expected or set(a.values()) != {'0'}:
                return False
        return True

    def connections_zero(self, closed_at, now):
        closed = timestamp(closed_at)
        data = self.client('cloudwatch').get_metric_statistics(Namespace='AWS/RDS',
            MetricName='DatabaseConnections', Dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': self.c['db_id']}],
            StartTime=closed, EndTime=now, Period=60, Statistics=['Maximum'])['Datapoints']
        points = [p for p in data if p['Timestamp'] >= closed
                  and fresh(p['Timestamp'].isoformat(), now, 180)]
        return bool(points) and all(type(p.get('Maximum')) in (float, int)
                                    and p['Maximum'] == 0 for p in points)

    def launch_audit(self, key):
        response = self.client('ecs').run_task(cluster=self.c['cluster_arn'],
            taskDefinition=self.c['audit_task_arn'], launchType='FARGATE', count=1,
            clientToken=key, startedBy='ipgo-rds-audit', group='ipgo-rds-audit',
            tags=[{'key': 'Controller', 'value': self.c['name']}],
            networkConfiguration={'awsvpcConfiguration': {
                'subnets': self.c['audit_subnets'], 'securityGroups': self.c['audit_security_groups'],
                'assignPublicIp': 'DISABLED'}},
            overrides={'containerOverrides': [{'name': 'audit', 'environment': [{'name': 'AUDIT_KEY', 'value': key}]}]})
        if response.get('failures') or len(response.get('tasks', [])) != 1:
            raise ValueError('audit_launch_failed')
        return response['tasks'][0]['taskArn']

    def owned_task(self, arn, key):
        tasks = self.client('ecs').describe_tasks(cluster=self.c['cluster_arn'], tasks=[arn])['tasks']
        if len(tasks) != 1:
            raise ValueError('audit_task_unknown')
        t = tasks[0]
        env = t.get('overrides', {}).get('containerOverrides', [])
        if (t.get('taskDefinitionArn') != self.c['audit_task_arn'] or t.get('startedBy') != 'ipgo-rds-audit'
            or t.get('group') != 'ipgo-rds-audit' or t.get('launchType') != 'FARGATE'
            or not any(e.get('name') == 'AUDIT_KEY' and e.get('value') == key
                       for c in env for e in c.get('environment', []))):
            raise ValueError('audit_ownership_mismatch')
        return t

    def cleanup_audit(self, arn, key):
        if arn:
            t = self.owned_task(arn, key)
            if t['lastStatus'] != 'STOPPED':
                self.client('ecs').stop_task(cluster=self.c['cluster_arn'], task=arn, reason='fixed audit deadline')

    def audit_stopped(self, arn, key):
        return self.owned_task(arn, key)['lastStatus'] == 'STOPPED'

    def audit_result(self, arn, key, now):
        t = self.owned_task(arn, key)
        if t['lastStatus'] != 'STOPPED':
            return None
        containers = t.get('containers', [])
        if len(containers) != 1 or containers[0].get('exitCode') != 0:
            raise ValueError('audit_exit_failed')
        expected_image = self.c['audit_image'].split('@')[-1]
        if containers[0].get('imageDigest') != expected_image:
            raise ValueError('audit_image_mismatch')
        audit = self.read_json(f"{self.c['result_prefix']}/{key}.json")
        self.verify_audit(audit, key, now)
        return audit

    def verify_audit(self, audit, key, now):
        m = self.manifest(now)
        if (audit.get('key') != key or audit.get('db_arn') != self.c['db_arn']
            or not fresh(audit.get('observed_at'), now, 300)
            or any(audit.get(k) is not True for k in ('ok', 'read_only', 'tls_verified'))
            or audit.get('schema_sha256') != m['schema_sha256']
            or audit.get('reference_sha256') != m['reference_sha256']
            or any(type(audit.get(k)) is not int or audit[k] != 0 for k in
                   ('active_engine_jobs', 'open_business_transactions', 'llm_explanation_violations'))):
            raise ValueError('audit_evidence_invalid')
