# --build-arg PYTHON_IMAGE=python@sha256:<검증한digest> 지정이 필요하다.
ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE}
WORKDIR /app
COPY --chmod=0444 requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
# CAは公式RDS bundleを別途取得し、承認したSHA256と照合してからビルドcontextに置く。
COPY --chmod=0444 rds-ca.pem /app/rds-ca.pem
COPY --chmod=0444 audit.py /app/audit.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 65534:65534
ENTRYPOINT ["python", "/app/audit.py"]
