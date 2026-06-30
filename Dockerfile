# Production image for the Conduit MCP server (Streamable HTTP transport).
#
# Safe by default: this image binds the loopback interface, so running it on its
# own exposes nothing off-box. Public exposure is the docker-compose stack
# (Caddy TLS + per-IP rate limiting), which overrides the command to bind
# 0.0.0.0 and sets CONDUIT_ALLOW_PUBLIC=1 with Host/Origin allowlists.
FROM python:3.12-slim

WORKDIR /app

# Install the package (and its runtime deps) from the project metadata.
COPY pyproject.toml README.md LICENSE ./
COPY conduit ./conduit
RUN pip install --no-cache-dir . && \
    useradd --create-home --uid 10001 app && \
    chown -R app /app

USER app

ENV CONDUIT_TRANSPORT=http
# Documentation only. Because the default CMD binds 127.0.0.1, a plain
# `docker run -p 8000:8000` cannot reach the process: use the compose stack for
# public serving, or override the bind (e.g. --network host) for local use.
EXPOSE 8000

# Loopback bind: serves only inside the container unless the deployment overrides
# the host (the compose stack binds 0.0.0.0 behind Caddy).
CMD ["conduit-mcp", "--transport", "http", "--host", "127.0.0.1", "--port", "8000", "--path", "/mcp"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
