# k6 — Modern Load Testing

## Why k6

- JavaScript-based test scripts (developer-friendly)
- CLI-first, designed for CI/CD integration
- Built-in metrics export (Prometheus, Grafana, Datadog, InfluxDB)
- Lower resource usage than JMeter for same load
- Open source (Grafana Labs)

## When to Use k6 vs JMeter

| Criteria | k6 | JMeter |
|----------|-----|--------|
| Script language | JavaScript | XML (GUI-generated) |
| CI/CD integration | Native CLI | Requires plugins |
| Protocol support | HTTP, WebSocket, gRPC | HTTP, JDBC, JMS, SOAP, FTP |
| Resource usage | Low (Go-based) | High (Java-based) |
| Learning curve | Easy (JS devs) | Medium (GUI + XML) |
| Distributed testing | k6 Cloud or xk6-distributed | Built-in remote agents |
| Best for | API load testing, CI pipelines | Enterprise multi-protocol, legacy |

**Rule of thumb:** k6 for API/web + CI/CD. JMeter for enterprise multi-protocol + legacy systems.

## Script Patterns

### Basic Load Test
```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '2m', target: 100 },  // ramp up
    { duration: '5m', target: 100 },  // steady state
    { duration: '2m', target: 0 },    // ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'],  // 95% requests < 500ms
    http_req_failed: ['rate<0.01'],    // <1% error rate
  },
};

export default function () {
  const res = http.get('https://api.example.com/endpoint');
  check(res, {
    'status 200': (r) => r.status === 200,
    'response time < 500ms': (r) => r.timings.duration < 500,
  });
  sleep(1); // think time
}
```

### Stress Test (Find Breaking Point)
```javascript
export const options = {
  stages: [
    { duration: '2m', target: 100 },
    { duration: '5m', target: 100 },
    { duration: '2m', target: 200 },
    { duration: '5m', target: 200 },
    { duration: '2m', target: 300 },
    { duration: '5m', target: 300 },
    { duration: '2m', target: 400 },  // keep increasing
    { duration: '5m', target: 400 },
    { duration: '5m', target: 0 },
  ],
};
```

### Spike Test
```javascript
export const options = {
  stages: [
    { duration: '1m', target: 50 },   // normal load
    { duration: '10s', target: 500 },  // spike!
    { duration: '3m', target: 500 },   // hold spike
    { duration: '10s', target: 50 },   // recover
    { duration: '3m', target: 50 },    // verify recovery
    { duration: '1m', target: 0 },
  ],
};
```

### Soak Test (Memory Leak Detection)
```javascript
export const options = {
  stages: [
    { duration: '5m', target: 100 },
    { duration: '4h', target: 100 },   // run for hours
    { duration: '5m', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(99)<1500'],  // relaxed for long run
  },
};
```

### Dynamic Parameters (No Hardcoding)
```javascript
import { SharedArray } from 'k6/data';
import papaparse from 'https://jslib.k6.io/papaparse/5.1.1/index.js';

// Load test data from CSV
const testData = new SharedArray('users', function () {
  return papaparse.parse(open('./test-data.csv'), { header: true }).data;
});

export default function () {
  const user = testData[Math.floor(Math.random() * testData.length)];
  const res = http.post(`${__ENV.BASE_URL}/login`, JSON.stringify({
    username: user.username,
    password: user.password,
  }), { headers: { 'Content-Type': 'application/json' } });
}
```

## Thresholds (Performance Budgets)
```javascript
export const options = {
  thresholds: {
    http_req_duration: ['p(95)<500', 'p(99)<1500'],
    http_req_failed: ['rate<0.01'],
    http_reqs: ['rate>100'],           // min 100 RPS
    checks: ['rate>0.99'],             // 99% checks pass
    'http_req_duration{name:login}': ['p(95)<800'],  // per-endpoint
  },
};
```

## Output & Reporting
```bash
# Run with JSON output
k6 run --out json=results.json script.js

# Run with InfluxDB (for Grafana dashboards)
k6 run --out influxdb=http://localhost:8086/k6 script.js

# Run with Prometheus remote write
k6 run --out experimental-prometheus-rw script.js

# Run with web dashboard (real-time)
K6_WEB_DASHBOARD=true k6 run script.js
```
