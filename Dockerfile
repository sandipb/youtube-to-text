FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Install deno (yt-dlp's preferred JS runtime) and ffmpeg
RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    ffmpeg \
    && curl -fsSL https://deno.land/install.sh | sh \
    && rm -rf /var/lib/apt/lists/*

ENV DENO_INSTALL="/root/.deno"
ENV PATH="$DENO_INSTALL/bin:$PATH"

# Copy application files and install dependencies
COPY pyproject.toml app.py clean_podcast.py ./
COPY templates/ templates/
COPY static/ static/

# Install Python dependencies from pyproject.toml using uv
RUN uv pip install --system --no-cache .

# Expose port
EXPOSE 8080

# Run with uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
