# Enterprise Scale Platform Health workbook

An Azure Monitor workbook showing the health, capacity and throughput of the shared
platform services in an Enterprise Scale (Azure Landing Zone) deployment.

## Import

1. Azure portal → **Monitor** → **Workbooks** → **+ New**.
2. Open the **Advanced Editor** (`</>` on the toolbar), choose **Gallery Template**.
3. Paste the contents of [workbook/alz-platform-health.workbook.json](workbook/alz-platform-health.workbook.json) → **Apply** → **Save**.

## Tabs

Built for a **Virtual WAN** based landing zone.

| Tab | Data source | What it shows |
|---|---|---|
| Overview | Resource Graph, Metrics, Logs* | Service Health event summary, per-service health tiles, Policy / Defender / Advisor / Backup tiles, Azure VMware Solution tiles (private clouds, CPU, memory, vSAN used), unhealthy resources, fired alerts, active Service Health events, health state changes over the time range, availability % per resource, recent changes (who changed what), failed operations and deployments*, full inventory |
| Virtual WAN | Resource Graph, Metrics | WANs and hubs (routing state, routing units), hub BGP peers, spoke VM utilisation, routes, spoke peering state |
| Firewall | Resource Graph, Metrics, Logs* | Health %, SNAT, throughput, observed capacity, latency, rule hits, firewall policy posture (threat intel, IDPS, TLS inspection, DNS proxy, rule counts), denied flows*, threat intel & IDPS*, DNS proxy queries* |
| ExpressRoute | Metrics | Circuit/provider state, BGP & ARP availability, bandwidth utilisation, vWAN ER gateway CPU/throughput/routes, connections |
| VPN | Metrics, Logs* | vWAN S2S & P2S gateways, VPN sites, connections, tunnel bandwidth, BGP status, drops, tunnel events* |
| Connectivity | Resource Graph, Logs* | Network Watcher connection monitors, latest result per test*, packet loss and round-trip time by path* |
| Shared Services | Resource Graph, Metrics | Bastion, DDoS coverage & attacks, DNS Private Resolver, Private DNS zone limits/links, private endpoint connection and DNS state, duplicate Private Link zones, Key Vault health |
| Build Agents | Resource Graph, Metrics, Logs* | Agent scale sets (instances running/deallocated, ADO config checks), CPU, memory, disk IOPS, heartbeats*, free disk* |
| AVS (Azure VMware Solution) | Metrics | CPU and memory per cluster, vSAN usage per datastore (75% SLA threshold) |
| AVD (Azure Virtual Desktop) | Resource Graph, Logs* | Host pools, session host status, sessions/users, connection RTT, connection success rate, time to sign in, logon time by stage, sessions by host pool, top errors |
| Storage | Metrics | Availability, latency, transactions by response type (throttling), Azure Files (FSLogix) transactions, used capacity and quota by share |
| Governance | Resource Graph, Logs* | Service retirements, planned maintenance, AVD registration tokens, Key Vault expiry events*, Policy compliance, Defender secure score/controls/alerts/recommendations, pending patches by machine (Azure Update Manager), Advisor recommendations |
| Monitoring & Backup | Resource Graph, Logs* | Workspace caps & ingestion status, ingestion by table*, workspace errors*, agent heartbeats*, machines with no Azure Monitor Agent or data collection rule, data collection rules, platform resources that are not logging*, ingestion delay by table*, platform resources with no alert rule, disabled or silent alert rules, alerts fired per day and the rules that fire most, action groups and their receivers, Service Health / Resource Health alerts per subscription, backup vaults/jobs/items, Site Recovery |
| Capacity | Resource Graph, Resource Manager | vCPU and compute quotas by subscription and region, network quotas for one subscription and region, subnet address utilisation |
| Throughput | Metrics, Logs* | Hub, firewall, ExpressRoute, VPN, P2S, storage and AVD bandwidth side by side |

\* Log panels appear once a **Log Analytics workspace** is selected, and need the matching diagnostic
settings (`AZFW*` resource-specific firewall tables, VPN `TunnelDiagnosticLog`, AVD `WVD*` tables,
Connection Monitor `NWConnectionMonitorTestResult`, Key Vault audit logs, the subscription activity log (`AzureActivity`),
Azure Monitor Agent / VM insights on build agents).

## Parameters

- **Subscriptions** – defaults to all you can see.
- **Time range** – applies to metrics and log panels.
- **Log Analytics workspace** – optional; enables the log panels.
- **Build agent name pattern** – regex matched against scale set names to identify build agent pools.

## Health signal

Overview status uses Azure Resource Health where Resource Graph has a record for the resource; otherwise
it falls back to configuration state (provisioning state, hub routing state, ExpressRoute circuit/provider
state, DNS resolver state, Private DNS limits/links, workspace ingestion status, storage primary status).
The *Signal* column shows which was used.

Those are current states. *Health state changes* lists the Resource Health transitions during the time
range, so an outage that has already recovered still shows. It covers only resource types that report
to Resource Health, and Resource Graph keeps 14 days.

*Availability over the time range* turns those transitions into a percentage per resource. Time spent
Unavailable or Degraded counts as impaired. Resources with no incident are not listed, and an incident that
began before the time range (or more than 14 days ago) is not counted.

## Editing

The JSON is generated by [src/build_workbook.py](src/build_workbook.py). Edit the script and regenerate:

```sh
python src/build_workbook.py
```

## Licence

Released under the [MIT licence](LICENSE).
