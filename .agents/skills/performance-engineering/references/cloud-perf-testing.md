# Cloud Performance Testing

## AWS

### Load Generation
| Service | Use Case |
|---------|----------|
| EC2 (multiple regions) | Distributed JMeter/k6 agents |
| AWS Distributed Load Testing | Managed Fargate-based load gen (uses Taurus + JMeter) |
| CodeBuild | Run k6 in CI/CD pipeline |

### Monitoring During Tests
```
CloudWatch Metrics to Watch:
├── EC2: CPUUtilization, NetworkIn/Out, DiskReadOps
├── RDS: DatabaseConnections, ReadLatency, WriteLatency, FreeableMemory
├── ALB: TargetResponseTime, RequestCount, HTTP5xxCount
├── ElastiCache: CacheHitRate, CurrConnections, EngineCPUUtilization
└── Lambda: Duration, ConcurrentExecutions, Throttles
```

### Auto-Scaling Validation
Test that auto-scaling works correctly under load:
1. Start with min capacity
2. Ramp load gradually
3. Verify scale-out triggers at correct threshold
4. Hold load — verify new instances handle traffic
5. Ramp down — verify scale-in (slower, with cooldown)

### Cost Optimization Testing
- Right-size instances: Load test → check CPU/memory actual usage → downsize if <60%
- Spot instances for load generators (not SUT)
- Schedule perf environment: spin up before test, tear down after
- Compare instance types: same test on t3.xlarge vs c5.xlarge → cost per TPS

## GCP

### Load Generation
| Service | Use Case |
|---------|----------|
| GKE | k6/JMeter in Kubernetes pods, scale horizontally |
| Cloud Run | Serverless load gen for burst tests |
| Cloud Build | k6 in CI/CD pipeline |

### Monitoring During Tests
```
Cloud Monitoring Metrics:
├── Compute: cpu/utilization, memory/usage, network/received_bytes
├── Cloud SQL: database/cpu/utilization, connections, disk/read_ops
├── Cloud Run: request_latencies, request_count, container/cpu
├── GKE: container/cpu/usage_time, container/memory/usage
└── Load Balancer: request_count, total_latencies, backend_latencies
```

## Distributed Load Testing Architecture

### JMeter Distributed Mode
```
Controller (1 instance)
├── Agent 1 (Region A) — 500 VUs
├── Agent 2 (Region B) — 500 VUs
├── Agent 3 (Region C) — 500 VUs
└── Total: 1500 VUs across 3 regions

Setup:
1. Deploy agents in target regions
2. Open port 1099 (RMI) between controller and agents
3. Configure remote_hosts in jmeter.properties
4. Run: jmeter -n -t test.jmx -R agent1,agent2,agent3
```

### k6 Distributed (Cloud or DIY)
```bash
# Option 1: k6 Cloud (managed)
k6 cloud run script.js --vus 1000

# Option 2: DIY with Kubernetes
# Deploy k6 operator, run distributed test
kubectl apply -f k6-test.yaml

# Option 3: Multiple EC2/GCE instances
# Run k6 on each, aggregate results in InfluxDB/Grafana
```

## Environment Strategy

### Perf Test Environment Sizing
| Component | Recommendation |
|-----------|---------------|
| Application servers | Same instance type as prod, can use fewer |
| Database | Same instance type as prod (critical!) |
| Load balancer | Same config as prod |
| Network | Same region, similar latency |
| Data volume | Production-scale (millions of records) |

### Cost-Efficient Practices
- Use reserved/spot instances for load generators
- Schedule environment: up during test windows only
- Share perf environment across teams with scheduling
- Use smaller instance count but same type as prod
- Infrastructure-as-Code for reproducible teardown/setup
