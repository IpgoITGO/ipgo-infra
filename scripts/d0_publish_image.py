"""승인된 helper 이미지의 새 태그만 게시하기 위한 사전/사후 검사."""
import hashlib
import json
import os
import re
import sys
from pathlib import Path


def new_tag(client, tag):
    if not re.fullmatch('d0-[a-f0-9]{40}', tag):
        raise ValueError('IMAGE_TAG')
    try:
        client.describe_images(repositoryName='ipgo-dev/database', imageIds=[{'imageTag':tag}])
    except client.exceptions.ImageNotFoundException:
        return
    raise ValueError('EXISTING_TAG_REVIEW_REQUIRED')


if __name__ == '__main__':
    import boto3
    from botocore.config import Config
    try:
        helper=os.environ['HELPER_SHA']
        if not re.fullmatch('[a-f0-9]{40}',helper):raise ValueError('HELPER_SHA')
        client=boto3.client('ecr',region_name='ap-northeast-2',config=Config(retries={'total_max_attempts':1}))
        tag='d0-'+helper
        if sys.argv[1]=='check':
            new_tag(client,tag)
            print('새 D0 image tag 확인. 기존 tag는 덮어쓰지 않습니다.')
        elif sys.argv[1]=='record':
            details=client.describe_images(repositoryName='ipgo-dev/database',imageIds=[{'imageTag':tag}])['imageDetails']
            if len(details)!=1 or not re.fullmatch('sha256:[a-f0-9]{64}',details[0]['imageDigest']):raise ValueError('IMAGE_DIGEST')
            out={'helperSha':helper,'imageDigest':details[0]['imageDigest'],
                 'dockerfileSha256':hashlib.sha256(Path('server/Dockerfile.d0').read_bytes()).hexdigest(),
                 'publicKeyPemSha256':hashlib.sha256(Path('server/scripts/d0/public-key.pem').read_bytes()).hexdigest()}
            Path(os.environ['RUNNER_TEMP']+'/d0-image-digest.json').write_text(json.dumps(out,sort_keys=True))
            print(json.dumps(out,sort_keys=True))
        else:raise ValueError('MODE')
    except Exception:
        print('D0 image 검사 실패. 기존 tag를 덮어쓰거나 다른 저장소로 우회하지 않습니다.')
        raise SystemExit(1) from None
