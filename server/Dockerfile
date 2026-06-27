# Build context = repo root (see docker-compose.yml).

# 1) Build the React app
FROM node:20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY web/ ./
RUN npm run build

# 2) Python runtime serving the built web + the API
FROM python:3.11-slim AS app
WORKDIR /srv
COPY server/pyproject.toml ./
RUN pip install --no-cache-dir .
COPY server/app ./app
COPY --from=web /web/dist ./web_dist
ENV WEB_DIST=/srv/web_dist
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
