#!/usr/bin/env bash
# Push current master to GitHub (jaschwach/reccos-capital, main branch)
# Requires GITHUB_PAT env var to be set (stored in Replit Secrets)
# Usage: bash push_to_github.sh [optional commit message]

set -e

if [ -z "${GITHUB_PAT}" ]; then
  echo "ERROR: GITHUB_PAT environment variable is not set."
  echo "Set it in Replit Secrets (Settings → Secrets) as GITHUB_PAT"
  exit 1
fi

MSG="${1:-Auto-deploy from Replit}"
REPO="https://jaschwach:${GITHUB_PAT}@github.com/jaschwach/reccos-capital.git"

echo "→ Pushing to github.com/jaschwach/reccos-capital (main)..."
git push "${REPO}" master:main
echo "✓ Push complete."
