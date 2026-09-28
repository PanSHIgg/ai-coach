// Mock Server（零依赖）：node server.mjs 即可跑。
// PORT 默认 9000（环境变量可覆盖）；CORS 全放行；随机 50-150ms 延迟；未匹配返回 404 envelope。
import http from 'node:http';

import { match } from './routes.mjs';

const PORT = Number(process.env.PORT || 9000);
let seq = 0;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const requestId = () => `mock-${Date.now().toString(36)}-${(seq += 1)}`;

function send(res, status, envelope) {
  const body = JSON.stringify(envelope);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type,Authorization',
    'X-Request-Id': envelope.request_id || '',
  });
  res.end(body);
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type,Authorization',
    });
    res.end();
    return;
  }

  await sleep(50 + Math.random() * 100); // 模拟网络延迟 50-150ms

  const rid = requestId();
  const route = match(req.method, req.url || '/');
  if (!route) {
    send(res, 404, { code: 3001, message: '资源不存在', data: null, request_id: rid });
    return;
  }
  send(res, 200, { code: 0, message: 'ok', data: typeof route.d === 'function' ? route.d() : route.d, request_id: rid });
});

server.listen(PORT, () => {
  console.log(`[mock] AI 饮食管控教练 mock server: http://localhost:${PORT}（34 接口 canned）`);
});
