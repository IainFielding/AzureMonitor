# Well-Architected Framework

*Reference for [well-architected.workbook.json](../workbook/well-architected.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

A workload's gaps against the five pillars of the Azure Well-Architected Framework: Reliability, Security, Cost Optimization, Operational Excellence and Performance Efficiency. Each pillar combines Azure Advisor's recommendations with configuration checks read from Azure Resource Graph, so no workspace is needed.

It has 47 panels across 6 tabs. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Workload tag | The tag whose value names the workload a resource belongs to. Tag names here match case. |
| Workload | The workloads to review, from the values of the workload tag. All includes untagged resources. |

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

> **How to use this.** Pick the workload at the top (the **Workload tag** names the tag that identifies one), then
> work through the pillar tabs. Each pillar tile counts the configuration checks that fail plus Azure Advisor's
> recommendations for that pillar; red means at least one is high severity. *Advisor score* is Microsoft's own
> 0-100 score per pillar, averaged across the selected subscriptions; it is not narrowed to the workload. The checks
> here are the settings a reviewer would otherwise open each resource to find; they do not replace the
> [Azure Well-Architected Review](https://learn.microsoft.com/assessments/azure-architecture-review/), which asks
> about design, process and recovery testing that no setting shows.

#### Azure Advisor recommendations by pillar and impact

*Bar chart · Azure Resource Graph* · reads `advisorresources`

When there is nothing to show: *Advisor has no recommendations for the workload.*

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

> Diagnostic settings are not in Resource Graph, so resources that send no logs are not checked here: the **Platform health** *Monitoring* tab lists them.

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
| Security | Key-based (local) authentication enabled | Low | `microsoft.servicebus/namespaces`, `microsoft.eventhub/namespaces`, `microsoft.documentdb/databaseaccounts`, `microsoft.cognitiveservices/accounts`, `microsoft.appconfiguration/configurationstores`, `microsoft.signalrservice/signalr` |
| Cost Optimization | Windows VM with no licence type (Azure Hybrid Benefit not used) | Low | `microsoft.compute/virtualmachines` |
| Cost Optimization | SQL Server VM paying for its SQL licence | Low | `microsoft.sqlvirtualmachine/sqlvirtualmachines` |
| Cost Optimization | Deallocated VM keeping Premium SSD disks | Low | `microsoft.compute/virtualmachines` |
| Cost Optimization | Workspace keeps data searchable for more than 90 days | Low | `microsoft.operationalinsights/workspaces` |
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
| Operational Excellence | Alert rule disabled | Low | `microsoft.insights/metricalerts`, `microsoft.insights/scheduledqueryrules`, `microsoft.insights/activitylogalerts` |
| Performance Efficiency | Older-generation VM size | Low | `microsoft.compute/virtualmachines` |
| Performance Efficiency | Disk on Standard HDD | Low | `microsoft.compute/disks` |
| Performance Efficiency | Accelerated networking off | Low | `microsoft.network/networkinterfaces` |
| Performance Efficiency | Legacy storage account kind (general-purpose v1 or BlobStorage) | Low | `microsoft.storage/storageaccounts` |
| Performance Efficiency | App Service plan on Premium v2 or older | Low | `microsoft.web/serverfarms` |
| Performance Efficiency | AKS cluster with no autoscaling node pool | Low | `microsoft.containerservice/managedclusters` |

The idle-resource checks under Cost Optimization are the same ones the **Cloud Center of Excellence** workbook counts.
