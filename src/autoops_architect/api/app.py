"""Main FastAPI application for AutoOps Architect."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from autoops_architect.api.models import HealthResponse
from autoops_architect.api.routes import memory_router, templates_router, workflows_router
from autoops_architect.api.routes.webhooks import router as webhooks_router

# Package version
__version__ = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    # Startup
    print("AutoOps Architect API starting...")
    yield
    # Shutdown
    print("AutoOps Architect API shutting down...")


def create_app(
    title: str = "AutoOps Architect",
    debug: bool = False,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        title: Application title.
        debug: Enable debug mode.
        cors_origins: Allowed CORS origins.

    Returns:
        Configured FastAPI application.
    """
    app = FastAPI(
        title=title,
        description=(
            "Zero/low-code meta-agent that designs and runs autonomous SRE & ops "
            "workflows from natural language goals."
        ),
        version=__version__,
        lifespan=lifespan,
        debug=debug,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Configure CORS
    if cors_origins is None:
        cors_origins = ["*"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(workflows_router, prefix="/api/v1")
    app.include_router(templates_router, prefix="/api/v1")
    app.include_router(memory_router, prefix="/api/v1")
    app.include_router(webhooks_router, prefix="/api/v1")

    # Health check endpoint
    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health_check() -> HealthResponse:
        """Check API health status."""
        # Check if LLM is available
        llm_available = True  # Simplified check
        try:
            from autoops_architect.llm.providers import get_llm_client

            client = get_llm_client()
            llm_available = client is not None
        except Exception:
            llm_available = False

        return HealthResponse(
            status="healthy",
            version=__version__,
            llm_available=llm_available,
            memory_backend="json",
        )

    # Root endpoint with simple UI
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def root() -> str:
        """Serve the main UI page."""
        return get_ui_html()

    return app


def get_ui_html() -> str:
    """Generate the main UI HTML page."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AutoOps Architect</title>
    <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
    <style>
        :root {
            --bg-primary: #1a1a2e;
            --bg-secondary: #16213e;
            --bg-card: #0f3460;
            --text-primary: #eee;
            --text-secondary: #aaa;
            --accent: #e94560;
            --accent-secondary: #0f3460;
            --success: #4ade80;
            --error: #f87171;
            --warning: #fbbf24;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }

        header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 2rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--bg-card);
        }

        h1 {
            font-size: 1.75rem;
            font-weight: 600;
        }

        h1 span {
            color: var(--accent);
        }

        .status-badge {
            padding: 0.5rem 1rem;
            border-radius: 9999px;
            font-size: 0.875rem;
            background: var(--bg-card);
        }

        .status-badge.healthy {
            color: var(--success);
        }

        .main-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 2rem;
        }

        @media (max-width: 1024px) {
            .main-grid {
                grid-template-columns: 1fr;
            }
        }

        .card {
            background: var(--bg-secondary);
            border-radius: 0.75rem;
            padding: 1.5rem;
            border: 1px solid var(--bg-card);
        }

        .card h2 {
            font-size: 1.125rem;
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .form-group {
            margin-bottom: 1rem;
        }

        label {
            display: block;
            font-size: 0.875rem;
            color: var(--text-secondary);
            margin-bottom: 0.5rem;
        }

        textarea, input, select {
            width: 100%;
            padding: 0.75rem;
            border-radius: 0.5rem;
            border: 1px solid var(--bg-card);
            background: var(--bg-primary);
            color: var(--text-primary);
            font-size: 0.875rem;
            font-family: inherit;
        }

        textarea:focus, input:focus, select:focus {
            outline: none;
            border-color: var(--accent);
        }

        textarea {
            min-height: 100px;
            resize: vertical;
        }

        .btn {
            padding: 0.75rem 1.5rem;
            border-radius: 0.5rem;
            border: none;
            font-size: 0.875rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
        }

        .btn-primary {
            background: var(--accent);
            color: white;
        }

        .btn-primary:hover {
            opacity: 0.9;
        }

        .btn-secondary {
            background: var(--bg-card);
            color: var(--text-primary);
        }

        .btn-success {
            background: var(--success);
            color: var(--bg-primary);
        }

        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .button-group {
            display: flex;
            gap: 0.75rem;
            margin-top: 1rem;
        }

        #diagram-container {
            background: white;
            border-radius: 0.5rem;
            padding: 1rem;
            min-height: 300px;
            overflow: auto;
        }

        .node-list {
            margin-top: 1rem;
        }

        .node-item {
            background: var(--bg-primary);
            border-radius: 0.5rem;
            padding: 1rem;
            margin-bottom: 0.75rem;
            border: 1px solid var(--bg-card);
        }

        .node-item.disabled {
            opacity: 0.5;
        }

        .node-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .node-name {
            font-weight: 500;
        }

        .node-type {
            font-size: 0.75rem;
            color: var(--text-secondary);
            background: var(--bg-card);
            padding: 0.25rem 0.5rem;
            border-radius: 0.25rem;
        }

        .node-description {
            font-size: 0.875rem;
            color: var(--text-secondary);
            margin-top: 0.5rem;
        }

        .node-toggle {
            cursor: pointer;
        }

        .execution-log {
            font-family: 'Monaco', 'Consolas', monospace;
            font-size: 0.75rem;
            background: var(--bg-primary);
            border-radius: 0.5rem;
            padding: 1rem;
            max-height: 300px;
            overflow-y: auto;
        }

        .log-entry {
            padding: 0.25rem 0;
            border-bottom: 1px solid var(--bg-card);
        }

        .log-entry.success {
            color: var(--success);
        }

        .log-entry.error {
            color: var(--error);
        }

        .log-entry.info {
            color: var(--text-secondary);
        }

        .templates-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 1rem;
            margin-top: 1rem;
        }

        .template-card {
            background: var(--bg-primary);
            border-radius: 0.5rem;
            padding: 1rem;
            cursor: pointer;
            border: 2px solid transparent;
            transition: all 0.2s;
        }

        .template-card:hover {
            border-color: var(--accent);
        }

        .template-card.selected {
            border-color: var(--accent);
            background: var(--bg-card);
        }

        .template-name {
            font-weight: 500;
            margin-bottom: 0.5rem;
        }

        .template-desc {
            font-size: 0.75rem;
            color: var(--text-secondary);
        }

        .hidden {
            display: none;
        }

        .approval-badge {
            background: var(--warning);
            color: var(--bg-primary);
            font-size: 0.625rem;
            padding: 0.125rem 0.375rem;
            border-radius: 0.25rem;
            margin-left: 0.5rem;
        }

        .tabs {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 1rem;
        }

        .tab {
            padding: 0.5rem 1rem;
            border-radius: 0.5rem;
            cursor: pointer;
            background: var(--bg-primary);
            border: 1px solid var(--bg-card);
        }

        .tab.active {
            background: var(--accent);
            border-color: var(--accent);
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>AutoOps <span>Architect</span></h1>
            <div id="health-status" class="status-badge">Checking...</div>
        </header>

        <div class="main-grid">
            <div class="left-column">
                <div class="card">
                    <h2>Create Workflow</h2>

                    <div class="tabs">
                        <div class="tab active" data-tab="goal">From Goal</div>
                        <div class="tab" data-tab="template">From Template</div>
                    </div>

                    <div id="goal-form">
                        <div class="form-group">
                            <label for="goal-input">Goal Description</label>
                            <textarea id="goal-input" placeholder="Describe what you want to investigate or accomplish...
Example: Investigate elevated 5xx errors for checkout-api service in production"></textarea>
                        </div>

                        <div class="form-group">
                            <label for="services-input">Services (comma-separated)</label>
                            <input type="text" id="services-input" placeholder="checkout-api, payment-service">
                        </div>

                        <div class="form-group">
                            <label for="environment-select">Environment</label>
                            <select id="environment-select">
                                <option value="">Auto-detect</option>
                                <option value="production">Production</option>
                                <option value="staging">Staging</option>
                                <option value="development">Development</option>
                            </select>
                        </div>

                        <div class="button-group">
                            <button class="btn btn-primary" id="generate-btn">Generate Workflow</button>
                        </div>
                    </div>

                    <div id="template-form" class="hidden">
                        <div class="templates-grid" id="templates-list">
                            <!-- Templates loaded dynamically -->
                        </div>

                        <div class="form-group" style="margin-top: 1rem;">
                            <label for="template-service">Service</label>
                            <input type="text" id="template-service" placeholder="checkout-api">
                        </div>

                        <div class="button-group">
                            <button class="btn btn-primary" id="use-template-btn" disabled>Use Template</button>
                        </div>
                    </div>
                </div>

                <div class="card" style="margin-top: 1rem;">
                    <h2>Workflow Nodes</h2>
                    <p id="no-workflow" style="color: var(--text-secondary); font-size: 0.875rem;">
                        No workflow generated yet. Create one above.
                    </p>
                    <div id="node-list" class="node-list hidden"></div>

                    <div id="execution-controls" class="button-group hidden">
                        <button class="btn btn-success" id="execute-btn">Execute Workflow</button>
                        <button class="btn btn-secondary" id="dry-run-btn">Dry Run</button>
                    </div>
                </div>
            </div>

            <div class="right-column">
                <div class="card">
                    <h2>Workflow Graph</h2>
                    <div id="diagram-container">
                        <p style="color: #666; text-align: center; padding: 2rem;">
                            Generate a workflow to see the graph
                        </p>
                    </div>
                </div>

                <div class="card" style="margin-top: 1rem;">
                    <h2>Execution Log</h2>
                    <div id="execution-log" class="execution-log">
                        <div class="log-entry info">Ready to execute workflow...</div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        mermaid.initialize({ startOnLoad: false, theme: 'default' });

        const API_BASE = '/api/v1';
        let currentWorkflow = null;
        let selectedTemplate = null;
        let disabledNodes = new Set();

        // Tab switching
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');

                const tabName = tab.dataset.tab;
                document.getElementById('goal-form').classList.toggle('hidden', tabName !== 'goal');
                document.getElementById('template-form').classList.toggle('hidden', tabName !== 'template');

                if (tabName === 'template') {
                    loadTemplates();
                }
            });
        });

        // Health check
        async function checkHealth() {
            try {
                const res = await fetch('/health');
                const data = await res.json();
                const badge = document.getElementById('health-status');
                badge.textContent = data.status;
                badge.classList.add('healthy');
            } catch (e) {
                document.getElementById('health-status').textContent = 'Error';
            }
        }
        checkHealth();

        // Load templates
        async function loadTemplates() {
            try {
                const res = await fetch(`${API_BASE}/templates`);
                const templates = await res.json();

                const container = document.getElementById('templates-list');
                container.innerHTML = templates.map(t => `
                    <div class="template-card" data-id="${t.id}">
                        <div class="template-name">${t.name}</div>
                        <div class="template-desc">${t.description}</div>
                    </div>
                `).join('');

                container.querySelectorAll('.template-card').forEach(card => {
                    card.addEventListener('click', () => {
                        container.querySelectorAll('.template-card').forEach(c => c.classList.remove('selected'));
                        card.classList.add('selected');
                        selectedTemplate = card.dataset.id;
                        document.getElementById('use-template-btn').disabled = false;
                    });
                });
            } catch (e) {
                console.error('Failed to load templates:', e);
            }
        }

        // Generate workflow from goal
        document.getElementById('generate-btn').addEventListener('click', async () => {
            const goal = document.getElementById('goal-input').value.trim();
            if (!goal) {
                alert('Please enter a goal description');
                return;
            }

            const services = document.getElementById('services-input').value
                .split(',').map(s => s.trim()).filter(s => s);
            const environment = document.getElementById('environment-select').value || null;

            const btn = document.getElementById('generate-btn');
            btn.disabled = true;
            btn.textContent = 'Generating...';

            try {
                const res = await fetch(`${API_BASE}/workflows`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        description: goal,
                        services: services,
                        environment: environment
                    })
                });

                if (!res.ok) {
                    const error = await res.json();
                    throw new Error(error.detail || 'Failed to generate workflow');
                }

                currentWorkflow = await res.json();
                displayWorkflow(currentWorkflow);

            } catch (e) {
                alert('Error: ' + e.message);
            } finally {
                btn.disabled = false;
                btn.textContent = 'Generate Workflow';
            }
        });

        // Use template
        document.getElementById('use-template-btn').addEventListener('click', async () => {
            if (!selectedTemplate) return;

            const service = document.getElementById('template-service').value.trim();
            const goal = `Investigate issues for ${service || 'service'}`;

            const btn = document.getElementById('use-template-btn');
            btn.disabled = true;
            btn.textContent = 'Creating...';

            try {
                const res = await fetch(`${API_BASE}/templates/${selectedTemplate}/instantiate?goal_description=${encodeURIComponent(goal)}&service=${encodeURIComponent(service)}`, {
                    method: 'POST'
                });

                if (!res.ok) {
                    const error = await res.json();
                    throw new Error(error.detail || 'Failed to create workflow');
                }

                currentWorkflow = await res.json();
                displayWorkflow(currentWorkflow);

            } catch (e) {
                alert('Error: ' + e.message);
            } finally {
                btn.disabled = false;
                btn.textContent = 'Use Template';
            }
        });

        // Display workflow
        async function displayWorkflow(workflow) {
            // Render Mermaid diagram
            const container = document.getElementById('diagram-container');
            container.innerHTML = `<pre class="mermaid">${workflow.mermaid_diagram}</pre>`;
            await mermaid.run();

            // Display nodes
            document.getElementById('no-workflow').classList.add('hidden');
            const nodeList = document.getElementById('node-list');
            nodeList.classList.remove('hidden');
            nodeList.innerHTML = workflow.nodes.map(node => `
                <div class="node-item" data-id="${node.id}">
                    <div class="node-header">
                        <span class="node-name">
                            <input type="checkbox" class="node-toggle" data-id="${node.id}" checked>
                            ${node.name}
                            ${node.requires_human_approval ? '<span class="approval-badge">Approval</span>' : ''}
                        </span>
                        <span class="node-type">${node.type}</span>
                    </div>
                    <div class="node-description">${node.description || 'No description'}</div>
                </div>
            `).join('');

            // Add toggle handlers
            nodeList.querySelectorAll('.node-toggle').forEach(toggle => {
                toggle.addEventListener('change', (e) => {
                    const nodeId = e.target.dataset.id;
                    const nodeItem = e.target.closest('.node-item');
                    if (e.target.checked) {
                        disabledNodes.delete(nodeId);
                        nodeItem.classList.remove('disabled');
                    } else {
                        disabledNodes.add(nodeId);
                        nodeItem.classList.add('disabled');
                    }
                });
            });

            // Show execution controls
            document.getElementById('execution-controls').classList.remove('hidden');
        }

        // Execute workflow
        async function executeWorkflow(dryRun = false) {
            if (!currentWorkflow) return;

            const log = document.getElementById('execution-log');
            log.innerHTML = '<div class="log-entry info">Starting execution...</div>';

            // Update workflow with disabled nodes
            if (disabledNodes.size > 0) {
                await fetch(`${API_BASE}/workflows/${currentWorkflow.id}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ disabled_node_ids: Array.from(disabledNodes) })
                });
            }

            try {
                const res = await fetch(`${API_BASE}/workflows/${currentWorkflow.id}/execute?dry_run=${dryRun}`, {
                    method: 'POST'
                });

                const execution = await res.json();
                log.innerHTML += `<div class="log-entry info">Execution started: ${execution.execution_id}</div>`;

                // Stream events
                const eventSource = new EventSource(
                    `${API_BASE}/workflows/${currentWorkflow.id}/execute/${execution.execution_id}/stream`
                );

                eventSource.onmessage = (event) => {
                    const data = JSON.parse(event.data);

                    if (data.event_type === 'stream_end') {
                        eventSource.close();
                        return;
                    }

                    let className = 'info';
                    if (data.event_type === 'node_completed') className = 'success';
                    if (data.event_type === 'node_failed' || data.event_type === 'workflow_failed') className = 'error';

                    const message = data.node_name
                        ? `[${data.event_type}] ${data.node_name}: ${data.status}`
                        : `[${data.event_type}] ${data.message || data.status}`;

                    log.innerHTML += `<div class="log-entry ${className}">${message}</div>`;
                    log.scrollTop = log.scrollHeight;
                };

                eventSource.onerror = () => {
                    eventSource.close();
                    log.innerHTML += '<div class="log-entry info">Connection closed</div>';
                };

            } catch (e) {
                log.innerHTML += `<div class="log-entry error">Error: ${e.message}</div>`;
            }
        }

        document.getElementById('execute-btn').addEventListener('click', () => executeWorkflow(false));
        document.getElementById('dry-run-btn').addEventListener('click', () => executeWorkflow(true));
    </script>
</body>
</html>
"""


# Create app instance for uvicorn
app = create_app()
