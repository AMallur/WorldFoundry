#!/usr/bin/env sh
set -eu

base_url="${WORLDFOUNDRY_URL:-http://127.0.0.1:8787}"

response="$(curl -fsS -X POST "$base_url/v1/episodes" \
  -H 'content-type: application/json' \
  -d '{"environment":"support-desk","task":"incident-triage","seed":7}')"

episode_id="$(printf '%s' "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
printf 'episode=%s\n' "$episode_id"

act() {
  curl -fsS -X POST "$base_url/v1/episodes/$episode_id/actions" \
    -H 'content-type: application/json' -d "$1"
}

act '{"action":"set_priority","parameters":{"ticket_id":"TCK-100","priority":"critical"}}'
act '{"action":"assign","parameters":{"ticket_id":"TCK-100","assignee":"on-call"}}'
act '{"action":"reply","parameters":{"ticket_id":"TCK-100","message":"We acknowledge the outage and have opened an incident."}}'
act '{"action":"resolve","parameters":{"ticket_id":"TCK-100"}}'

curl -fsS -X POST "$base_url/v1/episodes/$episode_id/submit"
curl -fsS "$base_url/v1/episodes/$episode_id/trace" > "${episode_id}.jsonl"
printf 'trace=%s.jsonl\n' "$episode_id"

