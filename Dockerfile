# Multi-stage build for AutoOps Architect
# Produces a slim production image with all necessary dependencies

# Builder stage - install dependencies and build wheel
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

# Build wheel
RUN pip install --no-cache-dir build && \
    python -m build --wheel && \
    ls -la dist/

# Runtime stage - minimal image with only runtime dependencies
FROM python:3.11-slim

LABEL maintainer="AutoOps Team" \
      description="AutoOps Architect - AI-powered SRE workflow automation" \
      version="0.1.0"

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -m -u 1000 autoops && \
    chown -R autoops:autoops /app

# Copy wheel from builder
COPY --from=builder /build/dist/*.whl /tmp/

# Install AutoOps Architect with web extras
RUN pip install --no-cache-dir /tmp/*.whl[web] && \
    rm /tmp/*.whl && \
    pip cache purge

# Switch to non-root user
USER autoops

# Environment variables
ENV AUTOOPS_LOG_LEVEL=INFO \
    AUTOOPS_DEV_MODE=false \
    PYTHONUNBUFFERED=1

# Expose web UI port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command: start web server
CMD ["autoops", "serve", "--host", "0.0.0.0", "--port", "8000"]

# Alternative commands (override in docker-compose or docker run):
# CMD ["autoops", "--help"]
# CMD ["autoops", "plan", "Your goal here"]

