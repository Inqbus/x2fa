# ── Stage 1: dependency install ────────────────────────────────────────────────
FROM python:3.11-slim AS build

WORKDIR /build

# Install uv for fast, reproducible dependency resolution.
RUN pip install --no-cache-dir uv

# Copy lockfile first so Docker caches the install layer when only source changes.
COPY pyproject.toml uv.lock ./

# Install all runtime deps + installer extra into a project venv.
# --no-dev excludes pytest, playwright, litellm.
RUN uv sync --frozen --extra installer --extra postgres --extra mysql --no-dev

# Copy application source.
COPY src/ src/
COPY installer/ installer/


# ── Stage 2: runtime image ─────────────────────────────────────────────────────
FROM python:3.11-slim

# Dedicated non-root user.  Home directory is /home/x2fa — config and data
# volumes are mounted inside it (see compose.yml).
RUN useradd --create-home --shell /bin/bash --uid 1000 x2fa

USER x2fa
WORKDIR /home/x2fa/app

# Copy the venv and source from the build stage.
COPY --from=build --chown=x2fa:x2fa /build/.venv  /home/x2fa/app/.venv
COPY --from=build --chown=x2fa:x2fa /build/src     /home/x2fa/app/src
COPY --from=build --chown=x2fa:x2fa /build/installer /home/x2fa/app/installer

# Activate the venv and expose the x2fa package.
ENV PATH="/home/x2fa/app/.venv/bin:$PATH"
ENV PYTHONPATH="/home/x2fa/app/src:/home/x2fa/app"

EXPOSE 5000

# Default: run the WSGI server.
# Override the command to run the installer TUI:
#   docker run -it --rm [volume flags] x2fa x2fa-install
CMD ["gunicorn", "x2fa.wsgi:app", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--timeout", "60"]
