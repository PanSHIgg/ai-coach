# Performance Test Reporting

## Report Template

### 1. Executive Summary
```markdown
## Executive Summary

**Test Date**: YYYY-MM-DD
**Environment**: [Staging/Pre-prod/Prod-like]
**Tool**: [JMeter/Gatling/k6]
**Result**: [PASS/FAIL/CONDITIONAL PASS]

### Key Findings
- [Finding 1: e.g., API response time under load meets SLA]
- [Finding 2: e.g., Database connection pool exhausted at 500 concurrent users]
- [Finding 3: e.g., Memory leak detected in /api/reports endpoint after 2h sustained load]
```

### 2. Test Configuration
```markdown
## Test Configuration

| Parameter | Value |
|-----------|-------|
| Target system | [URL/Service name] |
| Test duration | [minutes/hours] |
| Max virtual users | [number] |
| Ramp-up period | [minutes] |
| Data volume | [rows/records] |
| Network | [LAN/WAN/Simulated latency] |
```

### 3. Results Summary Table
```markdown
## Results

| Endpoint | p50 | p95 | p99 | TPS | Error% | SLA | Status |
|----------|-----|-----|-----|-----|--------|-----|--------|
| POST /api/login | 120ms | 350ms | 800ms | 45 | 0.1% | p95<500ms | PASS |
| GET /api/dashboard | 200ms | 600ms | 1.2s | 30 | 0.5% | p95<500ms | FAIL |
| POST /api/submit | 300ms | 450ms | 900ms | 20 | 0.0% | p95<1s | PASS |
```

### 4. Detailed Findings
```markdown
## Findings

### Finding 1: [Title]
- **Severity**: [Critical/High/Medium/Low]
- **Endpoint**: [affected endpoint]
- **Observed**: [what happened — include metrics]
- **Expected**: [what should have happened — SLA]
- **Root Cause**: [analysis — DB locks, thread pool, memory, etc.]
- **Evidence**: [link to graph/screenshot]
- **Recommendation**: [specific action to fix]
- **Priority**: [P1-P4]
```

### 5. Comparison (Before/After Optimization)
```markdown
## Before vs After Optimization

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| p95 response time | 1.2s | 350ms | 71% faster |
| Max throughput | 200 TPS | 450 TPS | 125% increase |
| Error rate at peak | 5.2% | 0.3% | 94% reduction |
| CPU usage at peak | 95% | 62% | 33% reduction |
```

### 6. Recommendations
```markdown
## Recommendations (Priority Order)

1. **[P1] Increase DB connection pool** — Current: 20, Recommended: 50
2. **[P2] Add caching for /api/dashboard** — Currently hitting DB on every request
3. **[P3] Optimize /api/reports query** — Full table scan detected, add index on created_at
4. **[P3] Review memory allocation** — Potential leak in report generation
```

### 7. Risk Assessment
```markdown
## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Peak load exceeds test scenario | Medium | High | Set up auto-scaling, test quarterly |
| Third-party API degradation | High | Medium | Implement circuit breaker, fallback |
| Data growth impacts query perf | High | High | Index strategy, partitioning plan |
```

## Reporting Best Practices
- Always compare against defined SLAs — never report raw numbers without context
- Include graphs for response time distribution, throughput over time, error rate trends
- Highlight resource utilization correlation with response time degradation
- Provide actionable recommendations, not just findings
- Document test data and environment details for reproducibility
- Get stakeholder sign-off before closing
