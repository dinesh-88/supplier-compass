#!/usr/bin/env bash
# Build the image, push it to Nebius Container Registry and run it as a Nebius serverless endpoint.
#
#   cp deploy.env.example deploy.env   # fill in
#   scripts/deploy_nebius.sh           # DEPLOY_ENV=other.env scripts/deploy_nebius.sh for another file
#
# Needs: nebius CLI (logged in), jq, docker with buildx. Secrets are passed to the endpoint with --env and are
# never printed by this script.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

die() { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
say() { printf '\033[1;36m==>\033[0m %s\n' "$*" >&2; }

# ---- config ---------------------------------------------------------------------
ENV_FILE="${DEPLOY_ENV:-deploy.env}"
[[ -f "$ENV_FILE" ]] || die "$ENV_FILE not found. Copy deploy.env.example to deploy.env and fill it in."
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

PLATFORM="${PLATFORM:-cpu-d3}"
PRESET="${PRESET:-4vcpu-16gb}"
DATA_DIR="${DATA_DIR:-/tmp/data}"
for v in REGION_ID REGISTRY_NAME ENDPOINT_NAME APP_USERS SESSION_SECRET; do
  [[ -n "${!v:-}" ]] || die "$v is empty in $ENV_FILE."
done
(( ${#SESSION_SECRET} >= 16 )) || die "SESSION_SECRET must be at least 16 characters."
[[ "$APP_USERS" != *change-me* ]] || die "Set a real password in APP_USERS (it still says change-me)."
[[ -n "${LLM_API_KEY:-}" ]] || say "LLM_API_KEY is empty: chat, research and memo prose will be off."
[[ -n "${TAVILY_API_KEY:-}" ]] || say "TAVILY_API_KEY is empty: company research will be off."

for t in nebius jq docker curl git; do command -v "$t" >/dev/null || die "$t is not installed."; done
docker buildx version >/dev/null 2>&1 || die "docker buildx is not available."
docker info >/dev/null 2>&1 || die "The Docker daemon is not running."

PARENT_ID="${PROJECT_ID:-$(nebius config get parent-id 2>/dev/null || true)}"
[[ -n "$PARENT_ID" ]] || die "No project: set PROJECT_ID in $ENV_FILE or a parent-id in your nebius profile."

# ---- existing endpoint? -----------------------------------------------------------
# The CLI has no update command for endpoints (create, delete, get, list, logs, restart, ssh, start, stop),
# so switching the image means deleting and re-creating, which may change the URL. Ask first.
REPLACE_ID=""
if out=$(nebius ai endpoint get-by-name --name "$ENDPOINT_NAME" --parent-id "$PARENT_ID" --format json 2>&1); then
  REPLACE_ID=$(jq -r '.metadata.id' <<<"$out")
  old_url=$(jq -r '[.status.public_endpoints[]? | select(startswith("https://"))][0] // "none"' <<<"$out")
  old_image=$(jq -r '.spec.image // "?"' <<<"$out")
  say "Endpoint '$ENDPOINT_NAME' already exists: $REPLACE_ID"
  say "  state $(jq -r '.status.state // "?"' <<<"$out"), image $old_image, URL $old_url"
  cat >&2 <<EOF

The Nebius CLI cannot update an endpoint's image (no 'nebius ai endpoint update').
To deploy the new image the endpoint must be DELETED and created again. Its URL may change,
so links you already shared (for example with the jury) may stop working.

EOF
  [[ -t 0 ]] || die "Not deleting without confirmation. Run this script in a terminal to confirm."
  read -r -p "Type the endpoint name ('$ENDPOINT_NAME') to delete and re-create it, anything else to stop: " answer
  [[ "$answer" == "$ENDPOINT_NAME" ]] || die "Stopped. Nothing was changed."
elif ! grep -q "NotFound" <<<"$out"; then
  die "Could not look up the endpoint: $out"
fi

# ---- registry -----------------------------------------------------------------------
REGISTRY_ID=$(nebius registry list --parent-id "$PARENT_ID" --all --format json \
  | jq -r --arg n "$REGISTRY_NAME" '[.items[]? | select(.metadata.name == $n)][0].metadata.id // empty')
if [[ -z "$REGISTRY_ID" ]]; then
  say "Creating Container Registry '$REGISTRY_NAME'"
  REGISTRY_ID=$(nebius registry create --name "$REGISTRY_NAME" --parent-id "$PARENT_ID" --format json | jq -r '.metadata.id')
  [[ -n "$REGISTRY_ID" && "$REGISTRY_ID" != null ]] || die "Registry creation returned no ID."
else
  say "Using Container Registry '$REGISTRY_NAME' ($REGISTRY_ID)"
fi
nebius registry configure-helper >/dev/null

# ---- build and push -------------------------------------------------------------------
TAG=$(git rev-parse --short HEAD)
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  say "Working tree has uncommitted changes; tagging the image $TAG-dirty."
  TAG="$TAG-dirty"
fi
IMAGE="cr.$REGION_ID.nebius.cloud/${REGISTRY_ID#registry-}/supplier-compass:$TAG"
say "Building and pushing $IMAGE (linux/amd64)"
docker buildx build --platform linux/amd64 --tag "$IMAGE" --push .

# ---- endpoint ---------------------------------------------------------------------------
if [[ -n "$REPLACE_ID" ]]; then
  say "Deleting endpoint $REPLACE_ID"
  nebius ai endpoint delete --id "$REPLACE_ID" >/dev/null
fi

SUBNET_ARGS=()
SUBNET_ID=$(nebius vpc subnet list --parent-id "$PARENT_ID" --all --format json 2>/dev/null \
  | jq -r '[.items[]? | select(.metadata.name | test("default"))][0].metadata.id // empty' || true)
if [[ -n "$SUBNET_ID" ]]; then
  SUBNET_ARGS=(--subnet-id "$SUBNET_ID")
else
  say "No subnet named 'default…' found; letting Nebius pick the project's default subnet."
fi

ENV_ARGS=(--env "DATA_DIR=$DATA_DIR" --env "COOKIE_SECURE=1")
for v in APP_USERS SESSION_SECRET LLM_BASE_URL LLM_API_KEY LLM_MODEL LLM_FAST_MODEL TAVILY_API_KEY; do
  [[ -n "${!v:-}" ]] && ENV_ARGS+=(--env "$v=${!v}")
done

# No --auth token: browsers cannot send it; the app's own login protects every /api route.
say "Creating endpoint '$ENDPOINT_NAME' on $PLATFORM / $PRESET"
nebius ai endpoint create \
  --name "$ENDPOINT_NAME" \
  --parent-id "$PARENT_ID" \
  --image "$IMAGE" \
  --platform "$PLATFORM" \
  --preset "$PRESET" \
  --public \
  --container-port 8080 \
  --disk-size 20Gi \
  ${SUBNET_ARGS[@]+"${SUBNET_ARGS[@]}"} \
  "${ENV_ARGS[@]}" \
  --async >/dev/null

# ---- wait, then check ---------------------------------------------------------------------
say "Waiting for the endpoint to be RUNNING (up to 20 minutes)"
URL=""
state=""
for _ in $(seq 1 120); do
  ep=$(nebius ai endpoint get-by-name --name "$ENDPOINT_NAME" --parent-id "$PARENT_ID" --format json 2>/dev/null || true)
  ep="${ep:-"{}"}"
  new_state=$(jq -r '.status.state // "PENDING"' <<<"$ep")
  [[ "$new_state" != "$state" ]] && say "  $new_state"
  state="$new_state"
  case "$state" in
    RUNNING)
      URL=$(jq -r '[.status.public_endpoints[]? | select(startswith("https://"))][0] // empty' <<<"$ep")
      [[ -n "$URL" ]] && break ;;
    ERROR | FAILED | STOPPED)
      ENDPOINT_ID=$(jq -r '.metadata.id' <<<"$ep")
      nebius ai endpoint logs "$ENDPOINT_ID" --tail 50 >&2 || true
      die "Endpoint is $state: $(jq -c '.status.state_details // {}' <<<"$ep")" ;;
  esac
  sleep 10
done
[[ -n "$URL" ]] || die "Endpoint did not become RUNNING with an https URL (last state: ${state:-unknown})."
URL="${URL%/}"
ENDPOINT_ID=$(jq -r '.metadata.id' <<<"$ep")

say "Checking $URL/health"
code=000
for _ in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$URL/health" || true)
  [[ "$code" == 200 ]] && break
  sleep 10
done
if [[ "$code" != 200 ]]; then
  nebius ai endpoint logs "$ENDPOINT_ID" --tail 50 >&2 || true
  die "$URL/health returned HTTP $code, expected 200. Logs above; more with: nebius ai endpoint logs $ENDPOINT_ID --since 1h"
fi

# Sign in as the first APP_USERS entry to prove the env reached the container intact.
first="${APP_USERS%%,*}"
login_body=$(jq -cn --arg u "${first%%:*}" --arg p "${first#*:}" '{username: $u, password: $p}')
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -H 'content-type: application/json' \
  --data @- "$URL/api/login" <<<"$login_body" || true)
[[ "$code" == 200 ]] || die "/health is fine but logging in as '${first%%:*}' returned HTTP $code. Check APP_USERS."

cat >&2 <<EOF

$(printf '\033[1;32mDeployed.\033[0m')
  URL       $URL
  Image     $IMAGE
  Endpoint  $ENDPOINT_ID
  Health    200, login as '${first%%:*}' OK
  Logs      nebius ai endpoint logs $ENDPOINT_ID --follow
EOF
echo "$URL"
