FROM ghcr.io/astral-sh/uv:python3.13-bookworm

WORKDIR /app

# Copy your project into the container image
COPY . /app

# Default shell (optional)
CMD ["/bin/bash"]