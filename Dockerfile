# =============================================================================
# nBogne Adapter Dockerfile
# =============================================================================
# Runs at the facility. Receives FHIR, queues, transmits to central.
# =============================================================================

FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY nbogne/ ./nbogne/
COPY scripts/ ./scripts/
COPY config/ ./config/

# Create data directories
RUN mkdir -p /app/data /app/logs

# Default config
ENV NBOGNE_CONFIG_PATH=/app/config/docker.yaml

# Expose adapter port
EXPOSE 8081

# Run adapter
CMD ["python", "-m", "scripts.run_adapter"]
