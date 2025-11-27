# Goal: Debug Slow Login API Response Times

## Description

Debug slow response times on the login API endpoint that are affecting user experience.

## Context

- **Environment**: Production
- **Services**: auth-service
- **Priority**: Medium (P2)
- **Trigger**: User complaints about slow login

## Additional Information

Users are reporting that login takes 5-10 seconds instead of the usual <1 second. The issue seems intermittent and started around 9am UTC.

## Expected Workflow

1. Query latency metrics for auth-service
2. Collect logs around the affected timeframe
3. Check database connection pool metrics
4. Analyze for patterns (specific users, regions, etc.)
5. Generate summary of findings
6. Create tracking ticket if issue persists

## CLI Command

```bash
autoops plan-and-run \
  "Debug slow response times on the login API endpoint" \
  --service auth-service \
  --env production
```
