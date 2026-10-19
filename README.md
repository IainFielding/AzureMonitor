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
| Overview | Resource Graph, Metrics, Logs* | Issues board (one count per check across every tab, with the tab that has the detail), Service Health event summary, per-service health tiles (including Front Door, API Management and AI Foundry), Policy / Defender / Advisor / Backup tiles, Azure VMware Solution tiles (private clouds, CPU, memory, vSAN used), unhealthy resources, fired alerts, active Service Health events, health state changes over the time range, availability % per resource, recent changes (who changed what), failed operations and deployments*, full inventory |
| Virtual WAN | Resource Graph, Metrics | WANs and hubs (routing state, routing units), hub BGP peers, spoke VM utilisation, routes, spoke peering state |
| Firewall | Resource Graph, Metrics, Logs* | Health %, SNAT, throughput, observed capacity, latency, rule hits, firewall policy posture (threat intel, IDPS, TLS inspection, DNS proxy, rule counts), denied flows*, threat intel & IDPS*, DNS proxy queries* |
| ExpressRoute | Metrics | Circuit/provider state, BGP & ARP availability, bandwidth utilisation, vWAN ER gateway CPU/throughput/routes, connections |
| VPN | Metrics, Logs* | vWAN S2S & P2S gateways, VPN sites, connections, tunnel bandwidth, BGP status, drops, tunnel events* |
| Connectivity | Resource Graph, Logs* | Network Watcher connection monitors, latest result per test*, packet loss and round-trip time by path*, VNet flow log coverage, traffic by flow type*, top talkers* and top denied flows* |
| App Delivery | Resource Graph, Metrics, Logs* | Application Gateway backend health, responses, latency and capacity; Front Door origin health, error rates, latency and WAF actions; API Management capacity, requests by response, duration and failing operations*; WAF policies and their mode; top WAF rule matches* |
| AI Foundry | Resource Graph, Metrics, Resource Manager, Logs* | AI Foundry and Azure OpenAI resources, model deployments, hubs and projects, requests by status and deployment, tokens, time to response, provisioned utilisation, model quota for one subscription and region, failed or throttled requests* |
| Shared | Resource Graph, Metrics | Bastion, DDoS coverage & attacks, DNS Private Resolver, Private DNS zone limits/links, private endpoint connection and DNS state, duplicate Private Link zones, Key Vault health |
| Identity | Resource Graph, Metrics, Logs* | Entra ID sign-ins, failure reasons, Conditional Access blocks, failing service principals, users at risk and directory changes*, Entra Domain Services replica sets and health alerts, domain controller VMs (health, power, pending patches), CPU and memory, heartbeats*, directory/replication/DNS errors*, failed logons and lockouts* |
| Agents | Resource Graph, Metrics, Logs* | Agent scale sets (instances running/deallocated, ADO config checks), CPU, memory, disk IOPS, heartbeats*, free disk* |
| AVS (Azure VMware Solution) | Metrics | CPU and memory per cluster, vSAN usage per datastore (75% SLA threshold) |
| AVD (Azure Virtual Desktop) | Resource Graph, Logs* | Host pools, session host status, sessions/users, connection RTT, connection success rate, time to sign in, logon time by stage, sessions by host pool, top errors |
| Storage | Metrics | Availability, latency, transactions by response type (throttling), Azure Files (FSLogix) transactions, used capacity and quota by share |
| Governance | Resource Graph, Logs* | Service retirements, planned maintenance, AVD registration tokens, Key Vault expiry events*, policy exemptions and their expiry, Policy compliance, subscriptions outside the management group hierarchy, resource locks by service, orphaned resources, empty resource groups, pending patches by machine (Azure Update Manager), Advisor recommendations |
| Security | Resource Graph, Logs* | Defender for Cloud secure score, controls, active alerts and unhealthy recommendations, Defender plans on and off per subscription, Owner and access administrator assignments by scope, Sentinel open incidents, time to close and failing connectors or rules* |
| Monitoring | Resource Graph, Logs* | Workspace caps & ingestion status, ingestion by table*, workspace errors*, agent heartbeats*, machines with no Azure Monitor Agent or data collection rule, data collection rules, platform resources that are not logging*, ingestion delay by table*, platform resources with no alert rule, disabled or silent alert rules, alerts fired per day and the rules that fire most, action groups and their receivers, Service Health / Resource Health alerts per subscription, backup vaults/jobs/items, virtual machines with no backup, Site Recovery |
| Capacity | Resource Graph, Resource Manager | vCPU and compute quotas by subscription and region, network quotas for one subscription and region, month-to-date cost by service and budgets for one subscription, subnet address utilisation |
| Throughput | Metrics, Logs* | Hub, firewall, ExpressRoute, VPN, P2S, storage and AVD bandwidth side by side |

