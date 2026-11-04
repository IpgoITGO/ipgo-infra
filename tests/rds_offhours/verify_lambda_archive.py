"""실제 로컬 zip의 파일 목록·Lambda 읽기 권한을 검사한다."""
import json
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    expected = {'controller.py', 'dispatcher.py', 'policy.py', 'aws_api.py', 'failure_guard.py', 'audit.py'}
    assert set(archive.namelist()) == expected
    for info in archive.infolist():
        assert (info.external_attr >> 16) & 0o777 == 0o644, info.filename
print(json.dumps({'source': 'LOCAL_LAMBDA_ZIP', 'modules': len(expected), 'mode': '0644',
                  'cache_ca_secret_included': False}))
