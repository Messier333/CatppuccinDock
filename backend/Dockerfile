FROM python:3.12-slim AS runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libcairo2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test
RUN pip install --no-cache-dir httpx
COPY tests ./tests
ENV DATABASE_URL=sqlite:////tmp/catppuccindock-test.db
CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]

FROM runtime AS production
