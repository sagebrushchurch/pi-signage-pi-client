# Pi Signage Client

This is the client software designed to run on Raspberry Pi (or compatible devices like HiGole1 mini PCs) for the Pi Signage system. It communicates with the Pi Manager backend to fetch schedules, download content, and report status.

## Features

*   **Content Playback**: Supports Video (via `ffplay`), Audio, Webpages (via `firefox`), and Images.
*   **Hardware Acceleration**: Detects and uses hardware decoding (H.264/HEVC) on supported devices.
*   **Remote Management**: Polls the backend for schedule updates and commands.
*   **Monitoring**: Reports system load, uptime, and takes screenshots of the current display to upload to the server.
*   **Offline Support**: Caches content locally to continue playback if the network goes down (though it needs network to check for updates).

## Requirements

*   Python 3.8+
*   `ffmpeg` / `ffplay`
*   `firefox` (for web and image display)
*   `scrot` (or `grim` for Wayland screenshots)
*   `cec-utils`

## Installation

1.  **System Dependencies**:
    ```bash
    sudo apt install scrot cec-utils ffmpeg firefox-esr
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