\* Log panels appear once a **Log Analytics workspace** is selected, and need the matching diagnostic
settings (`AZFW*` resource-specific firewall tables, VPN `TunnelDiagnosticLog`, AVD `WVD*` tables,
Connection Monitor `NWConnectionMonitorTestResult`, Traffic Analytics `NTANetAnalytics`, Application Gateway and Front Door WAF logs, API Management gateway logs, AI Foundry request logs, Key Vault audit logs, the subscription activity log (`AzureActivity`),
Entra ID sign-in, audit, service principal sign-in and risky user logs,
Sentinel incidents and health (`SecurityIncident`, `SentinelHealth`),
Windows event logs and security events from domain controllers,
Azure Monitor Agent / VM insights on build agents).

## Parameters

- **Subscriptions** – defaults to all you can see.
- **Time range** – applies to metrics and log panels.
- **Log Analytics workspace** – optional; enables the log panels.
- **Domain controller name pattern** – regex matched against virtual machine and computer names to identify domain controllers.
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

## Firewall troubleshooting workbook

A second, single-page workbook for one question: **is a firewall blocking this connection, and which rule did
it?** It covers Azure Firewall, Palo Alto, Check Point and NSGs side by side. Import
[workbook/firewall-troubleshoot.workbook.json](workbook/firewall-troubleshoot.workbook.json) the same way as above.

Pick the workspace your firewalls log to, then fill in whatever you know. Every filter is optional:

| Filter | Takes |
|---|---|
| Platforms | Azure Firewall, Palo Alto, Check Point, NSG. Empty for all |
| Firewalls | Firewalls that logged in the time range. Empty for all of them |
| Source IP / CIDR | IPs or ranges, comma separated |
| Destination IP / CIDR / FQDN | IPs, ranges or FQDNs. FQDNs match as whole words, so `contoso.com` matches `www.contoso.com` |
| Destination port | Ports and ranges, comma separated, e.g. `1433, 11000-11999` |
| Match hops on | Source, destination and port (default), or destination and port only when the source is NATed between firewalls |
| Show | Blocked only (default), allowed only, or both. The path view always uses both |

The key panel is **Path through the firewalls**. For traffic that crosses several hops (source → Azure
Firewall → Palo Alto or Check Point → NSG → destination) it lines each flow up across them, shows what each did
and which rule decided it, and names where the flow stopped: blocked at a hop, asymmetric routing (an NVA dropping
packets that did not start a session), no reply from the destination (allowed everywhere, but nothing came back),
allowed by Azure Firewall but never seen at the NVA (a routing or logging problem), seen at the NVA but never at
Azure Firewall (a routing bypass), or allowed everywhere (look past the network). **Allowed but no reply** lists
the unanswered sessions and out-of-state drops behind those verdicts. If Azure Firewall
SNATs traffic before the NVA, set *Match hops on* to *Destination and port* so the hops still line up.

Other panels: events by verdict and source, events over time, the latest verdict per flow and firewall (always
blocked and allowed, so a flow fixed by a rule change shows, and a flow through two firewalls shows what each
did), the rules that matched, top sources and destinations, the latest 500 events, and Azure Firewall DNS
failures.

| Platform | Logs read | Notes |
|---|---|---|
| Azure Firewall | `AZFWNetworkRule`, `AZFWApplicationRule`, `AZFWNatRule`, `AZFWThreatIntel`, `AZFWIdpsSignature`, `AZFWDnsQuery`, `AZFWFqdnResolveFailure` | Resource-specific diagnostic tables; the legacy `AzureDiagnostics` format is not read. Traffic that matched no rule is labelled *default deny* |
| Palo Alto | `CommonSecurityLog` where the vendor is Palo Alto Networks | CEF traffic and threat logs. Rule name from the custom string labelled *Rule* |
| Check Point | `CommonSecurityLog` where the vendor is Check Point | CEF from Log Exporter. Rule name and layer from the custom strings labelled *Rule Name* and *Layer Name* |
| NSG | `NTANetAnalytics` | VNet flow logs with Traffic Analytics. Carries reply byte counts, so it also shows unanswered sessions |
| Azure Firewall (optional) | `AZFWFlowTrace` | Flow trace logs. Adds Azure Firewall packets outside a known session to the asymmetric routing check |

Palo Alto and Check Point must send CEF (the Sentinel connectors do), and only rules with logging turned on
appear. Plain syslog in the `Syslog` table is not read. *No reply* uses byte counts, which Palo Alto, Check Point
and VNet flow logs carry and Azure Firewall rule logs do not.

