# Goal: Investigate High Error Rate in Checkout Service

## Description

Investigate elevated 5xx errors for the checkout service in production and recommend mitigation strategies.

## Context

- **Environment**: Production
- **Services**: checkout-api, payments
- **Priority**: High (P1)
- **Trigger**: PagerDuty alert for error rate > 5%

## Additional Information

Started seeing increased errors around 2pm UTC, approximately 30 minutes after deployment v2.3.1. Current error rate is around 8%, up from baseline of 0.5%.

## Expected Workflow

1. Collect logs from checkout-api for the last 2 hours
2. Query error rate metrics from monitoring
3. Collect traces for failed requests
4. Run root cause analysis
5. Generate investigation summary
6. Create a Jira ticket for tracking
7. Notify the on-call channel

## CLI Command

```bash
autoops plan-and-run \
  "Investigate elevated 5xx errors for the checkout service in prod and recommend mitigation" \
  --service checkout-api \
  --service payments \
  --env production
```
