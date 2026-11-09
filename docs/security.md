# Security Model

This document outlines the security considerations, threat model, and safety mechanisms for AutoOps Architect.

## Overview

AutoOps Architect is a meta-agent system that executes workflows in response to operational goals. Because it can interact with production systems, execute commands, and potentially make changes, security is a critical concern.

## Threat Model

### 1. LLM-Proposed Dangerous Steps

**Risk Level:** HIGH

**Description:** The LLM planner may generate workflows containing dangerous operations such as:
- Service restarts in production
- Database modifications
- Configuration changes
- Rollbacks without proper validation

**Mitigations:**
- Remediation is disabled by default (`enable_remediation=False`): the planner refuses a generated workflow containing remediation steps
- High-risk node types require explicit human approval, and nothing downstream of an unapproved step runs
- Generated workflows are checked against the planner's node limit
- LLM prompts include explicit safety constraints

**Configuration:**
```python
from autoops_architect.planner import PlannerConfig

config = PlannerConfig(
    enable_remediation=False,  # Disable dangerous actions
    default_constraints=[
        "Prioritize investigation before remediation",
        "All remediation actions require human approval",
    ]
)
```

### 2. Arbitrary Shell Command Execution

**Risk Level:** HIGH

**Description:** Tools may execute shell commands, potentially allowing:
- Command injection attacks
- Privilege escalation
- Data exfiltration
- System compromise

**Mitigations:**
- `custom_script` nodes require explicit approval
- No shell tool ships with the package
- Tool registry controls which tools are available
- `SafetyValidator` reports dangerous patterns in parameters when you call it

**Configuration:**
```python
from autoops_architect.safety import SafetyConfig, ToolSafety

safety = SafetyConfig(
    tools=ToolSafety(
        allowed=["log_collector", "metric_query", "summary"],  # Whitelist
        blocked=["custom_script"],  # Blacklist
    )
)
```

### 3. Credential and Secrets Exposure

**Risk Level:** HIGH

**Description:** Credentials may be exposed through:
- Logging of parameters or outputs
- Memory storage without encryption
- Transmission to LLM providers
- Tool parameters in workflow JSON

**Mitigations:**
- Credentials should be stored in environment variables
- Sensitive fields are redacted in logs
- Memory files are created readable only by their owner; their contents are not encrypted
- Workflow JSON should not contain actual secrets

**Best Practices:**
```python
# DO: Use environment variables
os.environ["DATADOG_API_KEY"] = "..."

# DON'T: Put secrets in workflow params
workflow_params = {
    "api_key": "SECRET_VALUE"  # BAD!
}
```

### 4. Denial of Service

**Risk Level:** MEDIUM

**Description:** Attackers or misconfigured workflows may cause:
- Resource exhaustion (memory, CPU)
- Excessive API calls
- Long-running operations blocking the system
- Network saturation

**Mitigations:**
- Per-node timeout limits
- Concurrency limits for parallel execution
- Size limits on goals, service lists and webhook payloads

There is no global workflow timeout or LLM rate limit yet.

**Configuration:**
```python
from autoops_architect.executor import ExecutorConfig

config = ExecutorConfig(
    default_timeout_seconds=60,  # Per-node timeout
    max_concurrency=5,           # Parallel execution limit
)
```

### 5. Prompt Injection Attacks

**Risk Level:** MEDIUM

**Description:** Malicious input in goal descriptions may:
- Manipulate LLM to generate dangerous workflows
- Override safety constraints
- Inject unwanted instructions

**Mitigations:**
- The goal, services, tags, context, constraints and refinement feedback are screened before inclusion in prompts, and text from past runs has injection patterns removed
- System prompts include explicit safety boundaries
- Generated workflows are checked against the planner's limits
- The API refuses to clear the approval requirement on dangerous node types

**Input Sanitization:**
```python
from autoops_architect.safety import sanitize_goal

safe_goal = sanitize_goal(user_input)
# Blocks known injection patterns and validates length
```

### 6. Memory Backend Tampering

**Risk Level:** MEDIUM

**Description:** Attackers with file system access may:
- Modify stored workflows
- Inject malicious memory entries
- Corrupt the memory database
- Access sensitive historical data

**Mitigations:**
- Memory files have restricted permissions
- Memory entries are validated on load
- An unreadable JSON memory file is moved aside rather than overwritten

### 7. Tool Registry Manipulation

**Risk Level:** MEDIUM

**Description:** Malicious tools may be registered:
- Through dynamic imports
- Via configuration files
- By modifying the registry at runtime

**Mitigations:**
- Tool registration is explicit in code; tools are not loaded dynamically

### 8. Network-Based Attacks

**Risk Level:** LOW-MEDIUM

**Description:** When running the web UI:
- API endpoints may be exposed
- SSE streams may leak information
- CORS misconfiguration
- Authentication bypass

**Mitigations:**
- `autoops serve` and the Compose file publish the web UI on localhost only
- Cross-origin requests are refused unless `AUTOOPS_CORS_ORIGINS` allows them
- With `AUTOOPS_AUTH_ENABLED=true`, every API route requires a bearer token or API key with the right permission (the bundled web UI does not send credentials yet)
- Webhook triggers must carry a valid HMAC signature
- API endpoints validate input
- Each SSE stream is scoped to one execution

## Safety Features

### 1. Approval Requirements

Certain operations require explicit human approval:

