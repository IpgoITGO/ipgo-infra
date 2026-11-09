"""공개 artifact에는 암호화 plan만. 복호화는 NAS 로컬에서만 수행한다."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path

PUBLIC_KEY = Path(__file__).with_name('d0-plan-public-key.pem')


def seal(data, context, public):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not isinstance(public, rsa.RSAPublicKey) or public.key_size < 3072:
        raise ValueError('PUBLIC_KEY_BOUNDARY')
    key, nonce = os.urandom(32), os.urandom(12)
    header = {'version': 1, 'context': context, 'plainSha256': hashlib.sha256(data).hexdigest()}
    aad = json.dumps(header, sort_keys=True, separators=(',', ':')).encode()
    return {**header, 'nonce': base64.b64encode(nonce).decode(),
            'wrappedKey': base64.b64encode(public.encrypt(key, padding.OAEP(
                mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))).decode(),
            'ciphertext': base64.b64encode(AESGCM(key).encrypt(nonce, data, aad)).decode()}


def unseal(envelope, private):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if set(envelope) != {'version','context','plainSha256','nonce','wrappedKey','ciphertext'} or envelope['version'] != 1:
        raise ValueError('ENVELOPE_SCHEMA')
    header = {k: envelope[k] for k in ('version','context','plainSha256')}
    aad = json.dumps(header, sort_keys=True, separators=(',', ':')).encode()
    key = private.decrypt(base64.b64decode(envelope['wrappedKey'], validate=True), padding.OAEP(
        mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    plain = AESGCM(key).decrypt(base64.b64decode(envelope['nonce'], validate=True),
                               base64.b64decode(envelope['ciphertext'], validate=True), aad)
    if hashlib.sha256(plain).hexdigest() != envelope['plainSha256']:
        raise ValueError('PLAN_HASH')
    return plain


def main():
    from cryptography.hazmat.primitives import serialization
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['seal','unseal'])
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('--private-key')
    args = parser.parse_args()
    os.umask(0o077)
    if args.mode == 'seal':
        from d0_plan_guard import review
        raw = Path(args.input).read_bytes()
        digest = review(json.loads(raw), revoke=os.environ.get('REVOKE_RUNTIME')=='true')['planSha256']
        key = serialization.load_pem_public_key(PUBLIC_KEY.read_bytes())
        context = {'workflowSha': os.environ['GITHUB_SHA'], 'runId': os.environ['GITHUB_RUN_ID'], 'planSha256': digest}
        output = json.dumps(seal(raw, context, key), sort_keys=True).encode()
    else:
        key = serialization.load_pem_private_key(Path(args.private_key).read_bytes(), password=None)
        expected = serialization.load_pem_public_key(PUBLIC_KEY.read_bytes()).public_numbers()
        if key.public_key().public_numbers() != expected:
            raise ValueError('NAS_PRIVATE_KEY_MISMATCH')
        output = unseal(json.loads(Path(args.input).read_bytes()), key)
    with open(args.output, 'xb', opener=lambda path, flags: os.open(path, flags, 0o600)) as file:
        file.write(output)
    print('D0 plan envelope 처리 완료. plan/키 내용 출력 없음.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('D0 plan envelope 검증 실패. 적용하지 마세요.')
        raise SystemExit(1) from None
