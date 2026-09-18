FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    MOZ_ENABLE_WAYLAND=1 \
    XDG_SESSION_TYPE=wayland \
    PISIGNAGE_BROWSER=firefox-esr \
    PISIGNAGE_BROWSER_FLAGS=--kiosk

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    firefox-esr \
    grim \
    libcec-dev \
    libmagic1 \
    mpv \
    python3 \
    python3-dev \
    python3-magic \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

COPY . /app

CMD ["python3", "/app/pisignage.py"]
