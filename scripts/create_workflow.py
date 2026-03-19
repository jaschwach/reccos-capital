#!/usr/bin/env python3
import json, os, urllib.request, sys

PAT = os.environ.get("GITHUB_PAT")
if not PAT:
    print("ERROR: GITHUB_PAT not set")
    sys.exit(1)

REPO = "jaschwach/reccos-capital"
HEADERS = {
    "Authorization": f"Bearer {PAT}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "Content-Type": "application/json",
}

def api(method, path, body=None):
    url = f"https://api.github.com{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        body = e.read()
        print(f"  HTTP {e.code}: {body.decode()[:300]}")
        return None, e.code

WORKFLOW = """\
name: Deploy to Replit Production

on:
  push:
    branches:
      - main

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger Replit Deployment
        env:
          REPLIT_API_KEY: ${{ secrets.REPLIT_API_KEY }}
        run: |
          echo "Push to main received at $(date)"
          echo "Triggering Replit production deploy..."
          curl -s -w "\\nHTTP %{http_code}" \\
            -X POST \\
            -H "Authorization: Bearer $REPLIT_API_KEY" \\
            -H "Content-Type: application/json" \\
            "https://replit.com/api/v1/repls/fd221d28-05a5-42ab-85ce-974b5ca553ec/deployments" \\
            -d '{"type":"autoscale"}' || true
          echo "Deploy step complete."
"""

print("Step 1: Create blob...")
d, code = api("POST", f"/repos/{REPO}/git/blobs", {"content": WORKFLOW, "encoding": "utf-8"})
if not d:
    sys.exit(1)
blob_sha = d["sha"]
print(f"  Blob SHA: {blob_sha[:12]}")

print("Step 2: Get current main ref...")
d, code = api("GET", f"/repos/{REPO}/git/refs/heads/main")
if not d:
    sys.exit(1)
current_commit_sha = d["object"]["sha"]
print(f"  Current commit: {current_commit_sha[:12]}")

print("Step 3: Get current tree...")
d, code = api("GET", f"/repos/{REPO}/git/commits/{current_commit_sha}")
if not d:
    sys.exit(1)
base_tree_sha = d["tree"]["sha"]
print(f"  Base tree: {base_tree_sha[:12]}")

print("Step 4: Create new tree with workflow file...")
d, code = api("POST", f"/repos/{REPO}/git/trees", {
    "base_tree": base_tree_sha,
    "tree": [{
        "path": ".github/workflows/deploy.yml",
        "mode": "100644",
        "type": "blob",
        "sha": blob_sha
    }]
})
if not d:
    sys.exit(1)
new_tree_sha = d["sha"]
print(f"  New tree: {new_tree_sha[:12]}")

print("Step 5: Create commit...")
d, code = api("POST", f"/repos/{REPO}/git/commits", {
    "message": "Add GitHub Actions auto-deploy workflow",
    "tree": new_tree_sha,
    "parents": [current_commit_sha]
})
if not d:
    sys.exit(1)
new_commit_sha = d["sha"]
print(f"  New commit: {new_commit_sha[:12]}")

print("Step 6: Update main branch...")
d, code = api("PATCH", f"/repos/{REPO}/git/refs/heads/main", {
    "sha": new_commit_sha,
    "force": False
})
if not d:
    sys.exit(1)
print(f"  Branch updated to: {d['object']['sha'][:12]}")
print("\nDone! GitHub Actions workflow created at .github/workflows/deploy.yml")
print(f"View at: https://github.com/{REPO}/blob/main/.github/workflows/deploy.yml")
