#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --model <path> --port <port> --ctx-size <n> --threads <n>"
  exit 1
}

model=""
port=""
ctx_size=""
threads=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model)
      model="${2:-}"
      shift 2
      ;;
    --port)
      port="${2:-}"
      shift 2
      ;;
    --ctx-size)
      ctx_size="${2:-}"
      shift 2
      ;;
    --threads)
      threads="${2:-}"
      shift 2
      ;;
    *)
      usage
      ;;
  esac
done

if [[ -z "$model" || -z "$port" || -z "$ctx_size" || -z "$threads" ]]; then
  usage
fi

exec llama-server \
  --model "$model" \
  --port "$port" \
  --ctx-size "$ctx_size" \
  --threads "$threads"
