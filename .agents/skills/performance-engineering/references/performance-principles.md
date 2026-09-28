# Performance Testing Principles

## Foundational Principles

### 1. Reproducibility
- Tests MUST be reproducible when system under test is unchanged
- Same test script + same environment + same data = same results
- Best way to verify: add user to system, run test, compare baseline

### 2. Test Early
- Start performance testing early based on principle of testing
- Don't wait until UAT or pre-prod — find issues when they're cheap to fix
- Perf testing applicable at any phase:
  - **Unit level**: Evaluate resource utilization and potential bottlenecks
  - **Integration level**: Component interaction performance
  - **System level**: End-to-end under load

### 3. Risk-Based Approach
- Base performance risk on each technical environment
- Triệu chứng của memory leak: response time degrade over time (dấu hiệu nhận biết)
- Not every system needs the same level of perf testing — prioritize by risk

### 4. Business-Driven Objectives
- Business objective for performance → technical objective for performance → think time → test script
- Example flow: "users must complete checkout in <3s" → "API p95 <500ms, page load <2s" → "think time 5-10s between steps" → k6/JMeter script

### 5. Real User Behavior Modeling
- Understand real user behaviour, not just load numbers
- E.g.: Premier Lite Policy increase x4 existing users — model the actual behavior change, not just 4x traffic
- Not define throughput only base on concurrent users — throughput depends on think time, session length, user journey

### 6. Production Environment Parity
- What happen when perf test system is not equivalent to production env → false results
- Purpose of ramp up / ramp down time: gradual load increase to simulate realistic traffic patterns
- Data volume must match production scale

## What to Monitor

### System Metrics
- CPU%, memory%, disk I/O, network throughput
- Connection pool utilization
- Thread count and state
- GC frequency and duration (JVM apps)

### Application Metrics
- Response time distribution (p50, p95, p99)
- Throughput (requests/sec, transactions/sec)
- Error rate by type
- Queue depth and processing time

### Infrastructure Metrics
- Load balancer distribution
- Database query performance
- Cache hit/miss ratio
- CDN performance (Request related CSS, media)

## Performance Test Steps (Typical)

1. Define performance objectives (SLA/SLO)
2. Identify critical user journeys
3. Design workload model
4. Prepare test environment & data
5. Develop test scripts
6. Execute baseline tests
7. Execute load/stress/soak tests
8. Analyze results & identify bottlenecks
9. Optimize & retest
10. Report & sign-off

## Key Constraints

- **Load generator tool** != production traffic — understand limitations
- **System handles number of requests**, not concurrent users directly
- **Error rate allowance**: define what your system tolerates (e.g., <0.1% for financial services)
- **Network latency impact**: especially important for mobile app & geographically distributed users
