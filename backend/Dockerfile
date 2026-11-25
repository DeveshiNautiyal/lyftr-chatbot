# ---- build stage: resolve wheels once ----
FROM python:3.12-slim AS build
WORKDIR /w
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- runtime stage ----
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8000
COPY --from=build /install /usr/local
WORKDIR /srv
COPY app ./app
RUN useradd -m app && mkdir -p /data && chown app /data
USER app
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.asgi:app --host 0.0.0.0 --port ${PORT}"]
