FROM debian:bookworm-slim AS build

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libcec-dev \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    MOZ_ENABLE_WAYLAND=1 \
    XDG_SESSION_TYPE=wayland \
    PATH="/opt/venv/bin:${PATH}" \
    PISIGNAGE_BROWSER=firefox-esr \
    PISIGNAGE_BROWSER_FLAGS=--kiosk

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    cec-utils \
    firefox-esr \
    grim \
    libcec6 \
    libmagic1 \
    mpv \
    python3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/venv /opt/venv
COPY . /app

CMD ["/opt/venv/bin/python3", "/app/pisignage.py"]
