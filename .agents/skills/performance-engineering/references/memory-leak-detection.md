# Memory Leak Detection

## Symptoms

| Symptom | Likely Cause |
|---------|-------------|
| Memory usage grows over time, never drops | Object references not released |
| GC runs more frequently, longer pauses | Heap pressure from leaked objects |
| OOM crash after hours/days | Unbounded growth in cache/queue/listener |
| Response time degrades gradually | GC overhead stealing CPU |

## Detection Strategy

### 1. Soak Test (Primary Method)
Run load test for extended period (2-8 hours) with constant load:
```
k6: stages: [{ duration: '4h', target: 100 }]
JMeter: Loop Count = Forever, Duration = 14400s
```

Monitor memory during test:
- **Healthy**: Memory grows, GC reclaims, stabilizes at plateau
- **Leak**: Memory grows continuously, never stabilizes

### 2. Metrics to Watch

| Metric | Tool | What to Look For |
|--------|------|-----------------|
| Heap used | Grafana/APM | Steady upward trend over hours |
| GC frequency | JVM metrics / Node --trace-gc | Increasing over time |
| GC pause time | JVM metrics | Getting longer |
| RSS (Resident Set Size) | `ps` / container metrics | Growing beyond expected |
| Object count by type | Heap snapshot diff | Specific type count growing |

### 3. Heap Snapshot Comparison
Take snapshots at intervals during soak test, compare object counts:
```
Snapshot T=0h:   10,000 objects, 50MB heap
Snapshot T=1h:   15,000 objects, 75MB heap
Snapshot T=2h:   20,000 objects, 100MB heap
→ Linear growth = leak confirmed
```

## Common Leak Patterns

### Node.js
```javascript
// LEAK: Event listeners accumulating
server.on('request', handler);  // never removed
// FIX: Remove listeners on cleanup
server.removeListener('request', handler);

// LEAK: Closures holding references
function createHandler() {
  const largeData = loadHugeDataset();  // captured in closure forever
  return (req, res) => { /* uses largeData */ };
}
// FIX: Scope data properly, use WeakRef if needed

// LEAK: Global cache without eviction
const cache = {};
cache[key] = value;  // grows forever
// FIX: Use LRU cache with max size
const LRU = require('lru-cache');
const cache = new LRU({ max: 1000 });

// LEAK: Unresolved promises / timers
setInterval(() => { /* ... */ }, 1000);  // never cleared
// FIX: Store reference and clearInterval on shutdown
```

### Java / JVM
```java
// LEAK: Static collections growing
static List<Object> cache = new ArrayList<>();  // never cleared

// LEAK: Unclosed resources
Connection conn = dataSource.getConnection();  // never closed
// FIX: try-with-resources
try (Connection conn = dataSource.getConnection()) { }

// LEAK: Inner class holding outer reference
class Outer {
  byte[] largeData = new byte[1024*1024];
  class Inner { }  // holds implicit reference to Outer
}
// FIX: Use static inner class

// LEAK: ThreadLocal not cleaned
threadLocal.set(value);  // never removed
// FIX: Always remove in finally block
try { threadLocal.set(value); } finally { threadLocal.remove(); }
```

### Database Connection Leaks
```
Symptom: Connection pool exhausted, new requests timeout
Cause: Connections acquired but not returned

Check:
- PostgreSQL: SELECT count(*) FROM pg_stat_activity WHERE state = 'idle';
- Application: Monitor pool active/idle/waiting counts
- Look for: Connections in 'idle' state for long time = likely leak

Fix:
- Always close connections in finally/defer blocks
- Set connection max lifetime (e.g., 30 min)
- Set idle timeout (e.g., 10 min)
- Add pool validation query (testOnBorrow)
```

## Tools

### Node.js
| Tool | Purpose |
|------|---------|
| `--inspect` + Chrome DevTools | Heap snapshots, allocation timeline |
| `node --trace-gc` | GC activity logging |
| `clinic.js` | Automated leak detection |
| `heapdump` module | Programmatic heap snapshots |

### Java
| Tool | Purpose |
|------|---------|
| VisualVM | Heap dump analysis, GC monitoring |
| JFR (Java Flight Recorder) | Low-overhead production profiling |
| Eclipse MAT | Heap dump analysis, leak suspect report |
| `-verbose:gc` flag | GC logging |

### Container/System
| Tool | Purpose |
|------|---------|
| `docker stats` | Container memory usage over time |
| Prometheus + Grafana | Time-series memory metrics |
| `pmap` / `smaps` | Process memory map |

## Testing Checklist

- [ ] Run soak test (4h+ at steady load)
- [ ] Compare heap snapshots at 1h intervals
- [ ] Monitor GC frequency and pause time trends
- [ ] Check connection pool usage doesn't grow
- [ ] Verify memory returns to baseline after load stops
- [ ] Test with production-scale data volume
- [ ] Check for event listener accumulation
- [ ] Verify all timers/intervals are cleaned up on shutdown
