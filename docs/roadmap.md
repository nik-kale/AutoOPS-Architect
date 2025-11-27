# Roadmap

This document outlines the development roadmap for AutoOps Architect.

## Phase Overview

| Phase | Focus | Status |
|-------|-------|--------|
| Phase 1 | MVP: Core Library, CLI, Examples | ✅ Complete |
| Phase 2 | UX, Templates & Real Integrations | ✅ Complete |
| Phase 3 | Code Quality, Performance & CI | ✅ Complete |
| Phase 4 | Security, Safety & QA | ✅ Complete |
| Phase 5 | Ecosystem & Community | 🔜 Next |

---

## Phase 1: MVP (Complete) ✅

### Deliverables

- [x] Repository scaffold with proper structure
- [x] Data models (Goal, WorkflowGraph, Node, Edge, ExecutionResult)
- [x] LLM abstraction layer (OpenAI, Anthropic, Mock)
- [x] Planner/Architect component
- [x] Workflow executor engine
- [x] Tool interface and built-in tools
- [x] Memory backend (JSON, SQLite)
- [x] CLI with Typer
- [x] Tests with pytest
- [x] Example goals and workflows
- [x] Documentation (README, docs/, CONTRIBUTING)

---

## Phase 2: UX, Templates & Real Integrations 🔜

### Goals

Make AutoOps Architect easy to understand, visually inspect, and integrate with real systems.

### Tasks

#### 2.1 Workflow Templates

- [ ] Create template storage system
- [ ] Implement template loading in Planner
- [ ] Create built-in templates:
  - [ ] "Elevated 5xx error rate for service"
  - [ ] "Spikes in latency for API endpoint"
  - [ ] "Recurring login failures"
  - [ ] "Database connection pool exhaustion"
  - [ ] "Memory leak investigation"
- [ ] CLI command: `autoops templates list`
- [ ] CLI command: `autoops templates use <template>`

#### 2.2 Visual Graph Export

- [ ] Mermaid diagram export (basic done, needs enhancement)
- [ ] Graphviz DOT export
- [ ] SVG/PNG export via graphviz
- [ ] Add example diagrams to docs
- [ ] Interactive HTML export

#### 2.3 Simple Review UI

- [ ] Create FastAPI application scaffold
- [ ] Endpoint: `POST /plan` - Generate workflow from goal
- [ ] Endpoint: `GET /workflow/{id}` - Get workflow
- [ ] Endpoint: `POST /workflow/{id}/execute` - Execute workflow
- [ ] Endpoint: `GET /workflow/{id}/status` - Execution status
- [ ] Simple HTML/JS frontend:
  - [ ] Goal input form
  - [ ] Workflow graph visualization
  - [ ] Node toggle/edit capability
  - [ ] Execution progress display
  - [ ] Result summary view

#### 2.4 Real Integrations

- [ ] AutoRCA-Core integration:
  - [ ] HTTP client implementation
  - [ ] Authentication support
  - [ ] Response parsing
  - [ ] Error handling
- [ ] Secure-MCP-Gateway integration:
  - [ ] MCP protocol client
  - [ ] Server discovery
  - [ ] Tool schema loading
  - [ ] Authentication
- [ ] Ops-Agent-Desktop integration:
  - [ ] Mission file format definition
  - [ ] Mission submission API
  - [ ] Result retrieval
  - [ ] Screenshot capture

#### 2.5 Better Memory

- [ ] Define pluggable interface clearly
- [ ] Add Redis backend option
- [ ] Add PostgreSQL backend option
- [ ] Memory search improvements:
  - [ ] Full-text search
  - [ ] Semantic similarity (embeddings)
- [ ] Memory management CLI:
  - [ ] `autoops memory list`
  - [ ] `autoops memory delete <id>`
  - [ ] `autoops memory export`
  - [ ] `autoops memory import`

---

## Phase 3: Code Quality, Performance & CI 📋

### Goals

Make the codebase clean, maintainable, and ready for production use.

### Tasks

#### 3.1 Refactoring

- [ ] Ensure clear module separation
- [ ] Eliminate circular dependencies
- [ ] Standardize error handling
- [ ] Add structured logging
- [ ] Create configuration management system

#### 3.2 Type Safety & Validation

- [ ] Tighten all type hints
- [ ] Add runtime type checking option
- [ ] Strict JSON schema validation
- [ ] Input sanitization layer
- [ ] Add mypy strict mode compliance

#### 3.3 Concurrency & Scaling

- [ ] Parallel node execution:
  - [ ] Identify independent nodes
  - [ ] Implement async parallel execution
  - [ ] Add max_concurrency config
- [ ] Timeout handling:
  - [ ] Per-node timeouts
  - [ ] Global workflow timeout
  - [ ] Graceful cancellation
