# Playbook Gallery

This document contains ready-to-use playbooks for common operations scenarios. Each playbook can be used directly or customized for your environment.

## How to Use Playbooks

### From CLI

```bash
# List available templates
autoops templates list

# Use a template
autoops templates use error-rate-investigation -g "Check 5xx errors" -s my-service

# Run immediately
autoops templates use latency-investigation -g "Slow API" -s api-gateway --run
```

### From Code

```python
from autoops_architect.templates import create_registry_with_file_templates

registry = create_registry_with_file_templates()
template = registry.get("error-rate-investigation")

workflow = template.instantiate(
    goal_description="Investigate elevated 5xx errors",
    service="checkout-api",
)
```

---

## Error Investigation Playbooks

### 5xx Error Rate Investigation

**ID:** `error-rate-investigation`
**Category:** `error_investigation`
**Tags:** `5xx`, `errors`, `investigation`, `production`

Use when: HTTP 5xx errors are elevated for a service.

```bash
autoops templates use error-rate-investigation \
  -g "Elevated 5xx errors in checkout-api since 14:00 UTC" \
  -s checkout-api
```

**Workflow Steps:**
1. Collect error logs from the service
2. Query error rate metrics from monitoring
3. Analyze error patterns and stack traces
4. Run automated root cause analysis
5. Generate summary with recommendations

**Customization Options:**
- `duration`: Time window for log collection (default: 2h)
- `error_threshold`: Error rate threshold percentage (default: 5.0)

---

### Authentication Failure Investigation

**ID:** `auth-failure-investigation`
**Category:** `security`
**Tags:** `auth`, `login`, `failures`, `security`

Use when: Users report login failures or auth error rates spike.

```bash
autoops templates use auth-failure-investigation \
  -g "Users unable to login since 10:00" \
  -s auth-service
```

**Workflow Steps:**
1. Collect authentication logs
2. Query auth failure metrics
3. Check identity provider status
4. Analyze failure patterns
5. Generate security summary

---

## Performance Playbooks

### Latency Investigation

**ID:** `latency-investigation`
**Category:** `performance`
**Tags:** `latency`, `slow`, `performance`, `p99`

Use when: P95/P99 latency is above SLA or users report slowness.

```bash
autoops templates use latency-investigation \
  -g "API responses slow, P99 > 2s" \
  -s api-gateway
```

**Workflow Steps:**
1. Query latency percentile metrics (P50, P95, P99)
2. Collect slow request logs
3. Check dependency latencies
4. Analyze latency patterns and bottlenecks
5. Generate performance summary

**Customization Options:**
- `duration`: Time window (default: 6h)
- `latency_threshold_ms`: P99 threshold in ms (default: 1000)

---

### API Degradation Investigation

**ID:** `api-degradation-investigation`
**Category:** `performance`
**Tags:** `api`, `degradation`, `timeout`, `slowdown`

Use when: Overall API health is degraded with mixed symptoms.

```bash
autoops templates use api-degradation-investigation \
  -g "API health degraded, elevated errors and latency" \
  -s product-api
```

**Workflow Steps:**
1. Query error rates (4xx and 5xx)
2. Query latency percentiles
3. Collect distributed traces
4. Check dependency health
5. Collect error logs
6. Compare with baseline
7. Run root cause analysis
8. Generate comprehensive report

---

## Infrastructure Playbooks

### Resource Exhaustion Investigation

**ID:** `resource-investigation`
**Category:** `resources`
**Tags:** `memory`, `cpu`, `resources`, `oom`, `leak`

Use when: Services are hitting resource limits or OOMKilled.

```bash
autoops templates use resource-investigation \
  -g "Pods getting OOMKilled in worker deployment" \
  -s worker-service
```

**Workflow Steps:**
1. Query memory usage metrics over time
2. Query CPU utilization
3. Collect OOM and resource-related logs
4. Analyze resource trends (detect leaks/spikes)
5. Generate resource summary

---

### Database Connection Investigation

**ID:** `db-connection-investigation`
**Category:** `database`
**Tags:** `database`, `connection`, `pool`, `exhaustion`

Use when: "Connection pool exhausted" errors or DB timeouts.

```bash
autoops templates use db-connection-investigation \
  -g "Connection pool exhaustion errors" \
  -s order-service
```

**Workflow Steps:**
1. Query connection pool metrics
2. Collect database-related logs
3. Query database query latency
4. Analyze connection patterns
5. Generate database summary

