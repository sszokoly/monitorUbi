# monitorUbi
Monitor Ubiquiti UMR via Cloud API

## System Service

Use **Install Service** in the TUI to deploy the application and its virtual
environment to `/opt/monitorUbi`, apply the SELinux `usr_t` file context, and
enable `monitorUbi.service`. The monitor then runs independently of the TUI.
Both the TUI and daemon use `/opt/monitorUbi/monitorUbi/monitorUbi.db`.

For an installation created before this deployment flow, select **Uninstall
Service**, then **Install Service** after restarting the TUI. This replaces the
old unit that executed from the SELinux-restricted project directory under
`/home`.

```
┌ 𝐦𝗼𝐧𝐢𝐭𝗼𝐫𝐔𝐁𝐈 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Status: √ (running) │ RAM Usage: 24.2 MB │ DB Size: 201.2 MB │ Workspaces: 199 │ Devices: 323 │ Clients: 323 │ History: 30 days │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
┌ 𝐃𝐞𝐯𝐢𝐜𝐞𝐬 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Name                      Workspace                 State  WAN-IP           WAN  Signal  Usage     Clients  Last-Seen           │
│ URM1 Living Spirit        NetagenCBE's Cloud          ●    192.168.111.23   WAN  ▁▂▃▅▇█  299.1 MB  1        2026-07-31 23:32:52 │
│ URM2 CBE Vista Heights    Wayne's Cloud               ●    192.168.112.222  WAN  ▁▂▃▅      1.1 GB  1        2026-07-31 23:32:53 │
│ CBE Mountain Park         Wayne's Cloud               ●    192.168.11.22    WAN  ▁▂       22.1 MB  2        2026-07-31 22:32:53 │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```
