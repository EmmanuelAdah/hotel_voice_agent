#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════════
# deploy.sh — Production deployment script for Hotel Voice Agent
# Usage: ./scripts/deploy.sh [--no-migrate] [--no-build]
# ════════════════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"

NO_MIGRATE=false
NO_BUILD=false

for arg in "$@"; do
    case $arg in
        --no-migrate) NO_MIGRATE=true ;;
        --no-build)   NO_BUILD=true ;;
    esac
done

echo "════════════════════════════════════════════════════"
echo " Hotel Voice Agent — Production Deploy"
echo "════════════════════════════════════════════════════"

# ── Validate environment ───────────────────────────────────────────────────────
if [ ! -f "$ROOT_DIR/.env" ]; then
    echo "❌  ERROR: .env file not found. Copy .env.example and fill in values."
    exit 1
fi

source "$ROOT_DIR/.env"
required_vars=(DJANGO_SECRET_KEY DB_PASSWORD OPENAI_API_KEY REDIS_URL)
for var in "${required_vars[@]}"; do
    if [ -z "${!var:-}" ]; then
        echo "❌  ERROR: Required env var '$var' is not set."
        exit 1
    fi
done

echo "✅  Environment validated"

# ── Pull latest images ─────────────────────────────────────────────────────────
echo "📦  Pulling base images..."
docker compose -f "$COMPOSE_FILE" pull postgres redis kafka zookeeper prometheus grafana

# ── Build application image ────────────────────────────────────────────────────
if [ "$NO_BUILD" = false ]; then
    echo "🔨  Building application image..."
    docker compose -f "$COMPOSE_FILE" build \
        --build-arg BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        web daphne celery_worker celery_beat kafka_consumer
    echo "✅  Image built"
fi

# ── Start infrastructure first ─────────────────────────────────────────────────
echo "🚀  Starting infrastructure services..."
docker compose -f "$COMPOSE_FILE" up -d postgres redis zookeeper kafka
echo "⏳  Waiting for infrastructure to be healthy..."
sleep 15

# ── Run migrations ─────────────────────────────────────────────────────────────
if [ "$NO_MIGRATE" = false ]; then
    echo "🗄️   Running database migrations..."
    docker compose -f "$COMPOSE_FILE" run --rm \
        -e DJANGO_SETTINGS_MODULE=hotel_agent.settings.production \
        web python manage.py migrate --noinput
    echo "✅  Migrations complete"
fi

# ── Setup Kafka topics ─────────────────────────────────────────────────────────
echo "📨  Setting up Kafka topics..."
docker compose -f "$COMPOSE_FILE" run --rm \
    web python manage.py shell -c \
    "from hotel_agent.kafka.producer_consumer import setup_kafka_topics; setup_kafka_topics()"
echo "✅  Kafka topics ready"

# ── Collect static files ───────────────────────────────────────────────────────
echo "📂  Collecting static files..."
docker compose -f "$COMPOSE_FILE" run --rm web python manage.py collectstatic --noinput
echo "✅  Static files collected"

# ── Deploy application ─────────────────────────────────────────────────────────
echo "🚀  Deploying application services..."
docker compose -f "$COMPOSE_FILE" up -d \
    web daphne celery_worker celery_beat kafka_consumer \
    nginx prometheus grafana \
    kafka_exporter postgres_exporter redis_exporter

# ── Health check ───────────────────────────────────────────────────────────────
echo "⏳  Waiting for application to start (30s)..."
sleep 30

echo "🏥  Running health check..."
HEALTH_URL="http://localhost/api/v1/health/"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL" || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo "✅  Health check passed (HTTP 200)"
else
    echo "⚠️   Health check returned HTTP $HTTP_CODE — check logs with: docker compose logs web"
fi

echo ""
echo "════════════════════════════════════════════════════"
echo " ✅  Deployment complete!"
echo ""
echo " 🌐  API:      http://localhost/api/v1/"
echo " 📊  Grafana:  http://localhost:3000  (admin/\$GRAFANA_PASSWORD)"
echo " 🔥  Prometheus: http://localhost:9090"
echo " 📋  Logs:     docker compose logs -f web"
echo "════════════════════════════════════════════════════"
