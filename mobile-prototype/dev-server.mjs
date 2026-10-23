#!/usr/bin/env node
/**
 * mobile-prototype 开发服务器（零依赖，仅用 node 内置 http / net / fs）。
 *
 *   - `/api/*`（含 WebSocket 升级，如 /api/v1/ws/saves/{id}）原样反向代理到后端；
 *   - 其余请求按静态文件服务本目录（无 SPA 回退：原型用 hash 路由，只有 index.html 一个入口）。
 *
 * 环境变量：
 *   PORT         监听端口，默认 18765
 *   HOST         监听地址，默认 0.0.0.0
 *   BACKEND_URL  后端地址，默认 http://localhost:8000（与 frontend/vite.config.js 的 VITE_BACKEND_URL 同义）
 *
 * 用法：node mobile-prototype/dev-server.mjs
 * 注意：浏览器侧始终使用同源 /api/...，会话 Cookie `session` 因此无需 CORS。
 */
import http from "node:http";
import net from "node:net";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 18765);
const HOST = process.env.HOST || "0.0.0.0";
const BACKEND = new URL(process.env.BACKEND_URL || "http://localhost:8000");
// 老版本 node 把 localhost 优先解析成 ::1，而 uvicorn 默认只监听 127.0.0.1；统一走 IPv4
const BACKEND_HOST = BACKEND.hostname === "localhost" ? "127.0.0.1" : BACKEND.hostname;
const BACKEND_PORT = Number(BACKEND.port || (BACKEND.protocol === "https:" ? 443 : 80));
if (BACKEND.protocol === "https:") {
  console.error("dev-server 只支持 http 后端（开发用途）；https 请交给 nginx，见 deploy/nginx.conf.template");
  process.exit(1);
}

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8",
};

const isApi = (url) => url === "/api" || url.startsWith("/api/") || url.startsWith("/api?");

// ---------- 静态文件 ----------
function serveStatic(req, res) {
  if (req.method !== "GET" && req.method !== "HEAD") {
    res.writeHead(405, { Allow: "GET, HEAD" }).end();
    return;
  }
  let pathname;
  try {
    pathname = decodeURIComponent(new URL(req.url, "http://x").pathname);
  } catch {
    res.writeHead(400).end("bad request");
    return;
  }
  if (pathname.endsWith("/")) pathname += "index.html";
  const file = path.normalize(path.join(ROOT, pathname));
  // 防目录穿越；同时不暴露开发服务器自身与文档
  if (!file.startsWith(ROOT + path.sep) || file === fileURLToPath(import.meta.url)) {
    res.writeHead(403).end("forbidden");
    return;
  }
  fs.stat(file, (err, st) => {
    if (err || !st.isFile()) {
      res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" }).end("404 Not Found");
      return;
    }
    res.writeHead(200, {
      "Content-Type": MIME[path.extname(file).toLowerCase()] || "application/octet-stream",
      "Content-Length": st.size,
      "Cache-Control": "no-cache", // 开发期：每次校验，改了立刻生效
    });
    if (req.method === "HEAD") res.end();
    else fs.createReadStream(file).pipe(res);
  });
}

// ---------- /api 反向代理（HTTP） ----------
function proxyHttp(req, res) {
  const headers = { ...req.headers, host: BACKEND.host };
  headers["x-forwarded-for"] = req.socket.remoteAddress || "";
  headers["x-forwarded-host"] = req.headers.host || "";
  headers["x-forwarded-proto"] = "http";
  const up = http.request(
    { host: BACKEND_HOST, port: BACKEND_PORT, method: req.method, path: req.url, headers },
    (ur) => {
      res.writeHead(ur.statusCode || 502, ur.headers);
      ur.pipe(res);
    }
  );
  up.on("error", (e) => {
    console.error(`[proxy] ${req.method} ${req.url} -> ${BACKEND.origin} 失败: ${e.code || e.message}`);
    if (!res.headersSent) res.writeHead(502, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ code: "BACKEND_UNAVAILABLE", params: {} }));
  });
  res.on("close", () => up.destroy()); // 客户端中途断开，释放上游
  req.pipe(up);
}

// ---------- /api WebSocket 升级：改写 Host 后把两端 socket 对接 ----------
function proxyUpgrade(req, socket, head) {
  if (!isApi(req.url)) {
    socket.destroy();
    return;
  }
  const up = net.connect(BACKEND_PORT, BACKEND_HOST, () => {
    // 按原始头重放（保留大小写与 Cookie / Sec-WebSocket-* 等），仅替换 Host
    let raw = `${req.method} ${req.url} HTTP/${req.httpVersion}\r\n`;
    for (let i = 0; i < req.rawHeaders.length; i += 2) {
      const k = req.rawHeaders[i];
      const v = k.toLowerCase() === "host" ? BACKEND.host : req.rawHeaders[i + 1];
      raw += `${k}: ${v}\r\n`;
    }
    up.write(raw + "\r\n");
    if (head && head.length) up.write(head);
    socket.pipe(up).pipe(socket);
  });
  const close = () => {
    socket.destroy();
    up.destroy();
  };
  up.on("error", (e) => {
    console.error(`[proxy] WS ${req.url} -> ${BACKEND.origin} 失败: ${e.code || e.message}`);
    close();
  });
  socket.on("error", close);
  socket.on("close", close);
  up.on("close", close);
}

const server = http.createServer((req, res) => (isApi(req.url) ? proxyHttp(req, res) : serveStatic(req, res)));
server.on("upgrade", proxyUpgrade);
server.listen(PORT, HOST, () => {
  console.log(`mobile-prototype dev-server: http://${HOST}:${PORT}/  (/api -> ${BACKEND.origin})`);
});
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => process.exit(0));
