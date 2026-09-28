# CI/CD Performance Testing Integration

## Why Automate Perf Tests in Pipeline

- Catch performance regressions before merge
- Enforce performance budgets automatically
- No manual effort after initial setup
- Performance as a quality gate (fail build if SLA breached)

## GitHub Actions

### k6 in GitHub Actions
```yaml
name: Performance Tests
on:
  pull_request:
    branches: [main, develop]
  schedule:
    - cron: '0 2 * * 1'  # weekly full run

jobs:
  load-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install k6
        run: |
          sudo gpg -k
          sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D68
          echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" | sudo tee /etc/apt/sources.list.d/k6.list
          sudo apt-get update && sudo apt-get install k6

      - name: Run load test
        run: k6 run tests/perf/load-test.js
        env:
          BASE_URL: ${{ secrets.PERF_TEST_URL }}
          K6_WEB_DASHBOARD: true
          K6_WEB_DASHBOARD_EXPORT: perf-report.html

      - name: Upload report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: perf-report
          path: perf-report.html
```

### JMeter in GitHub Actions
```yaml
name: JMeter Performance Tests
on:
  workflow_dispatch:
    inputs:
      threads:
        description: 'Number of threads'
        default: '50'
      duration:
        description: 'Test duration (seconds)'
        default: '300'

jobs:
  jmeter-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run JMeter
        uses: rbhadti94/apache-jmeter-action@v0.5.0
        with:
          testFilePath: tests/perf/test-plan.jmx
          outputReportsFolder: reports/
          args: >-
            -Jthreads=${{ github.event.inputs.threads }}
            -Jduration=${{ github.event.inputs.duration }}
            -Jbase_url=${{ secrets.PERF_TEST_URL }}

      - name: Upload JMeter report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: jmeter-report
          path: reports/
```

## Pipeline Strategy

### PR Checks (Fast — < 5 min)
- Smoke test: 10 VUs, 1 min
- Verify no critical regressions
- Threshold: p95 < 500ms, error rate < 1%

### Nightly (Medium — 15-30 min)
- Load test: 100 VUs, 10 min ramp + 10 min steady
- Baseline comparison
- Threshold: p95 < 800ms, error rate < 0.5%

### Weekly (Full — 1-4 hours)
- Stress test: incremental to breaking point
- Soak test: 100 VUs, 2-4 hours
- Capacity planning data collection

### Release Gate (Before deploy)
- Full load test against staging
- Must pass all thresholds to proceed
- Report archived for audit

## Performance Budget as Code
```javascript
// k6 thresholds = performance budgets
export const options = {
  thresholds: {
    // API budgets
    'http_req_duration{endpoint:login}': ['p(95)<800'],
    'http_req_duration{endpoint:search}': ['p(95)<1200'],
    'http_req_duration{endpoint:checkout}': ['p(95)<2000'],

    // Global budgets
    http_req_failed: ['rate<0.01'],
    http_reqs: ['rate>50'],
  },
};
```

## Environment Considerations
- **Never run perf tests against production** unless read-only and approved
- Use dedicated perf environment with production-equivalent config
- Schedule runs during off-hours to avoid impacting other teams
- Clean test data after each run
- Use environment variables for all URLs/credentials — never hardcode
