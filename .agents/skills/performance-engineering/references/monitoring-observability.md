# Monitoring & Observability for Performance Testing

## Prometheus + Grafana Stack

### Architecture
```
Application → Prometheus exporter → Prometheus (scrape) → Grafana (visualize)
                                                        → Alertmanager (alert)
```

### Key Exporters
| Exporter | Metrics |
|----------|---------|
| Node Exporter | CPU, memory, disk, network (system level) |
| PostgreSQL Exporter | Connections, query time, locks, replication lag |
| Redis Exporter | Hit/miss ratio, memory, connections, keys |
| JMeter Backend Listener | Request/response metrics → InfluxDB → Grafana |
| k6 Prometheus Remote Write | k6 metrics directly to Prometheus |

### Essential Grafana Dashboards

#### During Load Test
- **Request rate** (req/s) — is load reaching target?
- **Response time** (p50, p95, p99) — within SLA?
- **Error rate** (%) — acceptable threshold?
- **Active threads/VUs** — matching test plan?

#### System Health
- **CPU utilization** per service — bottleneck identification
- **Memory usage** trend — leak detection
- **Disk I/O** — storage bottleneck
- **Network throughput** — bandwidth saturation

#### Database
- **Active connections** vs pool size
- **Query execution time** (p95)
- **Lock wait time**
- **Cache hit ratio**
- **Replication lag** (if applicable)

### Prometheus Alerting Rules (Perf Test)
```yaml
groups:
  - name: perf-test-alerts
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.01
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Error rate > 1% during perf test"

      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 0.5
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "P95 latency > 500ms"

      - alert: HighCPU
        expr: 100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 80
        for: 5m
        labels:
          severity: warning
```

## APM Tools Integration

| Tool | Strength | Integration |
|------|----------|------------|
| Datadog | Full-stack APM + infra | k6 output plugin, JMeter plugin |
| New Relic | Transaction tracing | API metrics correlation |
| Grafana Cloud | Native k6 + Prometheus | k6 cloud output |
| Elastic APM | Distributed tracing | Filebeat + Metricbeat |

## Correlation: Load Test ↔ System Metrics

### Timeline Alignment
During perf test, correlate:
```
Time    Load (VUs)    P95 Latency    CPU%    DB Connections    Error Rate
10:00   50            120ms          25%     20                0%
10:05   100           150ms          45%     40                0%
10:10   200           280ms          72%     80                0%
10:15   300           850ms          95%     120 (pool max!)   2.5%
10:20   400           timeout        99%     120 (queuing)     15%
→ Bottleneck: CPU saturation at 200+ VUs, DB pool exhausted at 300+ VUs
```

### Bottleneck Identification Decision Tree
```
Response time high?
├── CPU > 80%? → CPU-bound → Scale up/out, optimize code
├── Memory > 85%? → Memory-bound → Check leaks, increase RAM
├── DB connections = max? → Pool exhaustion → Increase pool, optimize queries
├── DB query time high? → Query bottleneck → Index, cache, optimize SQL
├── Disk I/O high? → I/O-bound → SSD, reduce logging, optimize writes
├── Network saturated? → Bandwidth → CDN, compression, reduce payload
└── None of above? → Application lock/contention → Profile code, check mutex
```

## Monitoring Checklist for Perf Tests

- [ ] Prometheus/Grafana running before test starts
- [ ] All service exporters configured and scraping
- [ ] Dashboard with load test timeline + system metrics
- [ ] Alerting rules set for SLA thresholds
- [ ] Baseline metrics captured before load starts
- [ ] Screenshots/exports of dashboards saved with test results
- [ ] Bottleneck correlation documented in report
