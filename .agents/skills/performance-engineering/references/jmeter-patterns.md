# JMeter Enterprise Patterns

## When to Use JMeter
- Multi-protocol testing (HTTP, JDBC, JMS, SOAP, FTP, LDAP)
- Complex enterprise flows with correlation and parameterization
- Team prefers GUI-based test design
- Need built-in distributed testing

## Test Plan Structure

```
Test Plan
├── Thread Group (User Scenario)
│   ├── HTTP Cookie Manager
│   ├── HTTP Header Manager
│   ├── CSV Data Set Config (test data)
│   ├── Transaction Controller (Login Flow)
│   │   ├── HTTP Request - GET /login
│   │   ├── Regular Expression Extractor (CSRF token)
│   │   └── HTTP Request - POST /api/auth
│   ├── Think Time (Uniform Random Timer: 3-7s)
│   ├── Transaction Controller (Business Flow)
│   │   ├── HTTP Request - GET /dashboard
│   │   └── HTTP Request - POST /api/submit
│   └── View Results Tree (debug only)
├── Aggregate Report
└── Summary Report
```

## Script Development Order
1. **Record** base flow using HTTP(S) Test Script Recorder or browser proxy
2. **Parameterize** dynamic data via CSV Data Set Config
3. **Correlate** dynamic values (session ID, CSRF tokens) using extractors
4. **Add think time** — Uniform Random Timer or Gaussian Random Timer
5. **Add assertions** — Response Assertion, JSON Assertion, Duration Assertion
6. **Add listeners** — for result collection (disable during load test for performance)

## Correlation Patterns

### Regular Expression Extractor
```
Reference Name: csrf_token
Regular Expression: name="csrf_token" value="(.+?)"
Template: $1$
Match No: 1
```

### JSON Path Extractor
```
Variable: auth_token
JSON Path: $.data.token
```

## Distributed Testing

```bash
# On controller
jmeter -n -t test.jmx -R server1,server2,server3 -l results.jtl

# On each remote server
jmeter-server -Djava.rmi.server.hostname=<server-ip>
```

## Best Practices
- **Remove listeners** during actual load test — they consume memory
- **Use CLI mode** (`-n` flag) for load tests, never GUI mode
- **Heap size**: Set `-Xms4g -Xmx4g` for large tests
- **CSV Data Set**: Use "Recycle on EOF" and "Stop thread on EOF" appropriately
- **Timers**: Always add realistic think time between requests
- **Assertions**: Keep lightweight — avoid complex regex in assertions under heavy load

## CLI Execution

```bash
# Basic run
jmeter -n -t test.jmx -l results.jtl -e -o report/

# With properties
jmeter -n -t test.jmx -Jthreads=100 -Jduration=300 -Jrampup=60

# Generate HTML report from existing results
jmeter -g results.jtl -o report/
```

## Common Pitfalls
- Forgetting to disable listeners → JMeter runs out of memory
- Not correlating dynamic values → requests fail silently
- Using fixed think time → unrealistic load pattern
- Testing from single machine → network becomes bottleneck before app does
- Not warming up JVM → first few minutes of results are skewed
