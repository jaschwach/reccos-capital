import { readFileSync } from 'fs';

const PAT = process.env.GITHUB_PAT;
if (!PAT) {
  console.error('GITHUB_PAT not set');
  process.exit(1);
}

const workflowYaml = `name: Deploy to Replit Production

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
          REPLIT_API_KEY: \${{ secrets.REPLIT_API_KEY }}
        run: |
          echo "Push to main received at $(date)"
          echo "Triggering Replit production deploy..."
          curl -s -w "\\nHTTP %{http_code}" \\
            -X POST \\
            -H "Authorization: Bearer $REPLIT_API_KEY" \\
            -H "Content-Type: application/json" \\
            "https://replit.com/api/v1/repls/fd221d28-05a5-42ab-85ce-974b5ca553ec/deployments" \\
            -d '{"type":"autoscale"}' || true
          echo "Done."
`;

const encoded = Buffer.from(workflowYaml).toString('base64');

const res = await fetch(
  'https://api.github.com/repos/jaschwach/reccos-capital/contents/.github/workflows/deploy.yml',
  {
    method: 'PUT',
    headers: {
      'Authorization': `Bearer ${PAT}`,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message: 'Add GitHub Actions auto-deploy workflow',
      content: encoded,
    }),
  }
);

const data = await res.json();
console.log('HTTP', res.status);
if (res.status === 201) {
  console.log('Created:', data.content.path);
  console.log('URL:', data.content.html_url);
} else {
  console.log('Error:', JSON.stringify(data, null, 2));
}
