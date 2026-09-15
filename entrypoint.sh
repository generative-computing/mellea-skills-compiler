#!/bin/bash
set -e

if [ -n "${OLLAMA_HOST}" ]; then
    export OLLAMA_API_URL="${OLLAMA_HOST}"
else
    echo "ERROR: OLLAMA_HOST is not set. Please set the OLLAMA_HOST environment variable." >&2
    exit 1
fi

# Either ANTHROPIC_BASE_URL + (ANTHROPIC_AUTH_TOKEN or ANTHROPIC_API_KEY) or BOB_API_KEY must be set
if [ -n "${ANTHROPIC_BASE_URL}" ] && { [ -n "${ANTHROPIC_AUTH_TOKEN}" ] || [ -n "${ANTHROPIC_API_KEY}" ]; }; then
  : # OK — proxy credentials provided
elif [ -n "${BOB_API_KEY}" ]; then
  : # OK — Bob API key provided
else
  echo "ERROR: Either (ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN/ANTHROPIC_API_KEY) for Claude, or BOB_API_KEY for IBM Bob, must be set." >&2
  exit 1
fi

# Execute whatever command was passed to docker run (or CMD)
exec "$@"