**SQL Managed Instance checks** sit behind a button at the bottom, since they are not needed every time. From
Resource Graph: each instance's connection type and the ports it needs (Proxy 1433; Redirect also 11000-11999 to
the instance subnet; 3342 for the public endpoint), the routes on its subnet (service routes, and default routes
to a firewall), the NSG rules on its subnet that cover those ports, and changes to the instance, its network,
route table and NSG over the time range.

## Backup & Recovery workbook

A third workbook: **is everything that should be backed up or replicated protected, is it working, and could it
be restored?** Import [workbook/backup-recovery.workbook.json](workbook/backup-recovery.workbook.json) the same way
as above. It runs on Resource Graph without a workspace; pick one for job history and Site Recovery RPO trends.

| Tab | Data source | What it shows |
|---|---|---|
| Overview | Resource Graph | Failed jobs, backup items with problems, VMs with no backup, replication problems, vaults without soft delete or immutability, SQL with local-only backups; jobs per day; protected items by workload; every item needing attention with the reason |
| Azure Backup | Resource Graph, Logs* | Recovery Services and Backup vaults (redundancy, cross-region restore, soft delete, immutability, multi-user authorisation, job failure alerts), protected items with stale backups flagged, Backup vault instances, jobs that did not complete, job trend, duration and failure codes*, virtual machines with no backup |
| Site Recovery | Resource Graph, Logs* | Replicated items (health, RPO, last test failover, errors), recovery plans and when they were last tested, failed jobs, RPO over time* |
| SQL | Resource Graph, Resource Manager | Azure SQL databases (backup redundancy, point-in-time restore window), failover groups, latest long-term retention backup per database (one subscription and region), managed instances, SQL Server VMs and whether Azure Backup protects them, SQL / SAP HANA databases in Azure Backup |
| Storage | Resource Graph, Resource Manager | Storage accounts by blob and file share backup, Azure Files shares in vaults, blob and file share soft delete, versioning and point-in-time restore for a chosen account |

\* Needs the vaults' diagnostic settings in *Resource specific* mode (`AddonAzureBackupJobs`,
`AzureSiteRecoveryReplicatedItems`, `AzureSiteRecoveryJobs`).

Two thresholds at the top: when a backup counts as stale (default 26 hours) and when a test failover is due
(default 180 days).

## Grafana dashboards

Two dashboards for [Azure Monitor dashboards with Grafana](https://learn.microsoft.com/azure/azure-monitor/visualize/visualize-grafana-overview)
are generated from the same definition as the workbook, so they stay in step with it:

| File | What it is |
|---|---|
| [grafana/alz-platform-health.dashboard.json](grafana/alz-platform-health.dashboard.json) | Every workbook tab as a collapsible row. A collapsed row loads nothing until it is opened. |
| [grafana/alz-platform-overview.dashboard.json](grafana/alz-platform-overview.dashboard.json) | The Overview tab only: Issues, at-a-glance tiles, platform services and resources needing attention. |

To import one: Azure portal → **Monitor** → **Dashboards with Grafana** → **New** → **Import**, load the JSON
file, then choose a subscription, resource group and region to save it in.

They carry the workbook's Resource Graph and Log Analytics panels, its text, and its subscription, workspace
and name-pattern parameters. They do **not** carry:

- **Metric charts.** A Grafana metrics query covers one subscription and region, where a workbook chart
  covers every resource in the estate. Each row says how many charts it left in the workbook.
- **Resource Manager panels** (network quota, cost, budgets, model quota): the data source cannot call
  Resource Manager.
- **Workbook behaviour:** load-on-demand buttons become collapsed rows, and the "select a workspace" hints
  are dropped, so a log panel with no workspace selected shows an error or no data.

Tiles become stat panels. A tile's status shows as a coloured dot before its name, not as an icon, and the
line of detail under the number is not shown. The workspace picker lists the workspaces of one subscription,
chosen in the *Workspace subscription* picker beside it.

## Performance

A tab runs its queries only when it is first opened, so the cost of opening the workbook is the Overview.
Its heaviest tables (health history, availability, changes, failed operations and the full inventory) wait
behind two buttons under *History and inventory*. Resource pickers that can match hundreds of resources
(key vaults, public IPs) start with the first 10 selected; choose **All** in the picker to chart every one.
A tab stays loaded once opened, so a long session that has visited most tabs is heavier than a fresh one:
reload the page to reset it.

## Editing

The JSON is generated by [src/build_workbook.py](src/build_workbook.py). Edit the script and regenerate:

```sh
python src/build_workbook.py
python src/build_firewall_troubleshoot.py
python src/build_backup.py
python src/build_grafana.py
```

Commit the scripts and all five generated JSON files. A check on every pull request regenerates them and fails
if the committed files differ.

## Licence

Released under the [MIT licence](LICENSE).
