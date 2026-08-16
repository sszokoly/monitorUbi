# monitorUbi
Monitor Ubiquiti UMR via Cloud API

## API Key

monitorUbi requires a Ubiquiti UniFi Cloud API key with access to the Mobility
workspaces and devices being monitored. Set the key in a `.env` file at the
project root:

```dotenv
UBI_API_KEY=your-api-key
```

The application loads this file automatically. Do not commit the key; `.env`
is ignored by Git. Restrict access to the file:

```bash
chmod 600 .env
```

The Linux **Install Service** deployment copies this file to the configured
`systemd.deployment_root`, where the system service loads it.

## Local Operation

On Windows, macOS, and Linux without an installed `monitorUbi.service`, the TUI
runs in local mode. Press `s` to start or stop polling inside the TUI process.
The local writable SQLite database is `monitorUbi/monitorUbi.db` in the project
directory. Closing the TUI stops local polling.

## Linux System Service

The **Install Service** button is available only on Linux. Use it to:

- Deploy the application and its virtual environment to the configured root
  (`/opt/monitorUbi` by default).
- Apply the SELinux `usr_t` file context when SELinux is enabled.
- Enable and start `monitorUbi.service`.

The monitor service then runs independently of the TUI. Its deployment root is
configured in `config.toml`:

```toml
[database]
default_database_path = "monitorUbi.db"

[systemd]
deployment_root = "/opt/monitorUbi"
```

With these defaults, both the TUI and daemon use
`/opt/monitorUbi/monitorUbi.db`. The daemon is the only writer and TUI sessions
open this database read-only. Pressing `s` starts or stops the systemd service.

Users other than the deployment owner run the TUI in read-only observer mode.
They can view the shared dashboard but cannot manage the system service.

Only `root` and the Unix user who owns the configured deployment root can
install, enable, start, stop, or uninstall the singleton `monitorUbi.service`;
these operations require that user's sudo password. When the deployment root
does not yet exist, the first user to install the service becomes its owner.

For an installation created before this deployment flow, select **Uninstall
Service**, then **Install Service** after restarting the TUI. This replaces the
old unit that executed from the SELinux-restricted project directory under
`/home`.

## Docker

The included Compose setup builds a multi-stage Alpine image and runs two
containers:

- `daemon` polls the Mobility API and is the only SQLite writer.
- `web` serves a read-only Textual dashboard on TCP port `8000`.

Create the project-root `.env` file described above, then run:

```bash
docker compose up --build -d
```

Open `http://localhost:8000`. To publish a different host port:

```bash
MONITORUBI_WEB_PORT=8080 docker compose up --build -d
```

The named `monitorubi-data` volume persists `/data/monitorUbi.db`. Stop the
containers without deleting data with:

```bash
docker compose down
```

The container does not run systemd and does not expose service-installation
controls. Build dependencies remain in the builder stage and are not included
in the runtime image.

## Web Service

For a minimal test-lab setup, serve the application with:

```
uv run textual serve --host 0.0.0.0 --port 8000 --title monitorUbi --command "python -m monitorUbi"
```

Open `http://<host-ip>:8000` in a browser. If a host firewall is active, allow
TCP port `8000`.

## Screenshots

![alt text](./screenshots/dashboard.png?raw=true "dashboard")

![alt text](./screenshots/device_details.png?raw=true "device details and plots")


## Disclaimer

monitorUbi is an independent tool and is not developed, endorsed, or supported
by the vendor. It is provided without express or implied warranty. Users are
responsible for evaluating the tool and using it at their own risk.
