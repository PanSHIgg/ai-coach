# Web Performance — Core Web Vitals & Frontend

## Core Web Vitals

| Metric | Good | Needs Improvement | Poor |
|--------|------|-------------------|------|
| **LCP** (Largest Contentful Paint) | <2.5s | 2.5-4s | >4s |
| **INP** (Interaction to Next Paint) | <200ms | 200-500ms | >500ms |
| **CLS** (Cumulative Layout Shift) | <0.1 | 0.1-0.25 | >0.25 |

## Additional Metrics

| Metric | Target | Description |
|--------|--------|-------------|
| TTFB | <800ms | Time to First Byte |
| FCP | <1.8s | First Contentful Paint |
| TTI | <3.8s | Time to Interactive |
| TBT | <200ms | Total Blocking Time |
| Bundle size | <200KB JS (initial) | Compressed JS payload |

## Measurement Tools

```bash
# Lighthouse CLI
npx lighthouse https://example.com --output json --output-path ./report.json

# Lighthouse CI
npx lhci autorun --collect.url=https://example.com

# Web Vitals in code
import { onLCP, onINP, onCLS } from 'web-vitals';
onLCP(console.log);
onINP(console.log);
onCLS(console.log);
```

## Common Optimization Strategies

### LCP Optimization
- Preload critical resources (`<link rel="preload">`)
- Optimize images (WebP/AVIF, proper sizing, lazy loading below fold)
- Reduce server response time (CDN, caching, edge computing)
- Remove render-blocking resources

### INP Optimization
- Break up long tasks (>50ms) using `requestIdleCallback` or `scheduler.yield()`
- Minimize main thread work
- Use web workers for heavy computation
- Debounce input handlers

### CLS Optimization
- Set explicit dimensions on images/videos (`width`/`height` attributes)
- Reserve space for dynamic content (ads, embeds)
- Avoid inserting content above existing content
- Use CSS `contain` for layout isolation

## CDN & Caching Strategy
- Cache static assets (CSS, JS, images) with long TTL + cache busting
- Use CDN for geographically distributed users
- Request related CSS, media — ensure CDN covers these
- Implement stale-while-revalidate for API responses

## Performance Budget

| Resource | Budget |
|----------|--------|
| Total page weight | <1.5MB |
| JavaScript (initial) | <200KB gzipped |
| CSS | <50KB gzipped |
| Images (above fold) | <500KB |
| Web fonts | <100KB |
| Third-party scripts | <100KB |

## Network Latency Impact
- Especially critical for mobile users and emerging markets
- Test with throttled connections (3G, slow 4G)
- Consider latency to CDN edge nodes
- Measure real user metrics (RUM) in addition to synthetic tests