- [ ] Resource management:
  - [ ] Connection pooling
  - [ ] Memory limits
  - [ ] Rate limiting for LLM calls

#### 3.4 Performance

- [ ] Add caching layer:
  - [ ] LLM response caching
  - [ ] Memory query caching
  - [ ] Tool result caching (where appropriate)
- [ ] Profile and optimize hot paths
- [ ] Lazy loading for heavy components
- [ ] Batch operations where possible

#### 3.5 CI/CD Setup

- [ ] GitHub Actions workflow:
  - [ ] Run tests on PR
  - [ ] Run linting (ruff)
  - [ ] Run type checking (mypy)
  - [ ] Code coverage reporting
  - [ ] Security scanning
- [ ] Release automation:
  - [ ] Version bumping
  - [ ] Changelog generation
  - [ ] PyPI publishing

---

## Phase 4: Security, Safety & QA 📋

### Goals

Make AutoOps Architect safe by default and thoroughly tested.

### Tasks

#### 4.1 Threat Model

- [ ] Create `docs/security.md`:
  - [ ] Risk: Arbitrary shell command execution
  - [ ] Risk: LLM-proposed dangerous steps
  - [ ] Risk: Credential exposure
  - [ ] Risk: Denial of service
  - [ ] Mitigation strategies

#### 4.2 Safety Features

- [ ] Global safety configuration:
  - [ ] Allowed node types whitelist
  - [ ] Allowed tools whitelist
  - [ ] Remediation enable/disable
  - [ ] Required approval types
- [ ] Approval workflow:
  - [ ] CLI approval prompts
  - [ ] API approval endpoints
  - [ ] Timeout for approval requests
  - [ ] Audit logging
- [ ] Sandboxing:
  - [ ] Custom script sandboxing
  - [ ] Network access controls
  - [ ] File system restrictions

#### 4.3 Input Validation

- [ ] Sanitize all user inputs
- [ ] Validate external URLs
- [ ] Validate file paths
- [ ] Prevent injection attacks:
  - [ ] Command injection
  - [ ] Path traversal
  - [ ] Template injection

#### 4.4 QA

- [ ] Expand test coverage to 90%+
- [ ] Add property-based tests (hypothesis):
  - [ ] WorkflowGraph validity
  - [ ] Node parameter validation
  - [ ] Edge cases
- [ ] Add integration tests:
  - [ ] Full plan-and-run flows
  - [ ] Memory persistence
  - [ ] Tool execution
- [ ] Add load tests:
  - [ ] Concurrent workflow execution
  - [ ] Large workflow handling
  - [ ] Memory backend performance

---

## Phase 5: Ecosystem & Community 📋

### Goals

Build a thriving ecosystem and community around AutoOps Architect.

### Tasks

#### 5.1 Ecosystem Integrations

- [ ] Export formats:
  - [ ] YAML for GitOps (Argo, Flux)
  - [ ] JSON for Autonomous Ops Hub
  - [ ] Terraform/Pulumi for IaC
- [ ] API for external tools:
  - [ ] REST API documentation
  - [ ] Python SDK package
  - [ ] JavaScript/TypeScript client
- [ ] Observability:
  - [ ] OpenTelemetry integration
  - [ ] Prometheus metrics export
  - [ ] Structured logging (JSON)

#### 5.2 Community Features

- [ ] Tool marketplace:
  - [ ] Community tool registry
  - [ ] Tool submission process
  - [ ] Quality standards
- [ ] Playbook gallery:
  - [ ] Common incident workflows
  - [ ] Industry-specific templates
  - [ ] User-submitted playbooks
- [ ] Issue labels:
  - [ ] `good first issue`
  - [ ] `help wanted`
  - [ ] `new tool: XYZ`
  - [ ] `enhancement`
  - [ ] `documentation`

#### 5.3 Telemetry & Analytics

- [ ] Optional anonymous usage metrics
- [ ] Workflow execution analytics
- [ ] Tool usage statistics
- [ ] Performance benchmarks

#### 5.4 Demo & Documentation

- [ ] Hosted demo environment
- [ ] Video tutorials
- [ ] Interactive documentation
- [ ] Case studies

---

## Contributing to the Roadmap

We welcome community input on the roadmap! To suggest changes:

1. Open an issue with the `roadmap` label
2. Describe the feature or improvement
3. Explain the use case and benefits
4. Indicate if you'd like to help implement it

## Version Milestones

| Version | Phase | Target Features |
|---------|-------|-----------------|
| 0.1.0 | Phase 1 | MVP with CLI and basic tools |
| 0.2.0 | Phase 2 | Templates, UI, real integrations |
| 0.3.0 | Phase 3 | CI/CD, performance improvements |
| 0.4.0 | Phase 4 | Security hardening, expanded tests |
| 1.0.0 | Phase 5 | Production-ready, ecosystem features |
