# Mobile App Performance — API-Based Testing

## Approach

Test mobile app performance by capturing real API traffic via proxy tools (Fiddler/Charles), then replaying and scaling with JMeter.

## Key Metrics

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| API response time (p95) | <500ms | 500ms-2s | >2s |
| Payload size per action | <500KB | 500KB-2MB | >2MB |
| API error rate | <0.1% | 0.1-1% | >1% |
| Concurrent sessions | per SLA | 80% SLA | >SLA |
| Throughput (TPS) | per SLA | 80% SLA | <80% SLA |

## Workflow: Fiddler/Charles → JMeter

### Step 1: Capture Traffic
- Configure Fiddler/Charles as proxy on mobile device
- Walk through critical user flows (login, browse, submit, etc.)
- Capture all API requests including headers, cookies, tokens
- Export sessions (Fiddler: `.saz`, Charles: `.chls`)

### Step 2: Analyze & Extract
- Identify unique API endpoints per flow
- Note request patterns: sequential vs parallel calls
- Record payload sizes and response times as baseline
- Identify dynamic values (tokens, session IDs, timestamps)

### Step 3: Build JMeter Scripts
- Import/recreate captured requests in JMeter
- Parameterize dynamic values (correlation)
- Add CSV datasets for test data
- Configure thread groups to simulate mobile patterns
- Add think time matching real user behavior

### Step 4: Simulate Mobile Patterns
- Model burst behavior (multiple parallel requests on screen load)
- Add realistic think times between actions
- Simulate session lifecycle (active → idle → re-open)

## Mobile API Workload Model

```
Mobile user session pattern:
1. App open → 5-8 API calls (parallel) → 30s browse
2. Action → 2-3 API calls → 15s think time
3. Repeat 3-5 times
4. Background (keepalive pings every 30s)
5. Re-open after 10-30min → refresh calls
```

### Key Differences vs Web
- More parallel API calls per user action (screen loads fetch multiple endpoints)
- Longer think time (users scroll, read, swipe between actions)
- Burst patterns: activity → long idle → activity
- Push notification triggers can cause thundering herd
- Mobile retries on network failure add extra load

## Tools

| Tool | Purpose |
|------|---------|
| Fiddler | Capture & inspect HTTP/HTTPS traffic from mobile device |
| Charles Proxy | Alternative proxy with mobile-friendly setup |
| JMeter | Replay captured traffic at scale for load testing |
| Postman | Quick API validation before building JMeter scripts |

## API Optimization Checklist

- [ ] Payload size optimized (gzip/brotli compression enabled)
- [ ] Pagination implemented for list endpoints
- [ ] Response times acceptable under concurrent load
- [ ] API handles burst requests without degradation
- [ ] Error handling tested (timeout, retry, 5xx responses)
- [ ] Auth token refresh under load verified
- [ ] API response times tested from target regions
