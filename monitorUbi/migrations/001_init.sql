CREATE TABLE workspaces (
    workspace_id TEXT PRIMARY KEY,
    workspace_name TEXT NOT NULL,
    is_owner INTEGER NOT NULL,
    status TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE devices (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    model TEXT NOT NULL,
    state TEXT NOT NULL,
    firmware_version TEXT NOT NULL,
    mac_address TEXT NOT NULL DEFAULT '',
    wan_source TEXT,
    wan_ip TEXT,
    enabled_wans TEXT,
    isp TEXT,
    lte_signal_level TEXT,
    cellular_data_usage_bytes INTEGER,
    cellular_data_limit_bytes INTEGER,
    memory_usage_percent INTEGER,
    uptime_seconds INTEGER,
    client_count INTEGER,
    host_address TEXT,
    poe_passthrough INTEGER,
    device_mode TEXT,
    wifi_enabled INTEGER,
    wifi_ssid TEXT,
    tx_power_level TEXT,
    vpn_profile_name TEXT,
    vpn_status TEXT,
    firewall_rule_names TEXT,
    routing_rule_names TEXT,
    ddns_profile_names TEXT,
    subscription_plan TEXT,
    subscription_status TEXT,
    latitude REAL,
    longitude REAL,
    location_last_updated INTEGER,
    last_seen_at TEXT NOT NULL,

    FOREIGN KEY (workspace_id)
        REFERENCES workspaces(workspace_id)
        ON DELETE RESTRICT
);

CREATE TABLE clients (
    device_id TEXT NOT NULL,
    mac TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL,
    connection_status TEXT NOT NULL,
    ip_address TEXT,
    is_blocked INTEGER NOT NULL,
    wifi_experience INTEGER,
    last_seen_at TEXT NOT NULL,

    PRIMARY KEY (device_id, mac),
    FOREIGN KEY (device_id)
        REFERENCES devices(id)
        ON DELETE RESTRICT
);

CREATE TABLE device_samples (
    sample_id INTEGER PRIMARY KEY,
    sampled_at TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    state TEXT NOT NULL,
    wan_source TEXT,
    wan_ip TEXT,
    lte_signal_level TEXT,
    cellular_data_usage_bytes INTEGER,
    memory_usage_percent INTEGER,
    uptime_seconds INTEGER,
    client_count INTEGER,

    FOREIGN KEY (workspace_id)
        REFERENCES workspaces(workspace_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (device_id)
        REFERENCES devices(id)
        ON DELETE RESTRICT
);

CREATE TABLE client_samples (
    sample_id INTEGER PRIMARY KEY,
    sampled_at TEXT NOT NULL,
    device_id TEXT NOT NULL,
    mac TEXT NOT NULL,
    connection_status TEXT NOT NULL,
    ip_address TEXT,
    is_blocked INTEGER NOT NULL,
    wifi_experience INTEGER,

    FOREIGN KEY (device_id, mac)
        REFERENCES clients(device_id, mac)
        ON DELETE RESTRICT
);

CREATE TABLE api_response_log (
    response_id INTEGER PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    workspace_id TEXT,
    device_id TEXT,
    err TEXT,
    trace_id TEXT,
    payload_json TEXT NOT NULL
);

CREATE INDEX idx_devices_workspace_id ON devices(workspace_id);
CREATE INDEX idx_clients_device_id ON clients(device_id);
CREATE INDEX idx_device_samples_device_time ON device_samples(device_id, sampled_at);
CREATE INDEX idx_device_samples_workspace_time ON device_samples(workspace_id, sampled_at);
CREATE INDEX idx_client_samples_client_time ON client_samples(device_id, mac, sampled_at);
CREATE INDEX idx_client_samples_device_time ON client_samples(device_id, sampled_at);
CREATE INDEX idx_api_response_log_fetched_at ON api_response_log(fetched_at);
