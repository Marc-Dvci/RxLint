# ---- web build
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- runtime
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RXLINT_MODEL_MODE=auto RXLINT_DATA=/data
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir -e .
COPY rulepacks ./rulepacks
COPY fixtures ./fixtures
COPY models ./models
COPY assets ./assets
COPY benchmarks ./benchmarks
COPY --from=web /web/dist ./web/dist
# Warm the OCR models into the image so the first request does not download them.
RUN python -c "from rapidocr_onnxruntime import RapidOCR; RapidOCR()"
RUN useradd -m rxlint && mkdir -p /data && chown rxlint /data
USER rxlint
EXPOSE 8000
CMD ["uvicorn", "rxlint.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
