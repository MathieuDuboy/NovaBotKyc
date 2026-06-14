#!/bin/bash
# Démarre l'environnement sandbox ISOLÉ du bot KYC (Bot A) :
#   1. Infra Docker dédiée (projet nova_kyc : MySQL 3308 / Mongo 27019 / Redis 6382)
#   2. App FastAPI (port 3003) en arrière-plan
#   3. Tunnel HTTPS localhost.run (affiche l'URL ….lhr.life)
# Distinct de nova_sbx (pikabao/3001) et nova_il (interlace/3002).
# (ngrok free = 1 domaine, déjà pris par interlace_bot -> on utilise localhost.run ici.)
# Usage : ./start_sandbox.sh

set -e
cd "$(dirname "$0")"
ROOT="$(pwd)"
MYSQL_PWD="SFdsfg2345-dsfsa342"

echo "▶ 1/3 Infra Docker (nova_kyc)…"
docker compose -f config/docker-compose.sandbox.yml -p nova_kyc up -d >/dev/null
echo -n "   attente MySQL "
until docker exec nova_kyc_mysql mysqladmin ping -h localhost -u root -p"$MYSQL_PWD" --silent >/dev/null 2>&1; do
  echo -n "."; sleep 2
done
echo " OK"

echo "▶ 2/3 App KYC (port 3003)…"
pkill -9 -f "uvicorn app:app --host 127.0.0.1 --port 3003" 2>/dev/null || true
sleep 1
export PYTHONPATH="$ROOT"
export WORKER_ID=0
nohup ./venv/bin/uvicorn app:app --host 127.0.0.1 --port 3003 > /tmp/nova_kyc_app.log 2>&1 &
echo -n "   attente démarrage app "
for i in $(seq 1 30); do
  grep -q "Application startup complete" /tmp/nova_kyc_app.log 2>/dev/null && { echo " OK"; break; }
  grep -qiE "Traceback|Address already in use" /tmp/nova_kyc_app.log && { echo " ⚠️ erreur — voir /tmp/nova_kyc_app.log"; break; }
  echo -n "."; sleep 2
done
echo "   (logs: /tmp/nova_kyc_app.log)"

echo "▶ 3/3 Tunnel HTTPS localhost.run — copie l'URL ….lhr.life dans params.json (api.miniapp_url)."
echo "      → mini app KYC : https://<url>/kyc"
echo "      → Ctrl+C coupe le tunnel (l'app reste up)."
echo "──────────────────────────────────────────────────────────────"
exec ssh -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 \
         -o ExitOnForwardFailure=yes -R 80:localhost:3003 localhost.run
