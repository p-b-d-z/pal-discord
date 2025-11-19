#!/bin/bash
# This script is used to build and run the PAL container locally.
# Requirements:
#   - Docker
#   - Environment variables stored in .env file
#   - Pre-commit

cleanup() {
  docker stop paldiscord
}
trap cleanup EXIT

if [ -z "$SLACK_BOT_TOKEN" ]; then
  echo "[INFO] Environment variables not detected, loading from file."
  source .env
else
  echo "[INFO] Environment variables detected."
fi
echo "[INFO] Building paldiscord..."
docker build -f Dockerfile . --tag paldiscord
echo "[INFO] Launching paldiscord [${ENVIRONMENT}]..."
docker run --rm \
  --name 'paldiscord' \
  --network host \
  -p 5000:5000 \
  -v ./:/etc/palbot/ \
  -e DISCORD_TOKEN="$DISCORD_TOKEN" \
  -e OPENAI_API_KEY="$OPENAI_API_KEY" \
  -e OPENAI_BASE_URL="$OPENAI_BASE_URL" \
  -e OPENAI_MODEL="$OPENAI_MODEL" \
  -e LOG_LEVEL="$LOG_LEVEL" \
  -e ENVIRONMENT="$ENVIRONMENT" \
  -e REGION="$REGION" \
  paldiscord
