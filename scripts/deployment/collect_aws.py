"""공식 AWS MCP run_script에 전달할 읽기 전용 수집 함수. 로컬 AWS 실행 금지.

파일 뒤에 result = await collect_deployment(...), 마지막 줄 result를 붙인다.
환경값/Secret값/로그 본문은 반환하지 않는다. IAM/서비스 쓰기는 포함하지 않는다.
"""


async def collect_deployment(region, cluster, baseline_tds=None):
    identity, regions = await asyncio.gather(call_boto3(
        service_name="sts", operation_name="GetCallerIdentity", region_name=region
    ), call_boto3(
        service_name="ec2", operation_name="DescribeRegions", region_name=region,
        params={"RegionNames": [region]},
    ), return_exceptions=True)
    if any(isinstance(x, Exception) for x in (identity, regions)):
        raise ValueError("IDENTITY_REGION_READ_FAILED")
    listed, listed_tasks = await asyncio.gather(call_boto3(
        service_name="ecs", operation_name="ListServices", region_name=region,
        params={"cluster": cluster},
    ), call_boto3(
        service_name="ecs", operation_name="ListTasks", region_name=region,
        params={"cluster": cluster},
    ), return_exceptions=True)
    if any(isinstance(x, Exception) for x in (listed, listed_tasks)):
        raise ValueError("RESOURCE_LIST_READ_FAILED")
    if any(x.get("nextToken") or x.get("NextToken") for x in (listed, listed_tasks)):
        raise ValueError("RESOURCE_LIST_PAGINATION_INCOMPLETE")
    if not 0 < len(listed["serviceArns"]) <= 10 or len(listed_tasks["taskArns"]) > 100:
        raise ValueError("CLUSTER_SCOPE_REVIEW_REQUIRED")

    async def describe_tasks():
        if not listed_tasks["taskArns"]:
            return {"tasks": []}
        return await call_boto3(service_name="ecs", operation_name="DescribeTasks", region_name=region,
                                params={"cluster": cluster, "tasks": listed_tasks["taskArns"]})

    services, tasks = await asyncio.gather(call_boto3(
        service_name="ecs", operation_name="DescribeServices", region_name=region,
        params={"cluster": cluster, "services": listed["serviceArns"]},
    ), describe_tasks(), return_exceptions=True)
    if any(isinstance(x, Exception) or x.get("failures") for x in (services, tasks)):
        raise ValueError("SERVICE_TASK_READ_INCOMPLETE")
    if (len(services["services"]) != len(listed["serviceArns"])
            or len(tasks["tasks"]) != len(listed_tasks["taskArns"])):
        raise ValueError("RESOURCE_DETAILS_INCOMPLETE")
    arns = sorted({s["taskDefinition"] for s in services["services"]}
                  | set((baseline_tds or {}).values()))
    data = await asyncio.gather(*[call_boto3(
            service_name="ecs", operation_name="DescribeTaskDefinition", region_name=region,
            params={"taskDefinition": arn},
        ) for arn in arns], return_exceptions=True)
    if any(isinstance(x, Exception) for x in data):
        raise ValueError("TASK_DEFINITION_READ_INCOMPLETE")
    definitions = {arn: item["taskDefinition"] for arn, item in zip(arns, data)}

    def normalized(td):
        ignored = {"taskDefinitionArn", "revision", "registeredAt", "registeredBy",
                   "status", "requiresAttributes", "compatibilities"}
        out = {k: v for k, v in td.items() if k not in ignored}
        out["containerDefinitions"] = []
        for container in sorted(td["containerDefinitions"], key=lambda c: c["name"]):
            c = dict(container)
            for key in ("environment", "secrets"):
                if key in c:
                    c[key] = sorted(c[key], key=lambda e: e["name"])
            out["containerDefinitions"].append(c)
        return out

    rows = []
    for service in services["services"]:
        name = service["serviceName"]
        arn = service["taskDefinition"]
        td = definitions[arn]
        changes = None
        baseline = (baseline_tds or {}).get(name)
        if baseline:
            old, new = normalized(definitions[baseline]), normalized(td)
            changes = [k for k in sorted(set(old) | set(new))
                       if k != "containerDefinitions" and old.get(k) != new.get(k)]
            old_cs = {c["name"]: c for c in old["containerDefinitions"]}
            new_cs = {c["name"]: c for c in new["containerDefinitions"]}
            if set(old_cs) != set(new_cs):
                changes.append("container_names")
            for cname in sorted(set(old_cs) & set(new_cs)):
                a, b = old_cs[cname], new_cs[cname]
                changes.extend("container." + cname + "." + k
                               for k in sorted(set(a) | set(b)) if k != "environment" and a.get(k) != b.get(k))
                ae = {e["name"]: e["value"] for e in a.get("environment", [])}
                be = {e["name"]: e["value"] for e in b.get("environment", [])}
                changes.extend("container." + cname + ".environment." + k
                               for k in sorted(set(ae) | set(be)) if ae.get(k) != be.get(k))
        rows.append({
            "name": name, "td": arn, "desired": service["desiredCount"],
            "running": service["runningCount"], "pending": service["pendingCount"],
            "deployment_configuration": service["deploymentConfiguration"],
            "grace": service.get("healthCheckGracePeriodSeconds", 0),
            "baseline_td": baseline, "changed_paths": changes,
            "settings": {e["name"]: e["value"]
                         for c in td["containerDefinitions"] for e in c.get("environment", [])
                         if e["name"] in {
                             "ENGINE_MODE", "IPGO_EMBEDDED_WORKER_ENABLED", "IPGO_LLM_CONTINUOUS_ENABLED",
                             "IPGO_LLM_EXPIRES_AT", "IPGO_ENGINE_ENABLED", "IPGO_INSIGHT_ENABLED",
                             "IPGO_INSIGHT_WORKER_ENABLED", "IPGO_INSIGHT_DEMO_STARTS_AT",
                             "IPGO_INSIGHT_DEMO_EXPIRES_AT", "IPGO_INSIGHT_MONTHLY_BUDGET_ENABLED",
                             "IPGO_INSIGHT_MONTHLY_BUDGET_USD", "IPGO_INSIGHT_BATCH_ENABLED",
                             "IPGO_INSIGHT_SINGLE_RESULT_ENABLED", "SPRING_FLYWAY_ENABLED"}},
            "deployments": [{"status": d["status"], "rollout": d.get("rolloutState"),
                             "failed": d.get("failedTasks"), "td": d["taskDefinition"]}
                            for d in service["deployments"]],
            "http_health_check": any(
                ("8080/actuator/health" if name.endswith("server") else "8000/health")
                in " ".join(c.get("healthCheck", {}).get("command", []))
                for c in td["containerDefinitions"] if c["name"] in ("server", "ai-api")),
        })
    return {
        "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "account": identity["Account"], "region": region,
        "region_confirmed": any(r["RegionName"] == region for r in regions["Regions"]),
        "cluster": cluster, "services": rows,
        "tasks": [{"service": t.get("group", "").removeprefix("service:"),
                   "td": t["taskDefinitionArn"], "status": t["lastStatus"],
                   "health": t.get("healthStatus"),
                   "containers": [{"name": c["name"], "image": c.get("image"),
                                   "digest": c.get("imageDigest"), "health": c.get("healthStatus")}
                                  for c in t["containers"]]}
                  for t in tasks["tasks"]],
    }
