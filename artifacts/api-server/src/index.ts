/**
 * Production entry point for Reccos Capital.
 *
 * This Node.js process:
 *   1. Spawns the Python/Flask app as a child process on FLASK_PORT.
 *   2. Waits until Flask is ready.
 *   3. Starts an HTTP server on PORT that:
 *        - Serves static HTML pages from dist/public/ for all page routes.
 *          Path resolution handles trailing slashes correctly:
 *            /login   → dist/public/login/index.html
 *            /login/  → dist/public/login/index.html
 *        - Proxies /api/* to Flask, rewriting /api/ → /rpc/.
 *        - Proxies /rpc/* to Flask as-is (direct API access).
 *        - SPA fallback: unknown paths serve dist/public/index.html.
 *
 * This approach avoids relying on Replit's static-artifact SPA fallback,
 * which does not handle /login (no trailing slash) → login/index.html.
 */

import { spawn, type ChildProcess } from "child_process";
import http from "http";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const _dirname: string =
  typeof __dirname !== "undefined"
    ? __dirname
    : path.dirname(fileURLToPath(import.meta.url));

// Built: artifacts/api-server/dist/index.cjs  → ../../.. = workspace root
// Dev:   artifacts/api-server/src/index.ts    → ../../.. = workspace root
const WORKSPACE_ROOT = path.resolve(_dirname, "../../..");
const PUBLIC_DIR = path.join(WORKSPACE_ROOT, "artifacts/reccos-capital/dist/public");

const PROXY_PORT = parseInt(process.env["PORT"] ?? "8080", 10);
const FLASK_PORT = PROXY_PORT + 100; // e.g. 8080 → 8180

// ---------------------------------------------------------------------------
// Static file resolution
// Handles /login, /login/, /subscriber/strategies, etc.
// ---------------------------------------------------------------------------

const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".css":  "text/css",
  ".js":   "application/javascript",
  ".json": "application/json",
  ".png":  "image/png",
  ".jpg":  "image/jpeg",
  ".svg":  "image/svg+xml",
  ".ico":  "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};

function resolveStatic(urlPath: string): string | null {
  // Strip query string and trailing slashes
  const clean = urlPath.split("?")[0].replace(/\/+$/, "") || "/";

  // 1. Exact file match (e.g. /style.css → dist/public/style.css)
  if (clean !== "/") {
    const exactFile = path.join(PUBLIC_DIR, clean);
    try {
      const stat = fs.statSync(exactFile);
      if (stat.isFile()) return exactFile;
    } catch { /* not found */ }
  }

  // 2. Directory index (e.g. /login → dist/public/login/index.html)
  const indexFile = path.join(PUBLIC_DIR, clean === "/" ? "" : clean, "index.html");
  try {
    fs.statSync(indexFile);
    return indexFile;
  } catch { /* not found */ }

  // 3. SPA fallback — serve root index.html
  const fallback = path.join(PUBLIC_DIR, "index.html");
  try {
    fs.statSync(fallback);
    return fallback;
  } catch { return null; }
}

function serveFile(filePath: string, res: http.ServerResponse): void {
  const ext = path.extname(filePath);
  const mime = MIME[ext] ?? "application/octet-stream";
  const data = fs.readFileSync(filePath);
  res.writeHead(200, { "Content-Type": mime, "Content-Length": data.length });
  res.end(data);
}

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
// Proxy a request to Flask
// ---------------------------------------------------------------------------

function proxyToFlask(
  flaskPath: string,
  clientReq: http.IncomingMessage,
  clientRes: http.ServerResponse
): void {
  const options: http.RequestOptions = {
    hostname: "127.0.0.1",
    port: FLASK_PORT,
    path: flaskPath,
    method: clientReq.method,
    headers: { ...clientReq.headers, host: `127.0.0.1:${FLASK_PORT}` },
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
}

// ---------------------------------------------------------------------------
// HTTP server
// ---------------------------------------------------------------------------

function startServer(): void {
  const server = http.createServer((clientReq, clientRes) => {
    const rawPath = clientReq.url ?? "/";

    // /api/* → proxy to Flask as /rpc/*
    if (rawPath.startsWith("/api/") || rawPath === "/api") {
      const flaskPath = "/rpc/" + rawPath.slice("/api/".length);
      proxyToFlask(flaskPath, clientReq, clientRes);
      return;
    }

    // /rpc/* → proxy to Flask as-is (direct API access)
    if (rawPath.startsWith("/rpc/") || rawPath === "/rpc") {
      proxyToFlask(rawPath, clientReq, clientRes);
      return;
    }

    // All other paths → serve static files
    const filePath = resolveStatic(rawPath);
    if (filePath) {
      try {
        serveFile(filePath, clientRes);
      } catch (err) {
        console.error("[static] Error reading file:", err);
        clientRes.writeHead(500, { "Content-Type": "text/plain" });
        clientRes.end("Internal Server Error");
      }
      return;
    }

    clientRes.writeHead(404, { "Content-Type": "text/plain" });
    clientRes.end("Not Found");
  });

  server.listen(PROXY_PORT, "0.0.0.0", () => {
    console.log(`[server] Listening on :${PROXY_PORT}`);
    console.log(`[server] Static files from: ${PUBLIC_DIR}`);
    console.log(`[server] API proxy: /api/* → Flask :${FLASK_PORT} /rpc/*`);
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
  startServer();
}

main().catch((err) => {
  console.error("[proxy] Fatal:", err);
  process.exit(1);
});
