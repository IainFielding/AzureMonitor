# Azure Monitor workbooks for an Enterprise Scale platform team

Azure Monitor workbooks (and Grafana dashboards) for the team that runs the shared platform of an
Enterprise Scale (Azure Landing Zone) deployment. They are built for a **Virtual WAN** based landing zone.

There are two kinds of workbook:

- **Dashboards** show the state of the whole estate, for routine checks. These are *Platform health*,
  *Backup & Recovery*, *Azure VMware Solution*, *Microsoft Sentinel operations*, *Privileged access* and
  *Expiry and renewals*. The *Monthly availability report* is a dashboard laid out to print, for service reviews.
- **Troubleshooters** each answer one question. You type in what you know (an IP, a name, a user, a correlation
  id) and they work out the rest. They are for tickets and incidents.

## The workbooks

| Workbook | Kind | Use it to answer | Main users |
|---|---|---|---|
| [Platform health](workbook/alz-platform-health.workbook.json) | Dashboard | Is the platform healthy, and where are the problems? Covers health, capacity, throughput, governance, security and monitoring coverage across 19 tabs | Whole platform team; the daily check |
| [Backup & Recovery](workbook/backup-recovery.workbook.json) | Dashboard | Is everything that should be protected backed up or replicated, and could it be restored? | Platform operations, BC/DR owners |
| [Azure VMware Solution](workbook/avs.workbook.json) | Dashboard | Are the private clouds healthy, do they have room to grow, are they connected and monitored, and what are vCenter, ESXi and NSX reporting? | VMware / AVS team, platform operations |
| [Microsoft Sentinel operations](workbook/sentinel.workbook.json) | Dashboard | Is Sentinel collecting what it should, are its detections and automation running, is the incident queue being worked, what does it cost, and is Purview data arriving? | The team that runs Sentinel, SOC leads |
| [Privileged access](workbook/privileged-access.workbook.json) | Dashboard | Who is using privileged access, were the activations properly approved, what was granted outside PIM, and do admins sign in safely? | Identity and security owners, auditors |
| [Expiry and renewals](workbook/expiry.workbook.json) | Dashboard | What expires or retires in the next 90 days: certificates, Key Vault objects, storage keys, AVD registration tokens, policy exemptions, service retirements, planned maintenance, reservations and savings plans? | Platform operations, FinOps |
| [Monthly availability report](workbook/availability-report.workbook.json) | Report | How available was each platform service last month against its target, what incidents caused the downtime, and what did Azure Service Health report? | Service owners, management service reviews |
| [Firewalls: blocked connections](workbook/firewall-troubleshoot.workbook.json) | Troubleshooter | Is a firewall blocking this connection, and which rule did it? | Network team |
| [Routing](workbook/routing.workbook.json) | Troubleshooter | What path does traffic from A to B take, and does the reply come back the same way? | Network team |
| [DNS and private endpoints](workbook/dns-troubleshoot.workbook.json) | Troubleshooter | Why does this name not resolve, or resolve to the wrong address? | Network team, application teams |
| [What changed?](workbook/changes.workbook.json) | Troubleshooter | What changed here, who did it, and what else happened at the same time? | Anyone running an incident |
| [Why was this request refused?](workbook/policy-denials.workbook.json) | Troubleshooter | Which policy (or missing permission, lock or quota) refused this deployment, and how do I get past it? | Governance owners, application teams |
| [Azure Virtual Desktop: one user](workbook/avd-user.workbook.json) | Troubleshooter | Why is this user's session failing, slow to start, or laggy? | End-user computing, service desk |
| [Log Analytics: cost and noise](workbook/log-cost.workbook.json) | Troubleshooter | Where is ingestion going, and what could we stop paying for? | Monitoring owners, FinOps |
| [Grafana dashboards](#grafana-dashboards) | Dashboard | The platform health view in Azure Managed Grafana or Azure Monitor dashboards with Grafana | NOC screens, teams that work in Grafana |

## Which workbook for which problem

Start from the symptom:

| Symptom | Start with | Then |
|---|---|---|
| "Something is down or slow" (no specific lead) | **Platform health**: Overview, Issues board | The tab it points to; **What changed?** for the affected resource group |
| "It worked yesterday" | **What changed?**, scoped to the resource group, over the window since it last worked | **Why was this request refused?** if a change failed |
| "I can't connect from A to B" | **DNS and private endpoints**, if the target is a name | **Routing** for the path and NSGs, then **Firewalls** for the rule that blocked it |
| "My private endpoint resolves to a public IP" | **DNS and private endpoints** | The zone links, or the on-premises conditional forwarder it flags |
| "Connections time out but the firewall allowed them" | **Routing**, for asymmetric routing | **Firewalls**: *Allowed but no reply* and out-of-state drops |
| "My deployment failed with RequestDisallowedByPolicy / AuthorizationFailed / ScopeLocked" | **Why was this request refused?** with the correlation id | Create a policy exemption, or grant the role it names |
| "A user can't get onto (or is slow on) virtual desktop" | **Azure Virtual Desktop: one user** | **Platform health**: AVD and Storage (FSLogix) tabs for the host pool as a whole |
| "Our Log Analytics bill went up" | **Log Analytics: cost and noise**, *Spikes*, then select the table | **What changed?** for the resource that started sending |
| "Are we protected if this region or resource is lost?" | **Backup & Recovery** | **Platform health**: Governance (service retirements, locks) |
| "Something is wrong in AVS" (VMs slow, vSAN full, workloads unreachable) | **Azure VMware Solution**: Overview, then Capacity or Logs | *Private cloud* tab for the hub connection, Global Reach and NSX segments; **Platform health** ExpressRoute tab for the gateway |
| "Sentinel didn't alert on something it should have" | **Microsoft Sentinel operations**: Data collection (did the table go silent?) | Detections: failed runs, rules turned off, rule changes in the audit |
| "A certificate expired and the site is down" | **Expiry and renewals**: Certificates & secrets | Point the service at the versionless Key Vault secret id so the next renewal is picked up by itself |
| "Who gave this person admin, and was it approved?" | **Privileged access**: Activations and Approvals | Assignments, for roles granted outside PIM; **What changed?** for Azure role assignments |

For a connectivity ticket, work in this order: **DNS** (does the name resolve to the right address?),
**Routing** (does the traffic go the right way, both ways, and do the NSGs allow it?), **Firewalls** (which rule
decided?). Most "the firewall is blocking me" tickets turn out to be DNS or a missing return route.

## Suggested routine

| When | What |
|---|---|
| **Daily** | Platform health: the Overview's Issues board, active Service Health events and fired alerts. Backup & Recovery, Azure VMware Solution and Sentinel operations: the Overview tiles |
| **Weekly** | Expiry and renewals: the Overview, with the window at 30 days. Privileged access over 7 days: approvals (rushed or self-approved), roles assigned outside PIM, break-glass sign-ins. What changed? over 7 days with *Changed by* empty, to spot changes made outside the pipelines (Client = Azure Portal). Platform health: Security and Monitoring tabs (silent alert rules, resources not logging). Why was this request refused? over 7 days, for policies that keep blocking teams |
| **Monthly** | Monthly availability report for the month just ended, with commentary, for the service review. Expiry and renewals with the window at 90 days, to plan renewals and reservation exchanges. Log Analytics: cost and noise over 30 days. Platform health: Capacity (quotas, subnet space) and Governance (service retirements, policy exemptions about to expire, orphaned resources). Backup & Recovery: test failovers due |
| **After a platform change** | What changed? scoped to the change's resource groups, then Platform health for the services involved |

## Setting up

### Import a workbook

1. Azure portal → **Monitor** → **Workbooks** → **+ New**.
2. Open the **Advanced Editor** (`</>` on the toolbar), choose **Gallery Template**.
3. Paste the contents of the workbook's JSON file from [workbook/](workbook/) → **Apply** → **Save**.

Save the workbooks as **shared** workbooks in one resource group in the platform management subscription, so the
whole team sees one copy and an update reaches everyone. To update a workbook, open it, choose **Edit** → Advanced
Editor, paste the new JSON over the old and save. Pin the panels you look at every day to an Azure dashboard,
or use the Grafana dashboards for a NOC screen.

### Permissions

Workbooks run every query **as the person viewing them**, so each person sees only what they have access to.
For the full picture, the platform team needs:

| Access | For | Typical role |
|---|---|---|
| Read on the management group root (or every landing zone subscription) | Resource Graph and Resource Manager panels (inventory, configuration, policy, changes, routing) | Reader |
| Read on the central Log Analytics workspace | Every log panel | Log Analytics Reader |
| Read on resource metrics | Metric charts | Monitoring Reader (included in Reader) |
| Save shared workbooks in the management resource group | Importing and updating the workbooks | Workbook Contributor |

Application teams can use the troubleshooters (DNS, What changed?, Why was this request refused?) with Reader on
their own subscriptions. They see their own resources, plus whatever shared networking they can read.

### Logs to collect

Every workbook runs without a workspace, but the log panels need data in the **central platform workspace**.
Configure these once, preferably through Azure Policy (the Azure Landing Zone diagnostic policies cover most of
them) so new resources are included automatically:

| Logs | Sent from | Used by |
|---|---|---|
| Activity log (`AzureActivity`), including the *ResourceHealth* and *ServiceHealth* categories | Each subscription's diagnostic setting | What changed?, Why was this request refused?, Platform health, Sentinel operations, Privileged access, Monthly availability report |
| Key Vault audit logs (`AzureDiagnostics` or `AZKVAuditLogs`) | Each vault's diagnostic setting | Expiry and renewals (near-expiry events), Platform health |
| Azure Firewall, resource-specific (`AZFW*`); optional flow trace (`AZFWFlowTrace`) | Each firewall's diagnostic setting | Firewalls, DNS, Platform health |
| Palo Alto / Check Point CEF (`CommonSecurityLog`) | The NVAs, through a syslog forwarder with the Azure Monitor Agent | Firewalls |
| VNet flow logs with Traffic Analytics (`NTANetAnalytics`) | Network Watcher | Firewalls (NSG decisions), Platform health (Connectivity) |
| DNS security policy (`DNSQueryLogs`), Windows DNS server events (`DnsEvents` or `ASimDnsActivityLogs`) | DNS security policy on the hub and spoke networks; DNS servers | DNS and private endpoints |
| Azure Virtual Desktop (`WVD*`) | Each host pool's and AVD workspace's diagnostic setting | Azure Virtual Desktop: one user, Platform health |
| Session host performance (`Perf` or `InsightsMetrics`) and FSLogix / User Profile Service events (`Event`) | Data collection rules on the session hosts | Azure Virtual Desktop: one user |
| Entra ID sign-in and audit logs (`SigninLogs`, `AuditLogs`, …) | Entra ID diagnostic settings | Azure Virtual Desktop: one user, Platform health (Identity), Privileged access (including `AADNonInteractiveUserSignInLogs` for break-glass accounts) |
| Query audit (`LAQueryLogs`) | The workspace's own diagnostic setting, category *Audit* | Log Analytics: cost and noise (*Who reads it*) |
| Backup and Site Recovery, resource-specific (`AddonAzureBackupJobs`, `AzureSiteRecovery*`) | Each vault's diagnostic setting | Backup & Recovery |
| VMware syslog (`AVSSyslog`): vCenter, ESXi, vSAN and NSX, including NSX firewall rule logging | Each AVS private cloud's diagnostic setting, category *VMware Syslog* | Azure VMware Solution |
| Sentinel health and audit (`SentinelHealth`, `SentinelAudit`) | Sentinel → Settings → *Auditing and health monitoring* | Sentinel operations |

The Platform health workbook's *Monitoring* tab lists platform resources that are not logging, and the cost
workbook shows what each of these costs once it is flowing.

### Good to know

- **Resource Graph keeps 14 days** of resource changes and health transitions. For longer history, select a
  workspace in What changed? to add the activity log, which keeps as long as the workspace retains it.
- **The troubleshooters read configuration, not live traffic,** except where they say they read logs. Routing in
  particular cannot see routes learned over BGP; its effective-routes link gives the definitive answer.
- **Multi-tenant or Azure Lighthouse:** the subscription picker lists every subscription the viewer can see, across
  tenants, so a managed-service team can use one copy.
- **Customising:** the workbooks are generated from the scripts in [src/](src/). Change a script and regenerate (see
  [Editing](#editing)) rather than editing a workbook in the portal, or the next import overwrites your change.

## Platform health workbook

The health, capacity and throughput of every shared platform service, one tab per area, with an Overview that
gathers every problem the other tabs find into one Issues board.
[workbook/alz-platform-health.workbook.json](workbook/alz-platform-health.workbook.json).

### Tabs

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

### Parameters

- **Subscriptions** – defaults to all you can see.
- **Time range** – applies to metrics and log panels.
- **Log Analytics workspace** – optional; enables the log panels.
- **Domain controller name pattern** – regex matched against virtual machine and computer names to identify domain controllers.
- **Build agent name pattern** – regex matched against scale set names to identify build agent pools.

### Health signal

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

A single-page workbook for one question: **is a firewall blocking this connection, and which rule did it?** It
covers Azure Firewall, Palo Alto, Check Point and NSGs side by side.
[workbook/firewall-troubleshoot.workbook.json](workbook/firewall-troubleshoot.workbook.json).

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

**Is everything that should be backed up or replicated protected, is it working, and could it be restored?**
[workbook/backup-recovery.workbook.json](workbook/backup-recovery.workbook.json). It runs on Resource Graph without a workspace; pick one for job history and Site Recovery RPO trends.

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

## Azure VMware Solution workbook

**Are the private clouds healthy, do they have room to grow, are they connected and monitored, and what are
vCenter, ESXi and NSX reporting?** [workbook/avs.workbook.json](workbook/avs.workbook.json). It goes further than
the Platform health workbook's AVS tab. It runs without a workspace; pick one for the Logs tab.

| Tab | Data source | What it shows |
|---|---|---|
| Overview | Resource Graph, Metrics | Private clouds and their health, clouds not connected to a hub, clouds missing CPU / memory / vSAN alert rules, active Service Health events, Advisor recommendations; CPU, memory and vSAN tiles; alert rule coverage per cloud, Service Health events for AVS, Resource Health changes |
| Capacity | Metrics | CPU, memory and vSAN used per private cloud, CPU and memory by cluster, vSAN used % and datastore used and capacity by datastore |
| Private cloud | Resource Graph, Resource Manager | For one private cloud: vCenter, NSX and HCX endpoints, network blocks, internet access, stretched cluster, customer-managed keys; clusters and host counts, add-ons; the ExpressRoute connections that use its circuit, Global Reach connections, NSX segments, DNS forwarder zones; run command history, diagnostic settings, changes |
| Logs | Logs* | Which private clouds are sending logs, syslog by level, errors and warnings by source, vCenter alarms raised, most frequent error messages, NSX firewall drops (for rules with logging on), Azure operations on AVS from the activity log |

\* Needs each private cloud's diagnostic setting sending *VMware Syslog* to the workspace (`AVSSyslog`), and the
activity log (`AzureActivity`) for the last panel.

## Microsoft Sentinel operations workbook

**Is Sentinel collecting what it should, are its detections and automation running, is the incident queue being
worked, what does it cost, and is Purview data arriving?** [workbook/sentinel.workbook.json](workbook/sentinel.workbook.json).
It is for the team that runs Sentinel. The analysts working incidents have Sentinel's own workbooks (*Security
Operations Efficiency* and others in the Content hub). Pick the Sentinel workspace at the top; the picker lists only
workspaces with Sentinel turned on.

| Tab | Data source | What it shows |
|---|---|---|
| Overview | Logs, Resource Graph | Tables gone silent or dropped, connectors / rules / automation failing, open high-severity incidents, incidents not triaged in time, subscriptions not sending the activity log, retention and daily cap; ingestion by table, incidents per day, everything failing now |
| Data collection | Logs, Resource Manager | Every table's last record and last 24 hours against its 7-day average, data connector health, data connectors configured, subscriptions sending the activity log, ingestion over time |
| Detections | Logs, Resource Manager | Analytics rules with failed runs, every analytics rule (enabled, severity, frequency), rules to tune (closed incidents that were not true positives), noisiest rules, rules that ran without alerting, changes to rules and settings |
| Incidents | Logs | Open incidents by severity and age, incidents still New after the triage target, time to triage and close by severity, workload by owner, closed incidents by source and classification |
| Automation | Resource Manager, Logs, Resource Graph, Metrics | Automation rules, automation rule and playbook run failures, playbooks (state, managed identity), playbook runs failed and actions throttled |
| Cost and retention | Resource Graph, Logs, Resource Manager | Commitment tier, retention, daily cap and network access; billable GB per day against the tier; billable and free ingestion; billable GB by table; every table's plan and retention |
| Purview | Logs | Whether each Purview-related table is receiving data, DLP / Insider Risk / Information Protection alerts, sensitivity label activity, labels removed or downgraded |

Needs Sentinel's **Auditing and health monitoring** turned on (Sentinel → Settings) for `SentinelHealth` and
`SentinelAudit`; without it the health and audit panels are empty. Two thresholds at the top: when a table counts
as silent (default 24 hours) and the triage target (default 4 hours). Open incidents and table baselines use fixed
windows (90 and 8 days) whatever the time range.

## Privileged access workbook

**Who is using privileged access, were the activations properly approved, what was granted outside PIM, and do
admins sign in safely?** [workbook/privileged-access.workbook.json](workbook/privileged-access.workbook.json).
It needs the workspace that receives the Entra ID audit and sign-in logs (often the Sentinel workspace).

| Tab | Data source | What it shows |
|---|---|---|
| Overview | Logs, Resource Graph | Role activations, approval decisions (denied, rushed, self-approved), requests awaiting approval, roles assigned outside PIM, break-glass sign-ins, privileged accounts without phishing-resistant MFA, risky app permissions granted, Azure access admins assigned to users; activations and decisions per day |
| Activations | Logs | Activations by role and by person, every activation with its justification and ticket, weak justifications flagged; Entra roles, PIM for Groups and Azure resources |
| Approvals | Logs | Requests awaiting approval, every approval decision (approver, requester, role, minutes to decide, justification, approver's reason), decisions by approver with rushed and self-approved counts |
| Assignments | Logs, Resource Graph | Entra role assignments made outside PIM (including to service principals), eligible and active assignments made or removed in PIM, application permissions / credentials / owners with risky permissions flagged, Owner and access administrator assignments in Azure, and who made them |
| Sign-ins | Logs | Break-glass account sign-ins, how each privileged account signs in (weakest method), risky sign-ins by privileged accounts, legacy authentication, changes to Conditional Access, authentication methods and PIM role settings |

Set **Break-glass accounts** (a regular expression of their user principal names) and, if your admins use separate
accounts, the **Admin account pattern**. A *rushed* approval is one decided within 2 minutes of the request (change it
at the top). Logs record changes, not standing state: a role held permanently and not touched in the time range
does not appear, because the current members of an Entra ID role are only in Microsoft Graph.

## Expiry and renewals workbook

**What falls due in the next 90 days, and what is already overdue?**
[workbook/expiry.workbook.json](workbook/expiry.workbook.json). It gathers the dates that are otherwise spread over
the Governance tab, the Azure portal and the billing blades. Choose how far ahead to look with **Due within** (30
days to a year).

| Tab | Data source | What it shows |
|---|---|---|
| Overview | Resource Graph, Logs* | One tile per kind of deadline (certificates on services, storage account keys, AVD registration tokens, App Gateway certificates renewed by hand, Key Vault objects expiring, policy exemptions, service retirements, planned maintenance); everything held on a resource that falls due in the window; exemptions and retirements due in the window |
| Certificates & secrets | Resource Graph, Logs* | App Service, API Management, Front Door and Entra Domain Services (secure LDAP) certificates with their expiry and how they are renewed, storage account keys with a key expiration policy, AVD registration tokens; Application Gateway listener certificates and whether they come from Key Vault (latest or pinned version) or were uploaded; Key Vault certificates, secrets and keys flagged by Azure Policy's expiry audits; Key Vault's own near-expiry and expired events* |
| Exemptions & retirements | Resource Graph | Policy exemptions with their expiry, service retirements from Azure Advisor with the resources affected, planned maintenance and retirement notices from Service Health |
| Reservations | Resource Manager | Reservations and savings plans with expiry, automatic renewal, state, term and scope |

\* Needs a Log Analytics workspace that receives the Key Vault audit logs.

A workbook cannot read inside a key vault. To list every certificate, secret and key that is due across all vaults,
assign the built-in Azure Policy definitions *Certificates should not expire within the specified number of days*,
*Secrets should have more than the specified number of days before expiration* and *Keys should have more than the
specified number of days before expiration* (effect Audit) at the landing zone root, with the number of days set to
your window; the *Certificates & secrets* tab lists what they flag. Application Gateway does not expose the expiry of
an uploaded certificate, so the tab shows where each one comes from instead: one read from Key Vault by its
versionless id renews itself. Reading reservations needs the *Reservations Reader* role at the tenant (and *Savings
plan Reader* for savings plans). Entra ID application secrets are in Microsoft Graph, which workbooks cannot query,
so they are not covered.

## Monthly availability report

**How available was each platform service last month?**
[workbook/availability-report.workbook.json](workbook/availability-report.workbook.json). A single page with no tabs,
so it prints in full, for a monthly service review. Choose the **Month** (last month by default), the **Target**,
and optionally type a few lines of **Commentary** to show at the top.

| Section | What it shows |
|---|---|
| Summary tiles | Services meeting the target, the lowest service availability, Resource Health incidents and resources affected, Azure Service Health incidents (hours of impact) and planned maintenance |
| Availability by service | For every platform service: available %, target met or missed, resources, resources affected, incidents, minutes impaired, longest incident, and the average availability of its resources; minutes impaired per day |
| Six-month trend | Available % for each service in the month and the five before it |
| Resource Health incidents | Every period a platform resource was impaired, longest first, with Resource Health's cause and title |
| Azure Service Health | Incidents posted to the subscriptions (impact window, services, regions, whether a post-incident review is published) and planned maintenance |

*Available %* is the share of the month in which no resource of the service was impaired, so a single firewall
down counts against Azure Firewall for as long as it was down; *average resource %* spreads the downtime over every
resource of the service. Impaired means *Unavailable*, and optionally *Degraded* (**Count as down**). Periods
Resource Health marks as user-initiated are left out unless **User-initiated** says to count them.

The report needs the central workspace that receives every subscription's activity log: Resource Graph keeps only
14 days of health changes, but the activity log's *ResourceHealth* events keep for as long as the workspace retains
them, so set the workspace's retention to at least 7 months for the trend. The list of platform resources comes
from Resource Graph (through `arg("")` in the query), so resources deleted since are left out, and build agent
scale sets are not included. Resource Health is Microsoft's view of each resource and does not see faults in your
own configuration, so present it alongside the incidents your team handled.

## More troubleshooting workbooks

Like the firewall workbook, each of these is a single page that answers one question. See
[Which workbook for which problem](#which-workbook-for-which-problem) for when to use each.

| Workbook | Question | Needs a workspace? |
|---|---|---|
| [DNS and private endpoints](workbook/dns-troubleshoot.workbook.json) | Why does this name not resolve, or resolve to the wrong address? | Optional: adds what the DNS servers answered |
| [What changed?](workbook/changes.workbook.json) | What changed in this resource group or resource, who changed it, and what else happened at the same time? | Optional: adds the activity log |
| [Why was this request refused?](workbook/policy-denials.workbook.json) | Which policy denied my deployment, and how do I get past it? | Yes for refused requests; the policy panels work without one |
| [Azure Virtual Desktop: one user](workbook/avd-user.workbook.json) | Why is this user's session failing, slow to start, or laggy? | Yes |
| [Log Analytics: cost and noise](workbook/log-cost.workbook.json) | Where is ingestion going, and what could we stop paying for? | Yes (the one being analysed) |
| [Routing](workbook/routing.workbook.json) | What path does traffic from A to B take, and does the reply come back the same way? | No |

### DNS and private endpoints

Type the name (`mystg.blob.core.windows.net`, or a URL) and, optionally, the client's IP or the DNS server it uses.
It follows the name the way Azure DNS does:

- **The private endpoint** serving the name: whether it is approved, whether it has a DNS zone group (so its record
  is written into the zone), and the address the name should resolve to.
- **The private DNS zones** that can answer it (the `privatelink.` zone and any parent zone), how many copies of each
  exist, whether one is linked to the network the lookup is made from, and whether *internet fallback* is on.
- **The client's DNS servers** and where each looks names up: Azure-provided DNS (the client's own network), a DNS
  Private Resolver inbound endpoint (the resolver's network), Azure Firewall DNS proxy (the firewall's network, or
  the servers its policy forwards to) or a DNS server VM. Enter a forwarder's address as the DNS server to follow
  the next hop.
- **The records** in a chosen zone and the **forwarding rules** of a chosen resolver ruleset, from Resource Manager.
- **What the DNS servers answered** (with a workspace): lookups for the name from Azure Firewall DNS proxy
  (`AZFWDnsQuery`), DNS security policy (`DNSQueryLogs`) and Windows DNS servers (`DnsEvents` or
  `ASimDnsActivityLogs`), flagging answers that returned a public address, which means the private zone was not used.

### What changed?

Narrow it down by resource group, part of a resource name or id, and who made the change. From Resource Graph
(14 days): the number of changes, creates, deletes and people; changes over time; who changed things and with which
tools; the most changed resources (select one to filter); and **every change, property by property, with its
value before and after**. Platform bookkeeping (etags, provisioning state) is hidden unless *Show* is set to *All
changes*. Alongside: Resource Health transitions, alerts fired, Service Health events, role assignments created and
policy assignments or exemptions changed in the same window. With a workspace receiving the activity log
(`AzureActivity`): events by category, failed operations, deployments with duration and error, role assignments
added and removed, and every operation with its final status.

### Why was this request refused?

Paste a correlation id, a resource or deployment name, or a caller into *Search*, or leave it empty for everything.
From the activity log, every refused request is sorted by reason: **policy**, Azure restriction (region or
service), **permissions** (with the action and scope that were missing), **resource lock**, quota or capacity,
template or request errors, or conflicts. For each **policy denial** it names the assignment, the policy and its
initiative, and **why**: the field, its value and what the policy expected (`location = westeurope (NotIn
["uksouth"])`).

Select a denial, or a row of *Policies that deny*, or pick an assignment, to see from Resource Graph: its scope,
excluded scopes, enforcement mode, effect overrides and non-compliance message; **every policy in it and the effect
each resolves to** (through the initiative's and assignment's parameters); its exemptions and when they expire; and
the resources it finds non-compliant. Locks are listed too. The page explains the ways round a denial, from
changing the request to an exemption.

### Azure Virtual Desktop: one user

Enter a user's sign-in name. For their connections over the time range:

- **Connection attempts**: when, which host and host pool, how each ended, time to the desktop, round-trip time,
  bandwidth, client, client IP and gateway region.
- **Errors and their likely cause**: whether Azure Virtual Desktop failed or the host, configuration or client
  did, with a plain explanation of the common codes (no host available, not assigned, broken domain trust, sign-in
  failed, timed out, network dropped, profile failed).
- **Time to the desktop**, less any time at a credential prompt, and the slowest Windows sign-in stages (profile,
  group policy, shell).
- **Round-trip time and bandwidth** over time, per host.
- **The session hosts they used**: latest health report and failing health checks, drain mode and sessions; CPU,
  free memory and input delay; FSLogix and User Profile Service errors on those hosts, flagging ones that name the
  user.
- **Entra ID sign-ins** to Azure Virtual Desktop, with Conditional Access results.

Needs the host pool and workspace diagnostic settings (`WVD*` tables). Host load, profile events and sign-ins use
`Perf` or `InsightsMetrics`, `Event` and `SigninLogs` when they are in the same workspace.

### Log Analytics: cost and noise

Pick one workspace and set *Price per GB* to what you pay for Analytics logs, in your currency (default 2.30). It
shows the workspace's plan, commitment tier, retention and daily cap; billable GB, the average per day and an
estimated monthly cost; GB per day for the ten biggest tables; and per table its share, cost and change over the
last 7 days. **Select a table** to see its biggest sources and what inside it makes it big: the diagnostic category,
event ID, performance counter, syslog facility, firewall vendor or app. Also:

- **Spikes**: days at least twice a table's normal volume.
- **Who reads it**: each table against the queries run on the workspace (`LAQueryLogs`, from the workspace's own
  *Audit* diagnostic setting), flagging tables nobody queries.
- **Who sends it**: the biggest resources and computers across every table, behind a button because it reads every
  table.
- **Collected twice**: machines reporting through both the Azure Monitor Agent and the legacy agent, or sending
  counters to both `Perf` and `InsightsMetrics`.
- **Ingestion warnings** (daily cap, dropped or throttled data), and every table's plan and retention from
  Resource Manager.

### Routing

Enter a source and a destination IP, and optionally a port and protocol. From configuration in Resource Graph:

- **Where the addresses are**: virtual network, subnet, route table, NSGs, network interface and VM, or the VPN site
  or local network gateway that covers them, with links to the interface's *effective routes* and *effective
  security rules* in the portal.
- **The route each side picks** for the other, longest prefix first: user routes, the network's own address space,
  peerings (a peering to `HV_…` is a Virtual WAN hub), Azure's default internet route, and the private ranges Azure
  drops. The next hop is identified: Azure Firewall, an appliance (flagging one with IP forwarding off) or an
  internal load balancer.
- **The verdict**: direct, symmetric through the same appliance, or **asymmetric** (one direction skips the
  firewall, which drops the session), or no route.
- **Every NSG on the path** in the order Azure applies them (source NIC and subnet outbound, destination subnet and
  NIC inbound), the rule that decides at each, and the rules that might match first.
- **Virtual WAN**: the routing intent, network connections and route tables of the hub the networks are connected to.

Routes a network learns over BGP (ExpressRoute, VPN, Virtual WAN, Route Server) are not in Resource Graph, so where
they apply the answer is an approximation; the *effective routes* link gives the definitive one.

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

The JSON is generated: each workbook by its own script in [src/](src/), all built from the helpers in
[src/build_workbook.py](src/build_workbook.py). Edit the scripts and regenerate:

```sh
python src/build_workbook.py
python src/build_firewall_troubleshoot.py
python src/build_backup.py
python src/build_dns_troubleshoot.py
python src/build_changes.py
python src/build_policy_denials.py
python src/build_avd_user.py
python src/build_log_cost.py
python src/build_routing.py
python src/build_avs.py
python src/build_sentinel.py
python src/build_privileged_access.py
python src/build_expiry.py
python src/build_availability.py
python src/build_grafana.py
```

Commit the scripts and every generated JSON file (fourteen workbooks, two dashboards). A check on every pull request regenerates them and fails
if the committed files differ.

## Licence

Released under the [MIT licence](LICENSE).
