"""Report host memory from a small, isolated container using the node IAM role."""
import pathlib
import urllib.request

import boto3

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
request = urllib.request.Request(
    "http://169.254.169.254/latest/api/token",
    data=b"",
    method="PUT",
    headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
)
with opener.open(request, timeout=2) as response:
    token = response.read().decode()
request = urllib.request.Request(
    "http://169.254.169.254/latest/meta-data/instance-id",
    headers={"X-aws-ec2-metadata-token": token},
)
with opener.open(request, timeout=2) as response:
    instance_id = response.read().decode()
memory = {
    line.split(":", 1)[0]: int(line.split()[1])
    for line in pathlib.Path("/proc/meminfo").read_text().splitlines()
    if line.startswith(("MemTotal:", "MemAvailable:"))
}
boto3.client("cloudwatch").put_metric_data(
    Namespace="Ipgo/Onebox",
    MetricData=[{
        "MetricName": "MemoryAvailablePercent",
        "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
        "Value": memory["MemAvailable"] * 100 / memory["MemTotal"],
        "Unit": "Percent",
        "StorageResolution": 60,
    }],
)
print("Host memory metric sent")
