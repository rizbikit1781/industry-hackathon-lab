FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# libgomp1: OpenMP runtime for scikit-learn / OR-Tools wheels
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY civicsignal/ civicsignal/
COPY data/ data/

ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn civicsignal.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
