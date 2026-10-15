#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.npm-global/bin:$PATH"
cd "$(dirname "$0")/.."
(cd frontend && npm install && npm run build)
firebase deploy --only hosting
