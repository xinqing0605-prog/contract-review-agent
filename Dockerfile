# 第一阶段：构建前端
FROM node:20-slim AS web
WORKDIR /app/web
COPY web/package.json ./
RUN npm install
COPY web/ ./
RUN npm run build

# 第二阶段：运行后端（同源托管前端产物）
FROM python:3.12-slim
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CLAUSEGUARD_DATA=/data

COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY --from=web /app/web/dist web/dist

RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8103
CMD ["sh", "-c", "python -m uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8103}"]