| Node Type | Requires Approval |
|-----------|------------------|
| `log_collection` | No |
| `metric_query` | No |
| `trace_collection` | No |
| `analysis` | No |
| `summary` | No |
| `service_restart` | **Yes** |
| `config_update` | **Yes** |
| `rollback` | **Yes** |
| `scale_action` | **Yes** |
| `custom_script` | **Yes** |

### 2. Workflow Validation

Every `WorkflowGraph` validates its structure when it is built: unique node IDs, edges that reference real nodes, and no cycles. Dangerous node types always carry the approval flag.

`SafetyValidator` adds policy checks (node count, allowed tools and node types, suspicious parameters). It runs when you call it; the executor does not invoke it for you.

### 3. Tool Whitelisting

Configure which tools are available:

```python
from autoops_architect.safety import SafetyConfig, SafetyValidator, ToolSafety

config = SafetyConfig(tools=ToolSafety(allowed=["log_collector", "metric_query", "summary"]))
result = SafetyValidator(config).validate_workflow(workflow)
if not result.valid:
    raise ValueError([issue.message for issue in result.errors])
```

### 4. Dry Run Mode

Test workflows without executing actual actions:

```bash
autoops run workflow.yaml --dry-run
```

```python
from autoops_architect.executor import WorkflowExecutor, ExecutorConfig

executor = WorkflowExecutor(
    config=ExecutorConfig(dry_run=True)
)
```

### 5. Audit Logging

Workflow execution is logged with correlation IDs:
- Workflow start and completion
- Node start, completion and failure
- Errors and failures

Sensitive values such as API keys and passwords are redacted from log output.

```python
import logging

logging.getLogger("autoops_architect").setLevel(logging.INFO)
# Logs include timestamps and operation details
```

## Security Configuration

### Global Safety Settings

`SafetyValidator` reads its policy from `~/.autoops/safety.yaml`:

```yaml
# Safety configuration for AutoOps Architect
version: "1.0"

# Execution controls
execution:
  enable_remediation: false
  max_nodes_per_workflow: 20
  default_timeout_seconds: 60
  workflow_timeout_seconds: 600
  max_concurrency: 5

# Tool controls
tools:
  allowed:
    - log_collector
    - metric_query
    - trace_collector
    - analysis
    - summary
  blocked:
    - custom_script
    - service_restart
  require_approval:
    - autoRCA
    - browserMission

# Node type controls
node_types:
  allowed:
    - log_collection
    - metric_query
    - trace_collection
    - analysis
    - summary
    - rca_call
  blocked:
    - service_restart
    - config_update
    - rollback
    - scale_action
    - custom_script

# Network controls
network:
  allowed_hosts:
    - "*.internal.company.com"
    - "api.datadog.com"
    - "api.openai.com"
  blocked_hosts:
    - "*.external-untrusted.com"

# Approval settings
approval:
  timeout_seconds: 300
  require_for_production: true
  notify_channel: "slack:#ops-approvals"
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AUTOOPS_SAFETY_CONFIG` | Path to safety config file | `~/.autoops/safety.yaml` |
| `AUTOOPS_ENABLE_REMEDIATION` | Enable remediation actions | `false` |
| `AUTOOPS_REQUIRE_APPROVAL` | Require approval for all actions | `false` |
| `AUTOOPS_DRY_RUN` | Enable dry run mode globally | `false` |
| `AUTOOPS_LOG_LEVEL` | Logging level | `INFO` |
| `AUTOOPS_AUTH_ENABLED` | Require credentials on API routes | `false` |
| `AUTOOPS_SECRET_KEY` | JWT signing key (random per process if unset) | unset |
| `AUTOOPS_TOKEN_EXPIRE_MINUTES` | Access token lifetime | `60` |
| `AUTOOPS_CREATE_ADMIN` | Create the first admin at startup | `false` |
| `AUTOOPS_ADMIN_USERNAME` | Name of that admin | `admin` |
| `AUTOOPS_ADMIN_PASSWORD` | Its password; no account is created without one | unset |
| `AUTOOPS_CORS_ORIGINS` | Comma-separated origins allowed cross-origin access | none |

## Security Best Practices

### For Operators

1. **Always review generated workflows** before execution
2. **Use dry-run mode** for new or complex workflows
3. **Start with read-only tools** (log_collector, metric_query)
4. **Enable remediation gradually** as you build trust
5. **Monitor execution logs** for unexpected behavior
6. **Keep tools and integrations updated**

### For Developers

1. **Validate all inputs** in custom tools
2. **Never execute shell commands** with user-provided data
3. **Use parameterized queries** for database operations
4. **Log security-relevant events** appropriately
5. **Follow the principle of least privilege**
6. **Review tool implementations** for security issues

### For Enterprise Deployment

1. **Run behind a reverse proxy** with authentication
2. **Use HTTPS** for all network communication
3. **Enable audit logging** to a secure destination
4. **Implement role-based access control**
5. **Integrate with your SIEM** for security monitoring
6. **Regular security assessments** of configurations

## Incident Response

If you discover a security vulnerability:

1. **Do not disclose publicly** until fixed
2. **Report via email** to security@example.com (replace with actual email)
3. **Include details**: steps to reproduce, impact assessment
4. **We will respond** within 48 hours
5. **Coordinated disclosure** after fix is available

## Security Updates

Security updates are released as:
- **Critical**: Immediate patch release
- **High**: Within 7 days
- **Medium**: In next scheduled release
- **Low**: Tracked and prioritized

Subscribe to security advisories by watching the repository.

## Version History

| Version | Changes |
|---------|---------|
| 1.0 | Initial security model |
