# FinOps hubs

*Reference for [finops-hubs.workbook.json](../workbook/finops-hubs.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

Are the FinOps hubs healthy and up to date, are the Cost Management exports landing, are the Data Factory pipelines and triggers running, and is Azure Data Explorer ingesting and holding current data? Built for FinOps toolkit **v15**; works with earlier hubs.

It has 66 panels across 6 tabs. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| FinOps hubs | Hubs are found by the cm-resource-parent tag the hub template puts on every resource. |
| Time range | Applies to metrics, pipeline runs, changes and log panels. |
| Log Analytics workspace | Optional. The workspace the hub resources' diagnostic settings send to. Enables the Logs tab and the data checks on the Data Explorer tab. |
| Latest version | The current FinOps toolkit release. Hubs whose ftk-version tag is lower are flagged. |
| Data factories | The hubs' data factories. |
| Data Explorer clusters | The hubs' Data Explorer clusters. |
| Storage accounts | The hubs' data lake storage accounts (the deployment script account is left out). |
| Key vaults | Remote hubs only: the vault holding the remote hub's key. |
| Data factory | Triggers, runs and managed private endpoints are read from Azure Resource Manager for one factory at a time. |
| Data Explorer cluster | Configuration, databases and data checks are for one cluster at a time. |
| Export scope | The Cost Management scope the exports are defined at, for example /providers/Microsoft.Billing/billingAccounts/1234567 or /subscriptions/<id>. |

## Tab: Overview

#### Tile hubs

*Tiles · Azure Resource Graph*

#### Tile health

*Tiles · Azure Resource Graph* · reads `healthresources`

#### Tile clusters

*Tiles · Azure Resource Graph*

#### Tile leftovers

*Tiles · Azure Resource Graph*

#### Tile alerts

*Tiles · Azure Resource Graph*

#### Tile service health

*Tiles · Azure Resource Graph* · reads `servicehealthresources`

#### Tile advisor

*Tiles · Azure Resource Graph* · reads `advisorresources`

> A hub is every resource tagged `cm-resource-parent` = `.../providers/Microsoft.Cloud/hubs/<name>`, which the hub
> template adds to all it deploys. *Older than* compares the `ftk-version` tag with the **Latest version** parameter
> (v15 is `15.0`). v15 makes queries faster, stops redeploys resetting data retention and fixes commitment purchases
> inflating savings, so upgrade hubs that are behind. A **Dev (No SLA)** Data Explorer SKU is fine for a trial, not
> for reports people rely on.

#### FinOps hubs

*Table · Azure Resource Graph* · reads `healthresources`

Columns: Name, Health, Version, Version check, Data store, Network, Remote hub, Resources, Unhealthy, Leftover scripts, Resource group.

When there is nothing to show: *No FinOps hubs found. A hub's resources carry the tag cm-resource-parent = .../providers/Microsoft.Cloud/hubs/<name>; check the subscriptions selected.*

#### Data Factory runs per factory (time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.datafactory/factories`: Pipelines succeeded (sum); Pipelines failed (sum); Activities failed (sum); Triggers succeeded (sum); Triggers failed (sum).

#### Data Explorer per cluster (time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.kusto/clusters`: Keep alive (average); CPU % (average); Ingestion utilisation % (average); Cache utilisation % (average); Ingestion latency (s) (average).

#### Hub resources

*Table · Azure Resource Graph* · reads `healthresources`

Columns: Hub, Resource, Role, Health, Reason, Provisioning, Version, Location.

When there is nothing to show: *No hub resources.*

#### Service Health events for Data Factory, Data Explorer, Storage, Key Vault and Cost Management (active, or updated in the last 30 days)

*Table · Azure Resource Graph* · reads `servicehealthresources`

When there is nothing to show: *No Service Health events for the services a hub uses.*

#### Advisor recommendations for hub resources

*Table · Azure Resource Graph* · reads `advisorresources`

Columns: Impact, Category, Problem, Solution, Resource, Updated.

When there is nothing to show: *No Advisor recommendations for hub resources.*

#### Resource Health changes (time range, up to 14 days)

*Table · Azure Resource Graph* · reads `healthresourcechanges`

Columns: Time, Resource, Previous, Health.

When there is nothing to show: *No Resource Health changes in the time range.*

#### Changes to hub resources (time range, up to 14 days)

*Table · Azure Resource Graph* · reads `resourcechanges`

Columns: Time, Resource, Change, Properties, Changed by, Client, Operation.

When there is nothing to show: *No changes in the time range.*

## Tab: Data Factory

> How a hub moves data: Cost Management writes an export into **msexports** → trigger `msexports_ManifestAdded` runs **msexports_ExecuteETL** (→ msexports_ETL_ingestion), which writes parquet into **ingestion** → trigger `ingestion_ManifestAdded` runs **ingestion_ExecuteETL** (→ ingestion_ETL_dataExplorer), which ingests into Data Explorer. The **config_** pipelines manage exports (`config_DailySchedule`, `config_MonthlySchedule`, `config_SettingsUpdated`) and backfill. Every trigger below should be **Started**.

#### Triggers

*Table · Azure Resource Manager*: `GET {Factory}/triggers`

Columns: Trigger, State, Type, Pipeline, Blob path begins with, Frequency.

When there is nothing to show: *No triggers: the hub deployment did not finish.*

#### Managed private endpoints

*Table · Azure Resource Manager*: `GET {Factory}/managedVirtualNetworks/default/managedPrivateEndpoints`

Columns: Endpoint, Connection, Target, Sub-resource, Provisioning.

When there is nothing to show: *No managed private endpoints (a hub with public access has none).*

#### Pipeline runs

*Chart · Azure Monitor metrics* of `microsoft.datafactory/factories`: PipelineSucceededRuns (sum); PipelineFailedRuns (sum); PipelineCancelledRuns (sum).

#### Failed pipeline runs by pipeline

*Chart · Azure Monitor metrics* of `microsoft.datafactory/factories`: PipelineFailedRuns (sum, split by Name).

#### Failed activity runs by pipeline

*Chart · Azure Monitor metrics* of `microsoft.datafactory/factories`: ActivityFailedRuns (sum, split by PipelineName).

#### Failed trigger runs by trigger

*Chart · Azure Monitor metrics* of `microsoft.datafactory/factories`: TriggerFailedRuns (sum, split by Name).

#### Pipeline runs (time range, newest 100). Select a run to see its activities

*Table · Azure Resource Manager*: `POST {Factory}/queryPipelineRuns`

Columns: Pipeline, Status, Start, End, Duration (ms), Invoked by, Message, Run id.

When there is nothing to show: *No pipeline runs in the time range.*

#### Activity runs for the selected pipeline run

*Table · Azure Resource Manager*: `POST {Factory}/pipelineruns/{RunId}/queryActivityruns`

Columns: Activity, Type, Status, Start, End, Duration (ms), Error code, Error.

When there is nothing to show: *No activity runs for this pipeline run.*

#### Trigger runs (time range, newest 100)

*Table · Azure Resource Manager*: `POST {Factory}/queryTriggerRuns`

Columns: Trigger, Status, Type, Time, Message.

When there is nothing to show: *No trigger runs in the time range.*

#### Diagnostic settings

*Table · Azure Resource Manager*: `GET {Factory}/providers/Microsoft.Insights/diagnosticSettings`

Columns: Setting, Workspace, Mode, Logs.

When there is nothing to show: *No diagnostic settings: pipeline run history is only kept 45 days in Data Factory, and the Logs tab has nothing to read.*

## Tab: Data Explorer

> No Data Explorer cluster in the selected hubs. A hub that stores data in **Microsoft Fabric** (Real-Time Intelligence eventhouse) or in storage only has none; monitor a Fabric eventhouse from the Fabric capacity metrics app.

#### Cluster

*Table · Azure Resource Graph*

Columns: State, Provisioning, Sku, Tier, Instances, Auto-stop, Optimized autoscale, Public network, Streaming ingest, Zones, Uri, Version.

> **Tier Basic** is the *Dev (No SLA)* SKU: a single node with no SLA. **Auto-stop** stops a cluster nobody queries for 5 days, and a stopped cluster cannot ingest, so turn it off for a hub. The hub keeps `*_raw` tables for 0 days and `*_final_v*` tables for 13 months by default; v15 no longer resets your retention when you redeploy.

#### Databases

*Table · Azure Resource Manager*: `GET {Cluster}/databases`

Columns: Database, Kind, Hot cache, Retention (soft delete), Size (bytes), Provisioning.

When there is nothing to show: *No databases: the hub deployment did not finish.*

#### Keep alive (1 = responding)

*Chart · Azure Monitor metrics* of `microsoft.kusto/clusters`: KeepAlive (average).

#### CPU and cache utilisation %

*Chart · Azure Monitor metrics* of `microsoft.kusto/clusters`: CPU (average); CacheUtilization (average).

#### Ingestion result

*Chart · Azure Monitor metrics* of `microsoft.kusto/clusters`: IngestionResult (sum, split by IngestionResultDetails).

#### Ingestion latency (s) and utilisation %

*Chart · Azure Monitor metrics* of `microsoft.kusto/clusters`: IngestionLatencyInSeconds (average); IngestionUtilization (average).

#### Ingestion volume (MB) by database

*Chart · Azure Monitor metrics* of `microsoft.kusto/clusters`: IngestionVolumeInMB (sum, split by Database).

#### Query duration by status, throttled queries

*Chart · Azure Monitor metrics* of `microsoft.kusto/clusters`: QueryDuration (average, split by QueryStatus); TotalNumberOfThrottledQueries (max).

### Data in the hub

> Select a **Log Analytics workspace** at the top to check the data itself: these panels read the cluster's **Hub** and **Ingestion** databases through a cross-service `adx()` query. You need at least *Viewer* on those databases, and the portal must be able to reach the cluster.

#### Adx fresh costs

*Tiles · Log Analytics*

When there is nothing to show: *Could not read Costs()*

#### Adx fresh prices

*Tiles · Log Analytics*

When there is nothing to show: *Could not read Prices()*

#### Adx fresh commitmentdiscountusage

*Tiles · Log Analytics*

When there is nothing to show: *Could not read CommitmentDiscountUsage()*

#### Adx fresh recommendations

*Tiles · Log Analytics*

When there is nothing to show: *Could not read Recommendations()*

#### Adx fresh transactions

*Tiles · Log Analytics*

When there is nothing to show: *Could not read Transactions()*

> Rows in each Hub database function (latest FOCUS schema). **Costs** and **CommitmentDiscountUsage** turn amber when the latest charge is more than 3 days old; any dataset is red when empty. A tile showing an error means the function is missing (an older hub) or the cluster cannot be reached.

#### Cost per month (Costs(), last 13 months): a gap is a month that was not exported or not ingested

*Bar chart · Log Analytics*

When there is nothing to show: *No cost data in the Hub database.*

#### Rows per month

*Table · Log Analytics*

When there is nothing to show: *No cost data.*

#### Hub settings (Ingestion database, HubSettings())

*Table · Log Analytics*

When there is nothing to show: *No hub settings recorded.*

#### Scopes the hub exports (HubScopes())

*Table · Log Analytics*

When there is nothing to show: *No scopes recorded: the hub has no managed exports, or exports are configured by hand.*

#### Diagnostic settings

*Table · Azure Resource Manager*: `GET {Cluster}/providers/Microsoft.Insights/diagnosticSettings`

Columns: Setting, Workspace, Mode.

When there is nothing to show: *No diagnostic settings: failed ingestions are not logged anywhere.*

## Tab: Storage & exports

#### Hub storage accounts

*Table · Azure Resource Graph*

Columns: id, Purpose, Sku, Hierarchical namespace, Public network, Firewall default, Shared key, Min TLS, Provisioning, Hub.

When there is nothing to show: *No hub storage accounts.*

#### Data lake storage accounts (time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.storage/storageaccounts`: Availability % (average); Transactions (sum); E2E latency (ms) (average); Used capacity (average).

#### Transactions by response type

*Chart · Azure Monitor metrics* of `microsoft.storage/storageaccounts`: Transactions (sum, split by ResponseType).

#### Used capacity

*Chart · Azure Monitor metrics* of `microsoft.storage/storageaccounts`: UsedCapacity (average).

### Cost Management exports
A hub only gets data when an export writes into its **msexports** container (FOCUS cost, price sheet, reservation details, recommendations and transactions). Managed exports (hub v0.x settings) are created by `config_ConfigureExports`; otherwise they are created by hand. Enter the scope the exports are defined at to check their last run.

#### Cost Management exports at this scope (check the destination is a hub's storage account and container msexports)

*Table · Azure Resource Manager*: `GET {ExportScope}/providers/Microsoft.CostManagement/exports`

Columns: Export, Dataset, Version, Schedule, Recurrence, Last run status, Last run, Error, Next run (estimate), Container, Destination.

When there is nothing to show: *No exports at this scope, or you need Cost Management Reader on it.*

## Tab: Network & security

> v15 adds **VNet** and **private network** modes with an opt-in **NAT gateway**. In private mode the storage account, Key Vault and Data Explorer cluster are reached through private endpoints, and Data Factory through managed private endpoints (on the Data Factory tab), all of which must be **Approved**. Deployment scripts run in container instances in their own subnet, and need outbound access (the NAT gateway) to finish.

#### Networking resources

*Table · Azure Resource Graph*

Columns: id, Type, Hub, Address space, Subnets, IP address, Provisioning.

When there is nothing to show: *No networking resources: the hubs use public access.*

#### Subnets

*Table · Azure Resource Graph*

Columns: Subnet, Prefix, Delegation, NAT gateway, NSG, IP configurations, Virtual network, Hub.

When there is nothing to show: *No hub virtual networks.*

#### Private endpoints to hub resources

*Table · Azure Resource Graph*

Columns: Private endpoint, Target, Sub-resource, Connection, Provisioning, Hub.

When there is nothing to show: *No private endpoints point at hub resources.*

#### Managed identities

*Table · Azure Resource Graph*

Columns: id, Kind, Principal id, Hub.

When there is nothing to show: *No identities.*

#### Metric alert rules on factories and clusters

*Table · Azure Resource Graph*

Columns: id, Type, Rules, No alert on, Covered.

When there is nothing to show: *No factories or clusters.*

> Suggested alerts: Data Factory `PipelineFailedRuns` and `TriggerFailedRuns` (total > 0), Data Explorer `IngestionResult` split by result (failures > 0) and `KeepAlive` (< 1). A log alert on `ADFPipelineRun` or `FailedIngestion` works too, but is not counted here.

#### Key Vault availability and API results (remote hubs)

*Chart · Azure Monitor metrics* of `microsoft.keyvault/vaults`: Availability (average); ServiceApiResult (sum, split by StatusCode).

## Tab: Logs

> Select a **Log Analytics workspace** at the top. Send the data factories' *Pipeline runs*, *Activity runs* and *Trigger runs*, the clusters' *Succeeded/Failed ingestion* and *Command*, and the storage accounts' blob *StorageWrite* logs to it. Resource-specific mode is best; AzureDiagnostics works for Data Factory.

#### Hub resources by last record in the workspace

*Table · Log Analytics*

Columns: Resource, Type, Status, Records, Last record, Tables.

When there is nothing to show: *No hub resources.*

### Data Factory

#### Pipeline runs by status

*Time chart · Log Analytics* · reads `ADFPipelineRun`, `AzureDiagnostics`

When there is nothing to show: *No pipeline runs logged in the time range.*

#### Trigger runs

*Table · Log Analytics* · reads `ADFTriggerRun`, `AzureDiagnostics`

Columns: Trigger, Type, Last status, Last run, Runs, Failed.

When there is nothing to show: *No trigger runs logged in the time range.*

#### Pipelines: last status, last success and failures

*Table · Log Analytics* · reads `ADFPipelineRun`, `AzureDiagnostics`

Columns: Factory, Stage, Pipeline, Last status, Last run, Last success, Runs, Failed, Avg minutes (succeeded), Failure type.

When there is nothing to show: *No pipeline runs logged in the time range.*

#### Failed activities by error

*Table · Log Analytics* · reads `ADFActivityRun`, `AzureDiagnostics`

When there is nothing to show: *No failed activities in the time range.*

### Data Explorer

#### Ingestions by result

*Time chart · Log Analytics* · reads `SucceededIngestion`, `FailedIngestion`

When there is nothing to show: *No ingestion logged in the time range.*

#### Last successful ingestion per table

*Table · Log Analytics* · reads `SucceededIngestion`

When there is nothing to show: *No successful ingestion logged in the time range.*

#### Failed ingestions

*Table · Log Analytics* · reads `FailedIngestion`

When there is nothing to show: *No failed ingestions in the time range.*

#### Commands that did not complete

*Table · Log Analytics* · reads `ADXCommand`

When there is nothing to show: *No failed commands in the time range.*

### Storage

#### Files written per container

*Table · Log Analytics* · reads `StorageBlobLogs`

When there is nothing to show: *No writes to msexports, ingestion or config logged in the time range.*

#### Storage errors (excluding 404 and 409)

*Table · Log Analytics* · reads `StorageBlobLogs`

When there is nothing to show: *No storage errors in the time range.*

### Azure operations

#### Operations in the hubs' resource groups (activity log)

*Table · Log Analytics* · reads `AzureActivity`

When there is nothing to show: *No operations in the time range (or the activity log is not sent to this workspace).*
