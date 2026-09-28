# Performance Test Workflow — New Project

Step-by-step workflow when starting performance testing on a new project.

## Phase 1: Analyze Requirements

### Critical Flow Identification
- Map all critical user journeys (login, search, checkout, claim submission, etc.)
- Prioritize by business impact and usage frequency
- Define metrics per flow: response time SLA, throughput target, error rate tolerance

### Architecture Review
- Which components interact in each flow?
- Which third parties are involved? (payment gateway, FileNet, external APIs)
- Identify single points of failure and shared resources
- Document network hops and latency expectations

### Environment Strategy
- Ensure perf testing covers third-party dependencies
- If third party unavailable → create mock service that simulates realistic latency & error rates
- Define approach: stub vs mock vs actual third-party test environment

### Statistics Testing
- Gather baseline metrics from existing system (if available)
- Define statistical significance criteria for results
- Plan for warm-up periods in test execution

## Phase 2: Prepare Environment
- **Data volume**: Must match production scale — this is non-negotiable
- **Scheduling**: Run during off-hours (e.g. preprod midnight) to avoid impacting other teams
- **Cost optimization**: Scale down servers when not running tests (chiến lược nâng giảm server)
- **Monitoring**: Set up APM, infrastructure monitoring, log aggregation BEFORE testing
- **Network**: Ensure network between load generator and target mimics real conditions

## Phase 3: Script Implementation

### Implementation Order
1. **Record/write** base script with correct user flow
2. **Parameterize** dynamic data (user IDs, tokens, search terms)
3. **Correlate** dynamic values (session IDs, CSRF tokens, correlation IDs)
4. **Add think time** between steps (realistic user pause simulation)
5. **Add assertions** to validate correct responses under load
6. **Add listeners/metrics** for detailed result collection
7. **Transaction nesting** — group related requests logically

### Data Coverage
- Ensure test data covers production distribution patterns
- Include edge cases: large payloads, special characters, boundary values
- Plan data refresh strategy between test runs

## Phase 4: Execute & Analyze

### Execution Strategy
1. **Smoke test** (1-2 VUs) — verify scripts work correctly
2. **Baseline test** (low load) — establish performance baseline
3. **Load test** (expected peak) — validate against SLAs
4. **Stress test** (beyond peak) — find breaking point
5. **Soak test** (sustained load, hours) — detect memory leaks, resource degradation

### Monitoring Checklist
- [ ] Application response times (p50, p95, p99)
- [ ] Error rates by type and endpoint
- [ ] CPU, memory, disk I/O on all servers
- [ ] Database query performance, connection pool, locks
- [ ] Cache hit/miss ratios
- [ ] Queue depths and processing times
- [ ] Network throughput and latency
- [ ] GC activity (JVM applications)

### Bottleneck Analysis
- Start from top (load balancer) → app server → database → external services
- Correlate response time spikes with resource utilization
- Check for connection pool exhaustion, thread starvation, lock contention

## Phase 5: Report & Recommendations

### Report Structure
1. **Executive Summary** — pass/fail against SLAs, key findings
2. **Test Configuration** — environment, tools, workload model, data volume
3. **Results Summary** — tables with p50/p95/p99, throughput, error rates
4. **Detailed Findings** — bottlenecks identified with evidence (graphs, logs)
5. **Optimization Recommendations** — prioritized by impact and effort
6. **Retest Results** — comparison before/after optimization
7. **Risk Assessment** — remaining risks and mitigation
8. **Sign-off** — stakeholder approval
