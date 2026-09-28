# Real-World Lessons — Insurance Health App

Practical lessons learned from performance engineering on enterprise-scale insurance/health application.

## Key Lessons

### 1. Throughput ≠ Concurrent Users
- **Mistake**: Defining throughput only based on concurrent user count
- **Lesson**: Throughput depends on think time, session duration, user journey complexity
- **Example**: 1000 concurrent users with 10s think time ≠ 1000 concurrent users with 1s think time

### 2. Model Real User Behavior
- **Mistake**: Just increasing load number linearly
- **Lesson**: Understand real user behaviour changes — e.g. Premier Lite Policy increase meant x4 existing users with different behavior patterns, not just 4x same traffic
- **Action**: Study user analytics, segment by user type, model each segment separately

### 3. Data Growth & Purging Strategy
- **Mistake**: Testing with small dataset, prod has millions of records
- **Lesson**: Plan for data growth and purging from the start
- **Action**: Test with production-scale data volume; include data cleanup in test plan

### 4. Microservice Integration Testing
- **Mistake**: Testing services in isolation with mocks that don't match prod behavior
- **Lesson**: Test separate services based on actual prod configuration and simulation
- **Action**: Integration perf test should mirror real service dependencies

### 5. STP Claim Rule Engine Bottleneck
- **Problem**: Khi nhiều claim submit đồng thời từ nhiều system, các service khác nhau system bị lỗi, third party FileNet stuck
- **Root cause**: STP Claim Rule logic not optimized for concurrent processing
- **Solution**: Optimized STP Claim Rule logic to handle concurrent claims without cascading failures
- **Takeaway**: Always test concurrent submission scenarios for business-critical flows

### 6. CPU Right-Sizing
- **Discovery**: Nhờ monitoring prod thấy CPU chỉ ko tới 40%
- **Action**: Đã đưa ra chiến lược reduce từ 8xlarge xuống 4xlarge (32 → 16 CPUs)
- **Impact**: Significant infrastructure cost savings without performance degradation
- **Takeaway**: Monitor production metrics BEFORE capacity planning — don't over-provision

### 7. Soak Test 12h — Memory Leak & System Degradation
- **Approach**: Soak test 12 hours with steady load to detect memory not being released, GC abnormal behavior
- **Finding**: System degraded over time — memory not released, GC frequency increased
- **AWS Setup**: Load generator on EC2, app on ECS/EKS/EC2
- **Monitoring**: AWS Performance Insights — turn on during test, turn off after to reduce cost
- **Takeaway**: Soak test is critical for insurance apps with long-running sessions; always monitor GC and memory trends over extended periods

### 8. AWS Cost Optimization for Perf Testing
- **Strategy**: Scale up perf environment before test, scale down/terminate after
- **Performance Insights**: Enable only during test windows — billed per vCPU/hour
- **Load generators**: Use spot EC2 instances for JMeter agents (not for SUT)
- **Schedule**: Run perf tests during off-hours (midnight) on preprod to avoid impacting other teams

## Flows When Starting New Project Perf Test

### Phase 1: Analyze Requirements
- Identify critical flows (happy path + error paths)
- Define metrics & SLAs (response time, throughput, error rate)
- Statistics testing: baseline measurements
- Check architecture: which components interact, which third parties involved
- Environment strategy: ensure perf for third parties included
  - If third party not available → create mock service
  - Approach: what is the strategy for third-party dependency?

### Phase 2: Select Tool & Prepare Environment
- Ensure data volume setting same as prod
- Schedule: e.g. Preprod midnight to avoid impacting other teams
- Chiến lược nâng giảm server khi ko run test → cost optimization
- Choose tool matching team skills & project requirements

### Phase 3: Implementation
- Ensure data coverage reflects production distribution
- Understand end user behavior clearly
- Define correct flow with proper transaction nesting (hợp lý)
- Thứ tự các bước: parameterize → correlate → add think time → add assertions → add listeners

### Phase 4: Execute & Analyze
- Baseline run first (low load, verify scripts work)
- Incremental load increase
- Monitor all layers: app, DB, infra, network
- Identify bottlenecks at each layer
- Document findings with evidence (screenshots, metrics)

### Phase 5: Report & Recommendations
- Executive summary (pass/fail against SLAs)
- Detailed findings with root cause
- Optimization recommendations with priority
- Retest results after optimization
- Sign-off from stakeholders
