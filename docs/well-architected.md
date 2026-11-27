# Well-Architected Framework

*Reference for [well-architected.workbook.json](../workbook/well-architected.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

A workload's gaps against the five pillars of the Azure Well-Architected Framework: Reliability, Security, Cost Optimization, Operational Excellence and Performance Efficiency. Each pillar combines Azure Advisor's recommendations with configuration checks read from Azure Resource Graph, so no workspace is needed; picking one adds the checks only logs can answer. The Assessment tab records the answers to the Well-Architected checklist and scores each pillar.

It has 64 panels across 8 tabs. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Workload tag | The tag whose value names the workload a resource belongs to. Tag names here match case. |
| Workload | The workloads to review, from the values of the workload tag. All includes untagged resources. |
| Log Analytics workspace | Optional. The workspaces the workload sends its logs to. Adds the checks only logs can answer: heartbeats, request failures, refused access, resources sending no logs, ingestion, and CPU and memory. |
| Time range | The period the log-based panels cover. The Resource Graph panels show the current state. |
| RE:01 Simplicity | Is the design kept as simple as the business requirements allow, with nothing that does not add value? |
| RE:02 Critical flows | Have the user and system flows been identified and rated by how critical they are? |
| RE:03 Failure modes | Has a failure mode analysis been done for each critical flow and its dependencies? |
| RE:04 Targets | Are availability and recovery targets (SLO, RTO, RPO) defined and agreed with the business? |
| RE:05 Redundancy | Is there redundancy at every layer, across availability zones and, where the targets need it, regions? |
| RE:06 Scaling | Does the workload scale in time to meet demand, automatically where it can? |
| RE:07 Self-healing | Do components cope with transient faults and failed dependencies (retries, timeouts, circuit breakers, queues)? |
| RE:08 Resilience testing | Is resilience tested, for example with fault injection or Azure Chaos Studio? |
| RE:09 Disaster recovery | Is there a documented disaster recovery plan, with restores and failover tested against the targets? |
| RE:10 Health model | Is health measured and modelled, with alerts on the signals that show the workload is degraded? |
| Notes | Accepted risks, owners and dates for Reliability, kept with the saved workbook. |
| SE:01 Baseline | Is there a security baseline for the workload, aligned to its compliance requirements? |
| SE:02 Secure development | Is software built through a secure development lifecycle, with dependencies and the supply chain checked? |
| SE:03 Data classification | Is the data the workload handles classified and labelled by sensitivity? |
| SE:04 Segmentation | Is the workload segmented, with deliberate boundaries between components and environments? |
| SE:05 Identity and access | Is access granted to identities with least privilege, conditional access and an audit trail, rather than by keys? |
| SE:06 Network controls | Is network traffic isolated and filtered, with private endpoints for data services? |
| SE:07 Encryption | Is data encrypted in transit and at rest with current standards (TLS 1.2 or later)? |
| SE:08 Hardening | Are components hardened, with unused features, ports and accounts removed? |
| SE:09 Secrets | Are secrets, keys and certificates kept in Key Vault, rotated, and never in code or configuration? |
| SE:10 Threat detection | Is the workload monitored for threats, with alerts going to people who respond? |
| SE:11 Security testing | Is the workload tested for security (penetration tests, code scanning) on a schedule? |
| SE:12 Incident response | Is there a tested incident response plan for a security breach of this workload? |
| Notes | Accepted risks, owners and dates for Security, kept with the saved workbook. |
| CO:01 Accountability | Does the team know what the workload costs and who is accountable for it? |
| CO:02 Cost model | Is there a cost model that estimates cost from expected usage and growth? |
| CO:03 Cost data | Is cost data collected, tagged by workload and reviewed regularly? |
| CO:04 Guardrails | Are there budgets, alerts and policies that catch unexpected spend? |
| CO:05 Best rates | Are the best rates in use: reservations, savings plans, Azure Hybrid Benefit, dev/test pricing? |
| CO:06 Billing increments | Is usage aligned to how each service bills (instance sizes, hourly units, tiers)? |
| CO:07 Component costs | Are idle or oversized components removed or resized? |
| CO:08 Environment costs | Do non-production environments cost less than production (smaller sizes, shut down out of hours)? |
| CO:09 Flow costs | Is spending prioritised by the business value of each flow? |
| CO:10 Data costs | Are storage tiers, retention and log ingestion matched to how the data is used? |
| CO:11 Code costs | Is code efficient in the resources it uses (calls, compute, data transfer)? |
| CO:12 Scaling costs | Does capacity scale in as readily as it scales out, so it follows demand? |
| CO:13 Personnel time | Is the time people spend running the workload measured and reduced? |
| CO:14 Consolidation | Are resources and responsibilities consolidated where that lowers cost without adding risk? |
| Notes | Accepted risks, owners and dates for Cost Optimization, kept with the saved workbook. |
| OE:01 Team and culture | Does the team have clear roles, shared standards and a habit of learning from incidents? |
| OE:02 Operational tasks | Are routine, as-needed and emergency operational tasks documented and repeatable? |
| OE:03 Planning | Is new work planned, prioritised and tracked in a backlog? |
| OE:04 Quality | Are development and testing standardised, with automated tests in the delivery pipeline? |
| OE:05 Infrastructure as code | Is all infrastructure deployed from code kept in source control? |
| OE:06 Pipelines | Do all changes go through a pipeline, with the same steps for every environment? |
| OE:07 Monitoring | Is there a monitoring system with logs, metrics and alerts for every component? |
| OE:08 Incident management | Is there a structured incident process, with on-call, runbooks and post-incident reviews? |
| OE:09 Automation | Are repetitive tasks (patching, scaling, certificate renewal) automated? |
| OE:10 Automation by design | Was automation designed in from the start rather than added later? |
| OE:11 Safe deployment | Are deployments progressive (rings, canary, blue-green) with a tested rollback? |
| Notes | Accepted risks, owners and dates for Operational Excellence, kept with the saved workbook. |
| PE:01 Targets | Are performance targets (response times, throughput) defined for the critical flows? |
| PE:02 Capacity planning | Is capacity planned against expected demand, including peaks and growth? |
| PE:03 Service selection | Were the services, SKUs and tiers chosen against the performance targets? |
| PE:04 Performance data | Is performance data collected for every component and flow? |
| PE:05 Scaling and partitioning | Can the workload scale out, and partition its data, where load requires? |
| PE:06 Performance testing | Is performance tested (load and stress tests) before release? |
| PE:07 Code and infrastructure | Are code and infrastructure tuned for performance, on current hardware? |
| PE:08 Data performance | Is data access optimised (indexing, caching, partitioning)? |
| PE:09 Critical flows | Do the critical flows get priority for capacity and performance? |
| PE:10 Operational tasks | Are operational tasks (backups, scans, deployments) timed so they do not slow the workload? |
| PE:11 Live issues | Is there a process to find and fix performance problems in production? |
| PE:12 Continuous improvement | Is performance reviewed and improved continuously, not only when it fails? |
| Notes | Accepted risks, owners and dates for Performance Efficiency, kept with the saved workbook. |

## Tab: Overview

### Pillars

#### Tile reliability

*Tiles · Azure Resource Graph* · reads `advisorresources`

#### Tile security

*Tiles · Azure Resource Graph* · reads `advisorresources`

#### Tile cost

*Tiles · Azure Resource Graph* · reads `advisorresources`

#### Tile operations

*Tiles · Azure Resource Graph* · reads `advisorresources`

#### Tile performance

*Tiles · Azure Resource Graph* · reads `advisorresources`

### Advisor score

#### Advisor score

*Tiles · Azure Resource Graph* · reads `advisorresources`

When there is nothing to show: *Advisor score is not available for the selected subscriptions.*

### Self-assessment score
From the answers on the **Assessment** tab: Yes scores 2, Partly 1 and No 0, out of every question answered other than Not applicable.

#### Self score

*Tiles · Azure Resource Graph* · reads `resourcecontainers`

> **How to use this.** Pick the workload at the top (the **Workload tag** names the tag that identifies one), then
> work through the pillar tabs. Each pillar tile counts the configuration checks that fail plus Azure Advisor's
> recommendations for that pillar; red means at least one is high severity. *Advisor score* is Microsoft's own
> 0-100 score per pillar, averaged across the selected subscriptions; it is not narrowed to the workload. The checks
> here are the settings a reviewer would otherwise open each resource to find. Pick a **Log Analytics workspace**
> to add what only logs show (heartbeats, failed requests, refused access, resources sending no logs, ingestion, CPU
> and memory). Design, process and recovery testing are not in any setting: answer them on the **Assessment** tab,
> which follows the same checklist as the
> [Azure Well-Architected Review](https://learn.microsoft.com/assessments/azure-architecture-review/).

#### Azure Advisor recommendations by pillar and impact

*Bar chart · Azure Resource Graph* · reads `advisorresources`

When there is nothing to show: *Advisor has no recommendations for the workload.*

## Tab: Workloads

### Workloads
Every workload side by side: the configuration checks that fail for each, by pillar, and its Azure Advisor recommendations. Workloads are the values of the **Workload tag**; set **Workload** to *All* to compare them all, and pick one to review it on the pillar tabs. *(untagged)* is every resource without the tag, which a review cannot assign to anyone.

#### Findings by workload

*Table · Azure Resource Graph* · reads `advisorresources`

Columns: Workload, Resources, Resources with findings, Findings, High severity, Reliability, Security, Cost Optimization, Operational Excellence, Performance Efficiency, Advisor recommendations, Advisor high impact.

When there is nothing to show: *No resources in the selected subscriptions.*

## Tab: Reliability

### Reliability
Can the workload survive the failure of a zone, an instance or a dependency, and recover its data? The checks look for single instances, resources not spread across availability zones, locally redundant data and SKUs Azure has retired. A resource in a region without availability zones is flagged too: record it as accepted if so.

#### Reliability tiles

*Tiles · Azure Resource Graph*

#### Reliability advisor tile

*Tiles · Azure Resource Graph* · reads `advisorresources`

#### Azure Advisor: Reliability (select a row for the resources)

*Table · Azure Resource Graph* · reads `advisorresources`

Columns: Recommendation, Impact, Resources, Action.

When there is nothing to show: *Advisor has no Reliability recommendations for the workload.*

#### Resources for the selected recommendation

*Table · Azure Resource Graph* · reads `advisorresources`, `resourcecontainers`

Columns: Resource, Impact, Subscription, Updated.

#### Configuration checks that fail

*Table · Azure Resource Graph*

Columns: Severity, Finding, Resources, What to do, Resource types.

When there is nothing to show: *Every configuration check passes for the workload.*

#### Findings by resource

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Finding, Severity, Resource, Detail, Resource group, Subscription.

When there is nothing to show: *Every configuration check passes for the workload.*

#### VMs with no backup or replication

*Table · Azure Resource Graph* · reads `recoveryservicesresources`

Columns: Virtual machine, OS, Power, Resource group, Location.

When there is nothing to show: *Every VM is backed up or replicated.*

#### Resources currently unavailable or degraded (Resource Health)

*Table · Azure Resource Graph* · reads `healthresources`

Columns: Resource, State, Reason, Summary, Since.

When there is nothing to show: *Resource Health reports nothing unavailable or degraded.*

> Recovery is the part of reliability settings show least: the **Backup & Recovery** workbook has failed jobs, stale backups and test failovers. Record a recovery time and recovery point target for the workload, and test a restore against them.

> Pick a **Log Analytics workspace** at the top to add the checks only logs can answer on this tab. They read the workspace the workload sends its logs to; pick several if its logs are split.

#### Machine availability from heartbeats (hours reporting in the time range)

*Table · Log Analytics* · reads `Heartbeat`

Columns: Machine, Computer, Availability %, Hours reporting, Hours expected, Last heartbeat.

When there is nothing to show: *No heartbeats from the workload's machines in the selected workspaces.*

#### Application requests: failures and response time (Application Insights)

*Table · Log Analytics* · reads `AppRequests`

Columns: Application Insights, App, Requests, Failed, Failed %, 95th percentile ms.

When there is nothing to show: *No requests from workspace-based Application Insights in the workload.*

> A machine is counted for the hours since it was first seen in the range, so a new machine is not marked down for the time before it existed; a machine shut down on purpose still counts as down. A workload machine at 0% may send its heartbeats to a workspace not selected.

## Tab: Security

### Security
Is the workload's data and access protected? The checks look for public network access, anonymous access, old TLS versions and key-based authentication where Entra ID could be used. The NSG rules and other internet exposure are on the **Azure Policy compliance** workbook's *Public exposure* tab.

#### Security tiles

*Tiles · Azure Resource Graph*

#### Security advisor tile

*Tiles · Azure Resource Graph* · reads `advisorresources`

#### Azure Advisor: Security (select a row for the resources)

*Table · Azure Resource Graph* · reads `advisorresources`

Columns: Recommendation, Impact, Resources, Action.

When there is nothing to show: *Advisor has no Security recommendations for the workload.*

#### Resources for the selected recommendation

*Table · Azure Resource Graph* · reads `advisorresources`, `resourcecontainers`

Columns: Resource, Impact, Subscription, Updated.

#### Configuration checks that fail

*Table · Azure Resource Graph*

Columns: Severity, Finding, Resources, What to do, Resource types.

When there is nothing to show: *Every configuration check passes for the workload.*

#### Findings by resource

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Finding, Severity, Resource, Detail, Resource group, Subscription.

When there is nothing to show: *Every configuration check passes for the workload.*

#### Defender for Cloud recommendations for the workload

*Table · Azure Resource Graph* · reads `securityresources`

When there is nothing to show: *No unhealthy Defender for Cloud recommendations (or Defender is not reporting).*

#### Secure score by subscription

*Table · Azure Resource Graph* · reads `securityresources`, `resourcecontainers`

Columns: Subscription, Score %.

When there is nothing to show: *No secure score: Defender for Cloud is not reporting for the selected subscriptions.*

#### Defender for Cloud security alerts on the workload (last 30 days)

*Table · Azure Resource Graph* · reads `securityresources`

Columns: Time, Severity, Alert, Resource, Status.

When there is nothing to show: *No Defender for Cloud alerts on the workload in the last 30 days.*

> Pick a **Log Analytics workspace** at the top to add the checks only logs can answer on this tab. They read the workspace the workload sends its logs to; pick several if its logs are split.

#### Requests refused to Key Vault and Storage (403 Forbidden)

*Table · Log Analytics* · reads `AZKVAuditLogs`, `AzureDiagnostics`, `StorageBlobLogs`

When there is nothing to show: *No refused requests in the time range (or the vaults and accounts send no logs here).*

## Tab: Cost Optimization

### Cost Optimization
Is the workload paying for anything it does not use? The checks look for idle resources, licences paid in the VM price and data kept longer than needed. Advisor's right-sizing, reservation and savings plan recommendations carry its estimated savings a year. Resource Graph holds no spend: use Cost Management for what the workload costs.

#### Cost tiles

*Tiles · Azure Resource Graph*

#### Cost advisor tile

*Tiles · Azure Resource Graph* · reads `advisorresources`

#### Azure Advisor: Cost Optimization (select a row for the resources)

*Table · Azure Resource Graph* · reads `advisorresources`

Columns: Recommendation, Impact, Resources, Savings, Currency, Action.

When there is nothing to show: *Advisor has no Cost Optimization recommendations for the workload.*

#### Resources for the selected recommendation

*Table · Azure Resource Graph* · reads `advisorresources`, `resourcecontainers`

Columns: Resource, Impact, Subscription, Updated.

#### Configuration checks that fail

*Table · Azure Resource Graph*

Columns: Severity, Finding, Resources, What to do, Resource types.

When there is nothing to show: *Every configuration check passes for the workload.*

#### Findings by resource

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Finding, Severity, Resource, Detail, Resource group, Subscription.

When there is nothing to show: *Every configuration check passes for the workload.*

> Savings are Azure Advisor's own estimate for a year. The **Cloud Center of Excellence** workbook's *Cost* tab rolls the same savings and idle resources up by subscription.

> Pick a **Log Analytics workspace** at the top to add the checks only logs can answer on this tab. They read the workspace the workload sends its logs to; pick several if its logs are split.

### Measure log ingestion for the workload (reads every table) (loads when asked)

#### Billable log ingestion by resource in the time range

*Table · Log Analytics*

Columns: Resource, GB, Largest table, Largest table GB, Tables.

When there is nothing to show: *The workload's resources sent no billable logs to the selected workspaces.*

## Tab: Operational Excellence

### Operational Excellence
Is the workload observable and maintained? The checks look for machines without the Azure Monitor Agent, patching that is not assessed, AKS clusters with no monitoring or upgrades, retired Application Insights, disabled alerting, and changes made by hand in the portal rather than through a pipeline.

#### Operations tiles

*Tiles · Azure Resource Graph*

#### Operations advisor tile

*Tiles · Azure Resource Graph* · reads `advisorresources`

#### Azure Advisor: Operational Excellence (select a row for the resources)

*Table · Azure Resource Graph* · reads `advisorresources`

Columns: Recommendation, Impact, Resources, Action.

When there is nothing to show: *Advisor has no Operational Excellence recommendations for the workload.*

#### Resources for the selected recommendation

*Table · Azure Resource Graph* · reads `advisorresources`, `resourcecontainers`

Columns: Resource, Impact, Subscription, Updated.

#### Configuration checks that fail

*Table · Azure Resource Graph*

Columns: Severity, Finding, Resources, What to do, Resource types.

When there is nothing to show: *Every configuration check passes for the workload.*

#### Findings by resource

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Finding, Severity, Resource, Detail, Resource group, Subscription.

When there is nothing to show: *Every configuration check passes for the workload.*

#### Monitoring agent on machines

*Table · Azure Resource Graph*

Columns: Machine, Agent, Kind, OS, Power, Resource group.

When there is nothing to show: *No VMs or Arc servers in the workload.*

#### Patching (Azure Update Manager)

*Table · Azure Resource Graph* · reads `patchassessmentresources`

Columns: Machine, Status, Critical, Security, Reboot pending, Assessed, Resource group.

When there is nothing to show: *No VMs or Arc servers in the workload.*

#### Changes by tool (last 14 days)

*Pie chart · Azure Resource Graph* · reads `resourcechanges`

When there is nothing to show: *No changes in the last 14 days.*

#### Changes made in the Azure portal (last 14 days)

*Table · Azure Resource Graph* · reads `resourcechanges`

Columns: Time, Resource, Change, Changed by.

When there is nothing to show: *No changes were made in the portal in the last 14 days.*

#### Azure retirements affecting the workload (Azure Advisor)

*Table · Azure Resource Graph* · reads `advisorresources`

Columns: Retiring, Retirement date, Days left, Resources, Action.

When there is nothing to show: *Advisor reports no retirements for the workload.*

#### Alerts fired on the workload (last 30 days)

*Table · Azure Resource Graph* · reads `alertsmanagementresources`

When there is nothing to show: *No alerts fired on the workload in the last 30 days.*

> An alert that fires often and is never acted on trains people to ignore alerts: tune its threshold, or remove it. A workload with no alerts at all may simply have none set up.

> Pick a **Log Analytics workspace** at the top to add the checks only logs can answer on this tab. They read the workspace the workload sends its logs to; pick several if its logs are split.

### Find resources sending no logs (reads every table) (loads when asked)

> Diagnostic settings are not in Resource Graph, so this looks at the workspaces instead: the workload's resources (of the types that can send resource logs, and its machines) that wrote nothing to any selected workspace in the last day. It needs a workload picked at the top: with *All* there is no list to compare against.

#### Workload resources that sent nothing to the selected workspaces (last 24 hours)

*Table · Log Analytics*

Columns: Resource, Type.

When there is nothing to show: *Every resource of the workload sent logs, or no single workload is picked.*

## Tab: Performance Efficiency

### Performance Efficiency
Can the workload scale and does it use current hardware? The checks look for older VM sizes, Standard HDD disks, accelerated networking turned off, legacy storage and App Service tiers, and compute with no autoscale.

#### Performance tiles

*Tiles · Azure Resource Graph*

#### Performance advisor tile

*Tiles · Azure Resource Graph* · reads `advisorresources`

#### Azure Advisor: Performance Efficiency (select a row for the resources)

*Table · Azure Resource Graph* · reads `advisorresources`

Columns: Recommendation, Impact, Resources, Action.

When there is nothing to show: *Advisor has no Performance Efficiency recommendations for the workload.*

#### Resources for the selected recommendation

*Table · Azure Resource Graph* · reads `advisorresources`, `resourcecontainers`

Columns: Resource, Impact, Subscription, Updated.

#### Configuration checks that fail

*Table · Azure Resource Graph*

Columns: Severity, Finding, Resources, What to do, Resource types.

When there is nothing to show: *Every configuration check passes for the workload.*

#### Findings by resource

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Finding, Severity, Resource, Detail, Resource group, Subscription.

When there is nothing to show: *Every configuration check passes for the workload.*

#### Autoscale on scale sets and App Service plans

*Table · Azure Resource Graph*

Columns: Resource, Autoscale, Kind, Sku, Instances, Min, Max, Resource group.

When there is nothing to show: *No scale sets or App Service plans that can autoscale in the workload.*

> Pick a **Log Analytics workspace** at the top to add the checks only logs can answer on this tab. They read the workspace the workload sends its logs to; pick several if its logs are split.

#### Machine CPU and memory in the time range (right-sizing)

*Table · Log Analytics* · reads `Perf`, `InsightsMetrics`

Columns: Machine, Fit, CPU average %, CPU 95th percentile %, Memory used 95th percentile %.

When there is nothing to show: *No CPU or memory counters from the workload's machines in the selected workspaces.*

> *Possibly oversized* is a 95th percentile CPU under 20% with memory under 50%: check the busiest period of the month before resizing. Memory on Windows is committed bytes in use.

## Tab: Assessment

### Assessment
The questions of the Well-Architected checklist for each pillar, for the design, process and testing that no
setting shows. Answer each for the workload being reviewed: **Yes**, **Partly**, **No** or **Not applicable**
(hover over a question's name for the whole question). Each pillar is scored from its answers, and every No or
Partly is listed at the bottom as the gaps to act on. Where this workbook has evidence for a question, the table
says where to look.

The answers are workbook parameters: to keep them, **Save** the workbook once answered (or **Save As** a copy per
workload, and per review date). Export the tables to Excel for the review record.

#### Assess score

*Tiles · Azure Resource Graph* · reads `resourcecontainers`

### Reliability
The [Reliability checklist](https://learn.microsoft.com/azure/well-architected/reliability/checklist) explains each question and what good looks like.

#### Assess re

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Id, Topic, Answer, Question, Evidence in this workbook.

> **Notes:** {RENotes}

### Security
The [Security checklist](https://learn.microsoft.com/azure/well-architected/security/checklist) explains each question and what good looks like.

#### Assess se

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Id, Topic, Answer, Question, Evidence in this workbook.

> **Notes:** {SENotes}

### Cost Optimization
The [Cost Optimization checklist](https://learn.microsoft.com/azure/well-architected/cost-optimization/checklist) explains each question and what good looks like.

#### Assess co

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Id, Topic, Answer, Question, Evidence in this workbook.

> **Notes:** {CONotes}

### Operational Excellence
The [Operational Excellence checklist](https://learn.microsoft.com/azure/well-architected/operational-excellence/checklist) explains each question and what good looks like.

#### Assess oe

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Id, Topic, Answer, Question, Evidence in this workbook.

> **Notes:** {OENotes}

### Performance Efficiency
The [Performance Efficiency checklist](https://learn.microsoft.com/azure/well-architected/performance-efficiency/checklist) explains each question and what good looks like.

#### Assess pe

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Id, Topic, Answer, Question, Evidence in this workbook.

> **Notes:** {PENotes}

#### Gaps to act on (every No and Partly)

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Answer, Pillar, Id, Topic, Question, Evidence in this workbook.

When there is nothing to show: *Nothing answered No or Partly yet.*

## Tab: Overview

### What the configuration checks cover

| Pillar | Check | Severity | Resource types |
|---|---|---|---|
| Reliability | VM with no availability zone, availability set or scale set | Medium | `microsoft.compute/virtualmachines` |
| Reliability | Basic SKU public IP (retired September 2025) | High | `microsoft.network/publicipaddresses` |
| Reliability | Basic SKU load balancer (retired September 2025) | High | `microsoft.network/loadbalancers` |
| Reliability | Application Gateway v1 (retired April 2026) | High | `microsoft.network/applicationgateways` |
| Reliability | Application Gateway not spread across zones | Medium | `microsoft.network/applicationgateways` |
| Reliability | Azure Firewall not spread across zones | Medium | `microsoft.network/azurefirewalls` |
| Reliability | VPN or ExpressRoute gateway SKU is not zone-redundant | Medium | `microsoft.network/virtualnetworkgateways` |
| Reliability | Storage account is locally redundant (LRS) | Low | `microsoft.storage/storageaccounts` |
| Reliability | App Service plan runs a single instance | Medium | `microsoft.web/serverfarms` |
| Reliability | App Service plan not zone-redundant | Low | `microsoft.web/serverfarms` |
| Reliability | SQL database not zone-redundant | Low | `microsoft.sql/servers/databases` |
| Reliability | AKS node pools not spread across zones | Medium | `microsoft.containerservice/managedclusters` |
| Reliability | AKS cluster on the Free tier (no uptime SLA) | Medium | `microsoft.containerservice/managedclusters` |
| Reliability | Key Vault without purge protection | Medium | `microsoft.keyvault/vaults` |
| Reliability | Azure Cache for Redis on the Basic tier (one node, no SLA) | Medium | `microsoft.cache/redis` |
| Reliability | Cosmos DB account in one region with no zone redundancy | Medium | `microsoft.documentdb/databaseaccounts` |
| Reliability | Front Door (classic), retiring March 2027 | High | `microsoft.network/frontdoors` |
| Reliability | Azure CDN from Edgio (shut down January 2025) | High | `microsoft.cdn/profiles` |
| Reliability | Azure CDN Standard from Microsoft (classic), retiring September 2027 | Medium | `microsoft.cdn/profiles` |
| Reliability | API Management on the stv1 platform (retired August 2024) | High | `microsoft.apimanagement/service` |
| Reliability | API Management on the Developer tier (no SLA) | Medium | `microsoft.apimanagement/service` |
| Reliability | API Management not spread across zones | Medium | `microsoft.apimanagement/service` |
| Reliability | Azure Database for PostgreSQL single server (retired March 2025) | High | `microsoft.dbforpostgresql/servers` |
| Reliability | Azure Database for MySQL single server (retired September 2024) | High | `microsoft.dbformysql/servers` |
| Reliability | Azure Database for MariaDB (retired September 2025) | High | `microsoft.dbformariadb/servers` |
| Reliability | PostgreSQL or MySQL flexible server with no high availability | Medium | `microsoft.dbforpostgresql/flexibleservers`, `microsoft.dbformysql/flexibleservers` |
| Reliability | PostgreSQL or MySQL flexible server backups not geo-redundant | Low | `microsoft.dbforpostgresql/flexibleservers`, `microsoft.dbformysql/flexibleservers` |
| Reliability | Container Apps environment not zone-redundant | Medium | `microsoft.app/managedenvironments` |
| Reliability | Recovery Services vault stores backups locally redundant | Low | `microsoft.recoveryservices/vaults` |
| Reliability | Recovery Services vault with soft delete off | Medium | `microsoft.recoveryservices/vaults` |
| Security | Storage account allows anonymous blob access | High | `microsoft.storage/storageaccounts` |
| Security | Storage account accepts HTTP | High | `microsoft.storage/storageaccounts` |
| Security | Storage account accepts TLS older than 1.2 | Medium | `microsoft.storage/storageaccounts` |
| Security | Storage account open to all networks | Medium | `microsoft.storage/storageaccounts` |
| Security | Storage account allows shared key access | Low | `microsoft.storage/storageaccounts` |
| Security | Key Vault open to all networks | High | `microsoft.keyvault/vaults` |
| Security | Key Vault uses access policies, not Azure RBAC | Low | `microsoft.keyvault/vaults` |
| Security | SQL server public network access enabled | Medium | `microsoft.sql/servers` |
| Security | SQL server accepts TLS older than 1.2 | Medium | `microsoft.sql/servers` |
| Security | SQL server allows SQL authentication | Low | `microsoft.sql/servers` |
| Security | App accepts HTTP | High | `microsoft.web/sites` |
| Security | AKS API server open to the internet | High | `microsoft.containerservice/managedclusters` |
| Security | AKS local accounts enabled | Medium | `microsoft.containerservice/managedclusters` |
| Security | Container registry allows anonymous pull | High | `microsoft.containerregistry/registries` |
| Security | Container registry admin user enabled | Medium | `microsoft.containerregistry/registries` |
| Security | VM without Trusted Launch | Low | `microsoft.compute/virtualmachines` |
| Security | API Management accepts TLS 1.0 or 1.1 | Medium | `microsoft.apimanagement/service` |
| Security | Application Gateway with no web application firewall | Low | `microsoft.network/applicationgateways` |
| Security | Cosmos DB account open to all networks | Medium | `microsoft.documentdb/databaseaccounts` |
| Security | Azure AI services account open to all networks | Medium | `microsoft.cognitiveservices/accounts` |
| Security | PostgreSQL flexible server allows password authentication | Low | `microsoft.dbforpostgresql/flexibleservers` |
| Security | PostgreSQL or MySQL flexible server public network access enabled | Medium | `microsoft.dbforpostgresql/flexibleservers`, `microsoft.dbformysql/flexibleservers` |
| Security | WAF policy in Detection mode or turned off | Medium | `microsoft.network/applicationgatewaywebapplicationfirewallpolicies`, `microsoft.network/frontdoorwebapplicationfirewallpolicies` |
| Security | Messaging namespace accepts TLS older than 1.2 | Medium | `microsoft.servicebus/namespaces`, `microsoft.eventhub/namespaces` |
| Security | Key-based (local) authentication enabled | Low | `microsoft.servicebus/namespaces`, `microsoft.eventhub/namespaces`, `microsoft.documentdb/databaseaccounts`, `microsoft.cognitiveservices/accounts`, `microsoft.appconfiguration/configurationstores`, `microsoft.signalrservice/signalr`, `microsoft.eventgrid/topics`, `microsoft.eventgrid/domains` |
| Cost Optimization | Windows VM with no licence type (Azure Hybrid Benefit not used) | Low | `microsoft.compute/virtualmachines` |
| Cost Optimization | SQL Server VM paying for its SQL licence | Low | `microsoft.sqlvirtualmachine/sqlvirtualmachines` |
| Cost Optimization | Deallocated VM keeping Premium SSD disks | Low | `microsoft.compute/virtualmachines` |
| Cost Optimization | Workspace keeps data searchable for more than 90 days | Low | `microsoft.operationalinsights/workspaces` |
| Cost Optimization | Workspace on a legacy pricing tier | Low | `microsoft.operationalinsights/workspaces` |
| Cost Optimization | DDoS protection plan protecting no virtual networks | Medium | `microsoft.network/ddosprotectionplans` |
| Cost Optimization | Stopped PostgreSQL or MySQL flexible server | Low | `microsoft.dbforpostgresql/flexibleservers`, `microsoft.dbformysql/flexibleservers` |
| Cost Optimization | Unattached disk | Medium | `microsoft.compute/disks` |
| Cost Optimization | Unused public IP | Medium | `microsoft.network/publicipaddresses` |
| Cost Optimization | VM stopped but not deallocated | Medium | `microsoft.compute/virtualmachines` |
| Cost Optimization | App Service plan with no apps | Medium | `microsoft.web/serverfarms` |
| Cost Optimization | Load balancer with no backend pools | Medium | `microsoft.network/loadbalancers` |
| Cost Optimization | NAT gateway on no subnet | Medium | `microsoft.network/natgateways` |
| Cost Optimization | Snapshot older than 90 days | Medium | `microsoft.compute/snapshots` |
| Operational Excellence | Periodic patch assessment off | Low | `microsoft.compute/virtualmachines` |
| Operational Excellence | AKS cluster with no Container insights or managed Prometheus | Medium | `microsoft.containerservice/managedclusters` |
| Operational Excellence | AKS automatic upgrades off | Low | `microsoft.containerservice/managedclusters` |
| Operational Excellence | Classic Application Insights (retired February 2024) | Medium | `microsoft.insights/components` |
| Operational Excellence | Action group disabled | Medium | `microsoft.insights/actiongroups` |
| Operational Excellence | Container Apps environment sends its logs nowhere | Low | `microsoft.app/managedenvironments` |
| Operational Excellence | Private endpoint connection not approved | Medium | `microsoft.network/privateendpoints` |
| Operational Excellence | Alert rule disabled | Low | `microsoft.insights/metricalerts`, `microsoft.insights/scheduledqueryrules`, `microsoft.insights/activitylogalerts` |
| Performance Efficiency | Older-generation VM size | Low | `microsoft.compute/virtualmachines` |
| Performance Efficiency | Disk on Standard HDD | Low | `microsoft.compute/disks` |
| Performance Efficiency | Accelerated networking off | Low | `microsoft.network/networkinterfaces` |
| Performance Efficiency | Legacy storage account kind (general-purpose v1 or BlobStorage) | Low | `microsoft.storage/storageaccounts` |
| Performance Efficiency | App Service plan on Premium v2 or older | Low | `microsoft.web/serverfarms` |
| Performance Efficiency | AKS cluster with no autoscaling node pool | Low | `microsoft.containerservice/managedclusters` |
| Performance Efficiency | AKS node pool on managed rather than ephemeral OS disks | Low | `microsoft.containerservice/managedclusters` |
| Performance Efficiency | PostgreSQL or MySQL flexible server on the Burstable tier | Low | `microsoft.dbforpostgresql/flexibleservers`, `microsoft.dbformysql/flexibleservers` |

The idle-resource checks under Cost Optimization are the same ones the **Cloud Center of Excellence** workbook counts.
