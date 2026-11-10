#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
if [[ -z "${PRODUCT_KNOWLEDGE_OLLAMA_URL:-}" ]] && /usr/bin/curl --noproxy '*' -fsS --max-time 1 http://127.0.0.1:11436/api/tags >/dev/null 2>&1; then
    export PRODUCT_KNOWLEDGE_OLLAMA_URL=http://127.0.0.1:11436
fi
exec python3 -B server.py "$@"
