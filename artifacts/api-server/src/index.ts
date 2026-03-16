/**
 * Production entry point for Reccos Capital.
 * This Node.js process:
 *   1. Spawns the Python/Flask app as a child process on FLASK_PORT.
 *   2. Waits until Flask is ready.
 *   3. Starts a thin HTTP proxy on PORT that rewrites /api/ → /rpc/
 *      before forwarding every request to Flask.
 *
 * Why the rewrite?  In production the Replit router sends /api/* to this
 * artifact (port 8080) and serves everything else as static files from
 * dist/public.  The static HTML pages use /api/ as their API prefix.
 * Flask internally uses /rpc/ routes.  The proxy bridges the two.
 */

import { spawn, type ChildProcess } from "child_process";
import http from "http";
import path from "path";
import { fileURLToPath } from "url";

// Support both CJS (__dirname global) and ESM (import.meta.url via fileURLToPath).
// esbuild bundles to CJS so __dirname is available there.
// tsx runs in ESM so we use import.meta.url.
const _dirname: string =
  typeof __dirname !== "undefined"
    ? __dirname
    : path.dirname(fileURLToPath(import.meta.url));

// Built output: artifacts/api-server/dist/index.cjs  → ../../.. = workspace root
// Dev (tsx):    artifacts/api-server/src/index.ts    → ../../.. = workspace root
const WORKSPACE_ROOT = path.resolve(_dirname, "../../..");

const PROXY_PORT = parseInt(process.env["PORT"] ?? "8080", 10);
// Flask runs on a well-separated internal port to avoid clashing with
// other dev services (e.g. mockup-sandbox on 8081).
const FLASK_PORT = PROXY_PORT + 100; // e.g. 8080 → 8180

// ---------------------------------------------------------------------------
// Flask subprocess
// ---------------------------------------------------------------------------

function startFlask(): ChildProcess {
  console.log(`[proxy] Spawning Flask on port ${FLASK_PORT} cwd=${WORKSPACE_ROOT}`);
  const flask = spawn("python", ["startup.py"], {
    cwd: WORKSPACE_ROOT,
    env: { ...process.env, PORT: String(FLASK_PORT) },
    stdio: "inherit",
  });
  flask.on("exit", (code) => {
    console.error(`[proxy] Flask exited with code ${code}`);
    process.exit(code ?? 1);
  });
  return flask;
}

// ---------------------------------------------------------------------------
// Wait for Flask to accept connections
// ---------------------------------------------------------------------------

function waitForFlask(port: number, maxAttempts = 40): Promise<void> {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const attempt = () => {
      const req = http.get({ hostname: "127.0.0.1", port, path: "/" }, (res) => {
        res.resume();
        console.log(`[proxy] Flask ready after ${attempts + 1}s`);
        resolve();
      });
      req.setTimeout(1000);
      req.on("error", () => {
        attempts++;
        if (attempts >= maxAttempts) {
          reject(new Error(`Flask did not start after ${maxAttempts}s`));
        } else {
          setTimeout(attempt, 1000);
        }
      });
      req.end();
    };
    attempt();
  });
}

// ---------------------------------------------------------------------------
// HTTP proxy with path rewrite:  /api/... → /rpc/...
// ---------------------------------------------------------------------------

function startProxy(flaskPort: number, proxyPort: number): void {
  const server = http.createServer((clientReq, clientRes) => {
    const rawPath = clientReq.url ?? "/";

    // Rewrite /api/... to /rpc/... so Flask's existing /rpc/ routes match
    const flaskPath = rawPath.startsWith("/api/")
      ? "/rpc/" + rawPath.slice("/api/".length)
      : rawPath;

    const options: http.RequestOptions = {
      hostname: "127.0.0.1",
      port: flaskPort,
      path: flaskPath,
      method: clientReq.method,
      headers: { ...clientReq.headers, host: `127.0.0.1:${flaskPort}` },
    };

    const flaskReq = http.request(options, (flaskRes) => {
      clientRes.writeHead(flaskRes.statusCode ?? 200, flaskRes.headers);
      flaskRes.pipe(clientRes, { end: true });
    });

    flaskReq.on("error", (err) => {
      console.error("[proxy] Error:", err.message);
      if (!clientRes.headersSent) {
        clientRes.writeHead(502, { "Content-Type": "text/plain" });
      }
      clientRes.end("Bad Gateway");
    });

    clientReq.pipe(flaskReq, { end: true });
  });

  server.listen(proxyPort, "0.0.0.0", () => {
    console.log(`[proxy] Listening on :${proxyPort} → Flask :${flaskPort} (rewrites /api/ → /rpc/)`);
  });
}

// ---------------------------------------------------------------------------
// Startup
// ---------------------------------------------------------------------------

async function main() {
  console.log("=== Reccos Capital production server ===");
  startFlask();
  console.log(`[proxy] Waiting for Flask on port ${FLASK_PORT}...`);
  await waitForFlask(FLASK_PORT);
  startProxy(FLASK_PORT, PROXY_PORT);
}

main().catch((err) => {
  console.error("[proxy] Fatal:", err);
  process.exit(1);
});
