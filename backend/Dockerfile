FROM python:3.12-slim-trixie AS runtime

WORKDIR /app

# CVE-2026-111497: fail the build if the security update is unavailable.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libcairo2 libbrotli1 \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' libbrotli1)" ge '1.1.0-2+deb13u1' \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

COPY app/ ./app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test
COPY tests ./tests
ENV DATABASE_URL=sqlite:////tmp/catppuccindock-test.db
CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]

FROM runtime AS production
