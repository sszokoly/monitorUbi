# monitorUbi
Monitor Ubiquiti UMR via Cloud API

## System Service

Use the **Install Service** button in the TUI to:

- Deploy the application and its virtual environment to `/opt/monitorUbi`.
- Apply the SELinux `usr_t` file context.
- Enable and start `monitorUbi.service`.

The monitor service then runs independently of the TUI. Both the TUI and
daemon use the shared SQLite database at
`/opt/monitorUbi/monitorUbi/monitorUbi.db`.

For an installation created before this deployment flow, select **Uninstall
Service**, then **Install Service** after restarting the TUI. This replaces the
old unit that executed from the SELinux-restricted project directory under
`/home`.

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
