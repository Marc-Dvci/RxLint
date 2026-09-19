#!/usr/bin/env bash
# Deploy RxLint to a Nebius Serverless AI endpoint.
#
# Prerequisites: the nebius CLI is installed and authenticated, and the image is pushed to a
# registry the endpoint can pull from (Nebius Container Registry needs no credentials inside the
# same project).
#
#   export IMAGE=cr.<region>.nebius.cloud/<registry-id>/rxlint:0.1.0
#   export PLATFORM=<platform id>   # list with: nebius compute platform list
#   export PRESET=<preset>          # a CPU preset of that platform; RxLint needs no GPU
#   export NEBIUS_API_KEY=... TAVILY_API_KEY=...
#   ./infra/nebius/deploy.sh
set -euo pipefail

: "${IMAGE:?set IMAGE to the pushed rxlint image}"
: "${PLATFORM:?set PLATFORM (nebius compute platform list)}"
: "${PRESET:?set PRESET for that platform}"
: "${NEBIUS_API_KEY:?set NEBIUS_API_KEY for Token Factory}"
NAME="${NAME:-rxlint}"

nebius ai endpoint create \
  --name "$NAME" \
  --image "$IMAGE" \
  --container-port 8000 \
  --platform "$PLATFORM" \
  --preset "$PRESET" \
  --disk-size 40Gi \
  --env "RXLINT_MODEL_MODE=auto" \
  --env "NEBIUS_API_KEY=${NEBIUS_API_KEY}" \
  --env "TAVILY_API_KEY=${TAVILY_API_KEY:-}" \
  --public

ID=$(nebius ai endpoint get-by-name --name "$NAME" --format json | jq -r '.metadata.id')
echo "endpoint id: $ID"
nebius ai endpoint get "$ID" --format json | jq -r '.status.public_endpoints[] | select(startswith("https://"))' | head -1
