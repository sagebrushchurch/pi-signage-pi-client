# Pi Signage Client

This is the client software designed to run on Raspberry Pi (or compatible devices like HiGole1 mini PCs) for the Pi Signage system. It communicates with the Pi Manager backend to fetch schedules, download content, and report status.

## Features

*   **Content Playback**: Supports Video/Audio/Images (via `mpv`) and Webpages (via `firefox`).
*   **Hardware Acceleration**: Detects and uses hardware decoding (H.264/HEVC) on supported devices.
*   **Remote Management**: Polls the backend for schedule updates and commands.
*   **Monitoring**: Reports system load, uptime, and takes screenshots of the current display to upload to the server.
*   **Offline Support**: Caches content locally to continue playback if the network goes down (though it needs network to check for updates).

## Requirements

*   Python 3.8+
*   `mpv`
*   `firefox`
*   `grim` for Wayland screenshots
*   `cec-utils`

## Installation

1.  **System Dependencies**:
    ```bash
    sudo apt install cec-utils firefox-esr grim mpv python3-magic
    ```

2.  **Python Dependencies**:
    ```bash
    pip3 install -r requirements.txt
    ```
    *Note: `httpx` might have issues on older Debian Stretch distributions.*

## Configuration

The client automatically detects if it is running in a development environment based on the hostname.
*   **Dev**: Hostname contains `-dev-` -> Connects to `https://piman.sagebrush.dev/pi_manager_api`
*   **Prod**: Default -> Connects to `https://piman.sagebrush.work/pi_manager_api`

## Usage

Run the client script:
```bash
python3 pisignage.py
```

## Docker

This repository now includes a `Dockerfile` for running the client in a container.
On Debian hosts running `sway`, start the container as the same logged-in user so it can
reach the Wayland and audio sockets:

```bash
docker build -t pi-signage-client .

docker run -d \
  --name pi-signage-client \
  --restart unless-stopped \
  --network host \
  --user "$(id -u):$(id -g)" \
  --group-add audio \
  --group-add video \
  -e WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}" \
  -e XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR}" \
  -e PULSE_SERVER="unix:${XDG_RUNTIME_DIR}/pulse/native" \
  -v "${XDG_RUNTIME_DIR}:${XDG_RUNTIME_DIR}" \
  -v /sys/class/drm:/sys/class/drm:ro \
  --device /dev/dri \
  --device /dev/snd \
  pi-signage-client
```

Notes:

* `--network host` lets the client report the host's network information instead of a
  container-only address.
* `--device /dev/dri` enables hardware-accelerated video where supported.
* `--device /dev/snd` plus the Pulse socket mount provide audio passthrough for `mpv`
  and Firefox on a typical Debian + sway setup.
* `pisignage.py` resolves `resolution.sh` relative to the repository, so no host-specific
  `/home/pi/...` path is required in the container.

### Running as a systemd service (with watchdog)

The client is designed to run indefinitely under `systemd` as a `--user` service named
`piman.service`, using [`systemd/piman.service`](systemd/piman.service) as a template:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/piman.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now piman.service
```

All network downloads and subprocess calls (screenshotting, resolution detection) have
bounded timeouts, and the client pings systemd's watchdog once per loop iteration via
`sd_notify`. If a call ever stalls past `WatchdogSec` (e.g. the network drops mid-download),
systemd kills and restarts the process automatically instead of it hanging forever.

## Hardware Notes

*   **HiGole1 MiniPC**: Wifi drivers may need to be installed manually: https://github.com/lwfinger/rtw89
