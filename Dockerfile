FROM python:3.12-slim

# Install system dependencies first
RUN apt update && apt install -y libolm-dev && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv --upgrade

WORKDIR /app

# Copy only requirements first for better layer caching
COPY pyproject.toml .
RUN uv sync

# Copy the rest of the application
COPY main.py .

# Set environment variable to suppress the hardlink warning
ENV UV_LINK_MODE=copy

CMD ["uv", "run", "python", "main.py"]