---

### Kubernetes Pod Crash Investigation

**ID:** `k8s-pod-crash-investigation`
**Category:** `kubernetes`
**Tags:** `kubernetes`, `k8s`, `crash`, `crashloop`, `pod`

Use when: Pods are in CrashLoopBackOff or repeatedly restarting.

```bash
autoops templates use k8s-pod-crash-investigation \
  -g "Pods crash-looping after deployment" \
  -s my-deployment
```

**Workflow Steps:**
1. Get Kubernetes events for the pod
2. Collect pod logs (current and previous)
3. Check resource usage metrics
4. Check liveness/readiness probe status
5. Analyze crash patterns
6. Generate crash investigation summary

---

### Network Connectivity Investigation

**ID:** `network-connectivity-investigation`
**Category:** `network`
**Tags:** `network`, `connectivity`, `dns`, `timeout`

Use when: Services can't reach each other or external dependencies.

```bash
autoops templates use network-connectivity-investigation \
  -g "Service cannot connect to payment gateway" \
  -s checkout-service
```

**Workflow Steps:**
1. Collect connection error logs
2. Query network error metrics
3. Check DNS resolution
4. Check load balancer health
5. Collect target service logs
6. Analyze connectivity patterns
7. Generate connectivity report

---

## Deployment Playbooks

### Post-Deployment Validation

**ID:** `deployment-validation`
**Category:** `deployment`
**Tags:** `deployment`, `release`, `validation`, `regression`

Use when: After deploying a new version, validate health.

```bash
autoops templates use deployment-validation \
  -g "Validate v2.3.0 deployment of user-service" \
  -s user-service
```

**Workflow Steps:**
1. Query current error rates
2. Query baseline error rates
3. Query current latency
4. Query baseline latency
5. Check pod health
6. Collect any new error patterns
7. Compare metrics statistically
8. Generate validation report with pass/fail

**Customization Options:**
- `duration`: Post-deployment window (default: 30m)
- `comparison_window`: Baseline period (default: 1h)
- `error_threshold_percent`: Acceptable error increase (default: 1.0)
- `latency_threshold_ms`: Acceptable P99 increase (default: 500)

---

## Creating Custom Playbooks

### Template Structure

Create a YAML file in `~/.autoops/templates/` or `.autoops/templates/`:

```yaml
id: my-custom-playbook
name: My Custom Playbook
description: Description of what this playbook does
category: custom
tags:
  - custom
  - my-team

author: your-name
version: "1.0"

parameters:
  service: "{{service}}"
  custom_param: "default_value"

nodes:
  - id: step-1
    name: "First step for {{service}}"
    type: log_collection
    tool: log_collector
    params:
      service: "{{service}}"

  - id: step-2
    name: "Second step"
    type: analysis
    tool: analysis
    params:
      analysis_type: "custom"

edges:
  - from_node_id: step-1
    to_node_id: step-2
```

### Variable Substitution

Use `{{variable_name}}` in node names, descriptions, and params:
- `{{service}}` - Replaced with the target service name
- `{{duration}}` - Time window for data collection
- Custom parameters from the `parameters` section

### Node Types

| Type | Description | Common Tools |
|------|-------------|--------------|
| `log_collection` | Gather logs | `log_collector` |
| `metric_query` | Query metrics | `metric_query` |
| `trace_collection` | Collect traces | `trace_collector` |
| `analysis` | Analyze data | `analysis` |
| `summary` | Generate report | `summary` |
| `rca_call` | Root cause analysis | `autoRCA` |

### Best Practices

1. **Start simple**: Begin with 3-5 nodes
2. **Parallel where possible**: Independent queries can run in parallel
3. **Always end with summary**: Provide actionable output
4. **Document parameters**: Help users know what to customize
5. **Test thoroughly**: Validate with `autoops templates validate`

---

## Contributing Playbooks

To contribute a playbook to the community:

1. Create your template YAML
2. Test with `autoops templates validate your-template.yaml`
3. Test execution with `--dry-run`
4. Submit a PR adding the template to `/templates/`
5. Include documentation in the PR description

### Submission Guidelines

- Use descriptive IDs (e.g., `aws-rds-connection-issues`)
- Include comprehensive tags for discoverability
- Document all parameters and their defaults
- Provide example usage commands
- Test against realistic scenarios
