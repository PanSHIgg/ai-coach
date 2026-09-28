# Database Performance Optimization

## Key Metrics

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| Query time (p95) | <50ms | 50-200ms | >200ms |
| Connection pool usage | <70% | 70-90% | >90% |
| Lock wait time | <10ms | 10-100ms | >100ms |
| Cache hit ratio | >95% | 80-95% | <80% |
| Slow queries/min | 0 | 1-5 | >5 |

## Index Optimization

### When to Add Index
- Columns in WHERE, JOIN, ORDER BY, GROUP BY
- High-cardinality columns (many unique values)
- Foreign keys
- Frequently queried but rarely updated columns

### When NOT to Add Index
- Small tables (<1000 rows) — full scan is faster
- Low-cardinality columns (boolean, status with 2-3 values)
- Columns that are frequently updated (index rebuild overhead)
- Tables with heavy INSERT/UPDATE (write penalty)

### Index Types (PostgreSQL)
```sql
-- B-tree (default, most common)
CREATE INDEX idx_users_email ON users(email);

-- Partial index (only index subset of rows)
CREATE INDEX idx_orders_pending ON orders(created_at)
  WHERE status = 'pending';

-- Composite index (multi-column, order matters!)
CREATE INDEX idx_orders_user_date ON orders(user_id, created_at DESC);

-- Covering index (includes extra columns to avoid table lookup)
CREATE INDEX idx_orders_covering ON orders(user_id, created_at)
  INCLUDE (total_amount, status);

-- GIN index (for JSONB, arrays, full-text search)
CREATE INDEX idx_products_tags ON products USING GIN(tags);

-- Expression index
CREATE INDEX idx_users_lower_email ON users(LOWER(email));
```

### Index Anti-Patterns
- **Over-indexing**: Too many indexes → slow writes, wasted storage
- **Wrong column order**: Composite index (A, B) can't serve queries filtering only on B
- **Unused indexes**: Check `pg_stat_user_indexes` for idx_scan = 0
- **Duplicate indexes**: Index on (A) is redundant if (A, B) exists

## Execution Plan Analysis

### Reading EXPLAIN ANALYZE
```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT * FROM orders WHERE user_id = 123 ORDER BY created_at DESC LIMIT 10;
```

### What to Look For
| Pattern | Problem | Fix |
|---------|---------|-----|
| **Seq Scan** on large table | Missing index | Add appropriate index |
| **Nested Loop** with high rows | N+1 or bad join | Add index on join column, restructure query |
| **Hash Join** with high memory | Large dataset join | Ensure join columns indexed, consider partitioning |
| **Sort** with high cost | ORDER BY without index | Add index matching sort order |
| **Bitmap Heap Scan** with many recheck | Low selectivity index | More specific index or partial index |
| **Rows estimated vs actual** differ wildly | Stale statistics | Run ANALYZE on table |

### Common Fixes
```sql
-- Update statistics (after bulk insert/delete)
ANALYZE orders;

-- Check for sequential scans (should be index scans on large tables)
SELECT relname, seq_scan, idx_scan
FROM pg_stat_user_tables
WHERE seq_scan > idx_scan AND n_live_tup > 10000
ORDER BY seq_scan - idx_scan DESC;

-- Find unused indexes (candidates for removal)
SELECT indexrelname, idx_scan
FROM pg_stat_user_indexes
WHERE idx_scan = 0 AND indexrelname NOT LIKE 'pg_%'
ORDER BY pg_relation_size(indexrelid) DESC;

-- Find slow queries
SELECT query, calls, mean_exec_time, total_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC LIMIT 20;
```

## Caching Strategy

### Cache Layers
```
Request → Application Cache (in-memory) → Redis/Memcached → Database
         ~1ms                              ~2-5ms            ~10-200ms
```

### What to Cache
- **Always cache**: Static reference data, user sessions, config, computed aggregates
- **Cache with TTL**: Search results, API responses, frequently read data
- **Never cache**: Real-time data, financial transactions, security tokens

### Cache Patterns

#### Cache-Aside (Lazy Loading)
```
1. Check cache → hit? return
2. Miss → query DB → store in cache → return
```
- Most common pattern
- Stale data possible until TTL expires or invalidation

#### Write-Through
```
1. Write to cache AND DB simultaneously
2. Read always from cache
```
- Consistent but slower writes
- Good for data that's read frequently after write

#### Cache Invalidation
```
1. Write to DB
2. Delete from cache (NOT update — avoids race conditions)
3. Next read re-populates cache
```
- Preferred approach to avoid stale data
- Use event-driven invalidation for related caches

### Redis Caching Patterns
```
# Key naming convention
user:{id}:profile        → user profile data
orders:{user_id}:recent  → recent orders list
search:{hash}            → search results (TTL: 5min)
config:feature_flags     → feature flags (TTL: 1min)

# TTL strategy
Hot data:     5-15 min
Warm data:    1-4 hours
Cold data:    24 hours
Static data:  7 days (with invalidation)
```

## Connection Pool Optimization

### Sizing Formula
```
Pool size = (CPU cores * 2) + effective_spindle_count

Example: 4 cores, SSD
Pool size = (4 * 2) + 1 = 9 connections
```

### Common Issues
- **Too small**: Requests queue waiting for connection
- **Too large**: DB overwhelmed with context switching
- **Leak**: Connections not returned to pool (check application code)

### Monitoring
```sql
-- Current connections by state
SELECT state, count(*)
FROM pg_stat_activity
GROUP BY state;

-- Connection age (long-lived connections may indicate leak)
SELECT pid, now() - backend_start AS connection_age, state, query
FROM pg_stat_activity
WHERE backend_type = 'client backend'
ORDER BY connection_age DESC;
```

## Query Optimization Checklist

- [ ] Run EXPLAIN ANALYZE on slow queries
- [ ] Check indexes exist for WHERE/JOIN/ORDER BY columns
- [ ] Verify statistics are up to date (ANALYZE)
- [ ] Avoid SELECT * — select only needed columns
- [ ] Use LIMIT for paginated results
- [ ] Avoid N+1 queries (use JOINs or batch loading)
- [ ] Check for lock contention on write-heavy tables
- [ ] Monitor connection pool usage under load
- [ ] Cache frequently accessed, rarely changed data
- [ ] Partition large tables (>10M rows) if query patterns support it
