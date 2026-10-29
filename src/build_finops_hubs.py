"""Generates the FinOps hubs workbook (FinOps toolkit v15).

Run:  python src/build_finops_hubs.py
Out:  workbook/finops-hubs.workbook.json

Are the FinOps hubs healthy and up to date, are the Cost Management exports landing, are the Data Factory
pipelines and triggers running, and is Azure Data Explorer ingesting and holding current data? Hubs are found by
the tags the hub template puts on every resource it deploys: `cm-resource-parent` (the hub's id,
.../providers/Microsoft.Cloud/hubs/<name>), `ftk-tool` ("FinOps hubs") and `ftk-version` (for example "15.0").

Inventory, health, versions, networking and alert coverage come from Resource Graph; pipeline, trigger, storage,
Key Vault and Data Explorer numbers from platform metrics; triggers, pipeline runs, activity runs, managed private
endpoints, databases and exports from Azure Resource Manager; diagnostic logs and the data in the Hub database (read
with a cross-service adx() query) from Log Analytics when a workspace is selected. Built from the helpers in
build_workbook.py so the workbooks look alike.
"""

import pathlib

from build_workbook import (AVG, DAY_MS, MAX, ONE_TILE, PROVISIONING, SUM, WORKSPACE_UNSET, arg, arm,
                            big_number_tiles, export_row, free_text_param, gid, group, health_fmt, hidden, hidden_arg_param,
                            la, low_is_good, m, metric_grid, metrics, notebook, params, resource_link, resource_param, status_fmt,
                            subscription_param, text, time_param, when_set, workspace_param, write_workbook)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "finops-hubs.workbook.json"

P = "ftkh"
HOUR_MS = 3600000
ADF = "microsoft.datafactory/factories"
ADX = "microsoft.kusto/clusters"
STG = "microsoft.storage/storageaccounts"
KV = "microsoft.keyvault/vaults"
ADF_API = "2018-06-01"
ADX_API = "2023-08-15"
LATEST = "15.0"

TABS = [
    ("overview", "Overview"),
    ("pipelines", "Data Factory"),
    ("adx", "Data Explorer"),
    ("storage", "Storage & exports"),
    ("network", "Network & security"),
    ("logs", "Logs"),
]

# The pipelines' triggers in a hub. A trigger left Stopped (a redeploy that failed between its stop and start
# scripts is the usual cause) means exports land in storage and are never processed.
EXPECTED_TRIGGERS = ["config_SettingsUpdated", "config_DailySchedule", "config_MonthlySchedule",
                     "msexports_ManifestAdded", "ingestion_ManifestAdded"]

# ---------------------------------------------------------------------------
# Shared Resource Graph fragments
# ---------------------------------------------------------------------------

# Every resource that belongs to one of the selected hubs.
HUB_RES = """
resources
| extend Hub = tolower(tostring(tags['cm-resource-parent']))
| where Hub in~ ({Hub})"""

HUB_PARAM_Q = """
resources
| extend Hub = tolower(tostring(tags['cm-resource-parent']))
| where Hub has '/providers/microsoft.cloud/hubs/' or tostring(tags['ftk-tool']) =~ 'FinOps hubs'
| where isnotempty(Hub)
| summarize by Hub
| extend parts = split(Hub, '/')
| project value = Hub, label = strcat(tostring(parts[8]), '  (', tostring(parts[4]), ')')
| order by label asc"""

# Each hub resource with its Resource Health state; provisioning state stands in where Resource Health has none.
HEALTH = HUB_RES + """
| project id = tolower(id), Hub, name, type, Provisioning = tostring(properties.provisioningState),
    Version = tostring(tags['ftk-version']), ResourceGroup = resourceGroup, Location = location
| join kind=leftouter (
    healthresources
    | where type =~ 'microsoft.resourcehealth/availabilitystatuses'
    | project id = tostring(split(tolower(id), '/providers/microsoft.resourcehealth/')[0]),
        RhHealth = tostring(properties.availabilityState), Reason = tostring(properties.summary)
  ) on id
| project-away id1
| extend Health = case(isnotempty(RhHealth), RhHealth, Provisioning =~ 'Failed', 'Unavailable',
        Provisioning =~ 'Succeeded' or isempty(Provisioning), 'Available', 'Degraded'),
    Reason = iff(isempty(RhHealth), iff(isempty(Provisioning), '', strcat('Provisioning: ', Provisioning)), Reason)
| project-away RhHealth"""

# A short role for each resource type a hub deploys.
ROLE = """
| extend Role = case(
    type =~ 'microsoft.storage/storageaccounts' and name contains 'script', 'Deployment script storage',
    type =~ 'microsoft.storage/storageaccounts', 'Data lake (msexports, ingestion, config)',
    type =~ 'microsoft.datafactory/factories', 'Data Factory (pipelines)',
    type =~ 'microsoft.kusto/clusters', 'Data Explorer cluster',
    type =~ 'microsoft.kusto/clusters/databases', 'Data Explorer database',
    type =~ 'microsoft.keyvault/vaults', 'Key Vault (remote hub)',
    type =~ 'microsoft.managedidentity/userassignedidentities', 'Managed identity',
    type =~ 'microsoft.network/virtualnetworks', 'Virtual network',
    type =~ 'microsoft.network/privateendpoints', 'Private endpoint',
    type =~ 'microsoft.network/privatednszones', 'Private DNS zone',
    type =~ 'microsoft.network/natgateways', 'NAT gateway',
    type =~ 'microsoft.network/publicipaddresses', 'Public IP (NAT)',
    type =~ 'microsoft.network/networksecuritygroups', 'Network security group',
    type =~ 'microsoft.resources/deploymentscripts', 'Deployment script (should be deleted)',
    type =~ 'microsoft.containerinstance/containergroups', 'Deployment script container (should be deleted)',
    type)"""

# One row per hub: its version, what it deployed, and how many of its resources are unhealthy.
HUBS_Q = HEALTH + """
| summarize VersionNumber = max(todouble(Version)),
    Resources = count(), Unhealthy = countif(Health !~ 'Available'),
    Storage = countif(type =~ 'microsoft.storage/storageaccounts' and name !contains 'script'),
    Factories = countif(type =~ 'microsoft.datafactory/factories'),
    Clusters = countif(type =~ 'microsoft.kusto/clusters'),
    Vaults = countif(type =~ 'microsoft.keyvault/vaults'),
    Networks = countif(type =~ 'microsoft.network/virtualnetworks'),
    Nat = countif(type =~ 'microsoft.network/natgateways'),
    Leftovers = countif(type in~ ('microsoft.resources/deploymentscripts', 'microsoft.containerinstance/containergroups'))
    by Hub
| extend parts = split(Hub, '/')
| extend Name = tostring(parts[8]), ResourceGroup = tostring(parts[4]),
    DataStore = iff(Clusters > 0, 'Azure Data Explorer', 'Storage only or Fabric'),
    Network = case(Networks > 0 and Nat > 0, 'Private (NAT gateway)', Networks > 0, 'Private', 'Public'),
    RemoteHub = iff(Vaults > 0, 'Yes', 'No'),
    Health = case(Unhealthy > 0, 'Degraded', 'Available')
| extend Version = tostring(VersionNumber),
    UpToDate = case(isnull(VersionNumber), 'Unknown', VersionNumber < todouble('{LatestVersion}'), 'Behind', 'Current')
| project Name, Health, Version, UpToDate, DataStore, Network, RemoteHub, Resources, Unhealthy, Leftovers,
    ResourceGroup, Hub
| order by case(Health =~ 'Available', 1, 0) asc, Name asc
"""

INVENTORY_Q = HEALTH + ROLE + """
| extend HubName = tostring(split(Hub, '/')[8])
| project HubName, id, Role, Health, Reason, Provisioning, Version, Location
| order by HubName asc, case(Health =~ 'Unavailable', 0, Health =~ 'Available', 2, 1) asc, Role asc
"""

SERVICE_HEALTH = """
servicehealthresources
| where type =~ 'microsoft.resourcehealth/events'
| where tostring(properties.Impact) has_any ('Data Factory', 'Data Explorer', 'Storage', 'Key Vault', 'Cost Management')"""

ADVISOR = """
advisorresources
| where type =~ 'microsoft.advisor/recommendations'
| where tolower(resourceGroup) in~ ({HubResourceGroups})
| extend rid = tolower(tostring(properties.resourceMetadata.resourceId))"""

# Metric alert rules that watch the factories and clusters, counted by whether they watch failures. A rule scoped
# to the resource group or subscription counts when its target type is the resource's type.
ALERT_COVERAGE = HUB_RES + """
| where type in~ ('microsoft.datafactory/factories', 'microsoft.kusto/clusters')
| extend rid = tolower(id), rtype = tolower(type), sub = tolower(strcat('/subscriptions/', subscriptionId))
| extend scopeKey = pack_array(rid, strcat(sub, '/resourcegroups/', tolower(resourceGroup)), sub)
| mv-expand scopeKey
| extend scopeKey = tostring(scopeKey)
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.insights/metricalerts'
    | where tobool(properties.enabled)
    | extend target = tolower(tostring(properties.targetResourceType))
    | mv-expand scope = properties.scopes
    | mv-expand crit = properties.criteria.allOf
    | project scopeKey = tolower(tostring(scope)), target, metric = tolower(tostring(crit.metricName)), rule = tolower(id)
  ) on scopeKey
| extend applies = isnotempty(rule) and (scopeKey == rid or target == rtype)
| summarize Rules = dcountif(rule, applies),
    PipelineFailures = countif(applies and metric in ('pipelinefailedruns', 'activityfailedruns')),
    TriggerFailures = countif(applies and metric == 'triggerfailedruns'),
    Ingestion = countif(applies and metric in ('ingestionresult', 'ingestionlatencyinseconds', 'ingestionutilization')),
    KeepAlive = countif(applies and metric == 'keepalive')
    by id = rid, Type = rtype
| extend Missing = iff(Type == 'microsoft.datafactory/factories',
        trim(@'[, ]+', strcat(iff(PipelineFailures == 0, 'failed pipeline runs, ', ''),
            iff(TriggerFailures == 0, 'failed trigger runs', ''))),
        trim(@'[, ]+', strcat(iff(Ingestion == 0, 'ingestion, ', ''), iff(KeepAlive == 0, 'keep alive', ''))))"""

# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

TILES = [
    ("hubs", HUB_RES + """
| summarize Version = max(todouble(tostring(tags['ftk-version']))) by Hub
| summarize Total = count(), Behind = countif(isnull(Version) or Version < todouble('{LatestVersion}'))
| project Signal = 'FinOps hubs', Value = Total, Detail = strcat(Behind, ' older than v{LatestVersion}'),
    State = case(Total == 0, 'Unknown', Behind > 0, 'Degraded', 'Available')
"""),
    ("health", HEALTH + """
| summarize Total = count(), Unavailable = countif(Health =~ 'Unavailable'),
    Degraded = countif(Health !~ 'Available' and Health !~ 'Unavailable')
| project Signal = 'Unhealthy hub resources', Value = Unavailable + Degraded,
    Detail = strcat('of ', Total, ' resources'),
    State = case(Total == 0, 'Unknown', Unavailable > 0, 'Unavailable', Degraded > 0, 'Degraded', 'Available')
"""),
    ("clusters", HUB_RES + """
| where type =~ 'microsoft.kusto/clusters'
| extend State = tostring(properties.state)
| summarize Total = count(), NotRunning = countif(State !~ 'Running'),
    Dev = countif(tostring(sku.tier) =~ 'Basic')
| project Signal = 'Data Explorer clusters not running', Value = NotRunning,
    Detail = strcat('of ', Total, ' · ', Dev, ' on a Dev (no SLA) SKU'),
    State = case(Total == 0, 'Unknown', NotRunning > 0, 'Unavailable', 'Available')
"""),
    ("leftovers", HUB_RES + """
| where type in~ ('microsoft.resources/deploymentscripts', 'microsoft.containerinstance/containergroups')
| summarize Total = count(), Failed = countif(tostring(properties.provisioningState) =~ 'Failed')
| project Signal = 'Deployment scripts left behind', Value = Total,
    Detail = strcat(Failed, ' failed · scripts delete themselves when a deploy succeeds'),
    State = case(Failed > 0, 'Unavailable', Total > 0, 'Degraded', 'Available')
"""),
    ("alerts", ALERT_COVERAGE + """
| summarize Total = count(), Gaps = countif(isnotempty(Missing))
| project Signal = 'Factories and clusters missing failure alerts', Value = Gaps,
    Detail = strcat('of ', Total), State = case(Total == 0, 'Unknown', Gaps > 0, 'Degraded', 'Available')
"""),
    ("service-health", SERVICE_HEALTH + """
| where tostring(properties.Status) =~ 'Active'
| extend EventType = tostring(properties.EventType), TrackingId = tostring(properties.TrackingId)
| summarize Total = dcount(TrackingId), Issues = dcountif(TrackingId, EventType =~ 'ServiceIssue')
| project Signal = 'Active Service Health events', Value = Total,
    Detail = strcat(Issues, ' issues · Data Factory, ADX, Storage, Key Vault, Cost Mgmt'),
    State = case(Issues > 0, 'Unavailable', Total > 0, 'Degraded', 'Available')
"""),
    ("advisor", ADVISOR + """
| extend Impact = tostring(properties.impact)
| summarize Total = count(), High = countif(Impact =~ 'High')
| project Signal = 'Advisor recommendations', Value = Total, Detail = strcat(High, ' high impact'),
    State = iff(Total > 0, 'Degraded', 'Available')
"""),
]

TILE_NOTE = """\
A hub is every resource tagged `cm-resource-parent` = `.../providers/Microsoft.Cloud/hubs/<name>`, which the hub
template adds to all it deploys. *Older than* compares the `ftk-version` tag with the **Latest version** parameter
(v15 is `15.0`). v15 makes queries faster, stops redeploys resetting data retention and fixes commitment purchases
inflating savings, so upgrade hubs that are behind. A **Dev (No SLA)** Data Explorer SKU is fine for a trial, not
for reports people rely on."""

ADVISOR_Q = ADVISOR + """
| project Impact = tostring(properties.impact), Category = tostring(properties.category),
    Problem = tostring(properties.shortDescription.problem), Solution = tostring(properties.shortDescription.solution),
    Resource = rid, Updated = todatetime(properties.lastUpdated)
| order by case(Impact =~ 'High', 0, Impact =~ 'Medium', 1, 2) asc
"""

SERVICE_HEALTH_Q = SERVICE_HEALTH + """
| where tostring(properties.Status) =~ 'Active' or todatetime(properties.LastUpdateTime) >= ago(30d)
| summarize EventType = take_any(tostring(properties.EventType)), Status = take_any(tostring(properties.Status)),
    Title = take_any(tostring(properties.Title)), Start = min(todatetime(properties.ImpactStartTime)),
    LastUpdate = max(todatetime(properties.LastUpdateTime)), Subscriptions = dcount(subscriptionId)
    by TrackingId = tostring(properties.TrackingId)
| order by case(Status =~ 'Active', 0, 1) asc, LastUpdate desc
"""

CHANGES_Q = """
resourcechanges
| extend Time = todatetime(properties.changeAttributes.timestamp)
| where Time >= todatetime('{TimeRange:startISO}')
| extend Resource = tolower(tostring(properties.targetResourceId))
| where tostring(split(Resource, '/')[4]) in~ ({HubResourceGroups})
| project Time, Resource, ChangeType = tostring(properties.changeType),
    Properties = strcat_array(bag_keys(properties.changes), ', '),
    ChangedBy = tostring(properties.changeAttributes.changedBy),
    Client = tostring(properties.changeAttributes.clientType),
    Operation = tostring(properties.changeAttributes.operation)
| order by Time desc
| take 200
"""

HEALTH_HISTORY_Q = """
healthresourcechanges
| where tostring(properties.targetResourceType) =~ 'microsoft.resourcehealth/availabilitystatuses'
| extend Time = todatetime(properties.changeAttributes.timestamp)
| where Time >= todatetime('{TimeRange:startISO}')
| extend id = tostring(split(tolower(tostring(properties.targetResourceId)), '/providers/microsoft.resourcehealth/')[0])
| extend state = properties.changes['properties.availabilityState']
| where isnotempty(tostring(state.newValue))
| where tostring(split(id, '/')[4]) in~ ({HubResourceGroups})
| project Time, id, Previous = tostring(state.previousValue), Health = tostring(state.newValue)
| order by Time desc
| take 500
"""

# ---------------------------------------------------------------------------
# Data Explorer
# ---------------------------------------------------------------------------

CLUSTER_Q = """
resources
| where id =~ '{Cluster}'
| project State = tostring(properties.state), Provisioning = tostring(properties.provisioningState),
    Sku = tostring(sku.name), Tier = tostring(sku.tier), Instances = toint(sku.capacity),
    AutoStop = tostring(properties.enableAutoStop),
    OptimizedAutoscale = tostring(properties.optimizedAutoscale.isEnabled),
    PublicNetwork = tostring(properties.publicNetworkAccess),
    StreamingIngest = tostring(properties.enableStreamingIngest),
    Zones = strcat_array(zones, ', '), Uri = tostring(properties.uri), Version = tostring(tags['ftk-version'])
"""

# The Hub database's functions are the hub's public contract: one per FOCUS dataset, latest schema. Read through
# Log Analytics with a cross-service adx() query, so the viewer needs at least Viewer on the Hub database and the
# portal must be able to reach the cluster (not the case when public network access is off).
# (function, date column, filled by daily exports). Costs and commitment usage come from daily exports, so a latest
# charge more than 3 days old means exports or ingestion stopped.
DATASETS = [
    ("Costs", "ChargePeriodStart", True),
    ("Prices", "x_EffectivePeriodStart", False),
    ("CommitmentDiscountUsage", "ChargePeriodStart", True),
    ("Recommendations", "x_RecommendationDate", False),
    ("Transactions", "x_TransactionDate", False),
]


def freshness_q(fn, col, daily):
    """One query per dataset: a function an older hub does not have fails only its own tile (a missing function
    fails a whole union, isfuzzy or not)."""
    return f"""
adx('{{ClusterUri}}/Hub').{fn}()
| summarize Rows = count(), Latest = max(todatetime(column_ifexists('{col}', datetime(null))))
| extend Days = datetime_diff('day', now(), Latest)
| project Signal = '{fn}', Value = Rows,
    Detail = iff(isnull(Latest), 'rows', strcat('latest ', format_datetime(Latest, 'yyyy-MM-dd'))),
    State = case(Rows == 0, 'Unavailable', {'true' if daily else 'false'} and Days > 3, 'Degraded', 'Available')
"""

# A month with no cost (or far less than its neighbours) is an export that never ran or was never ingested.
MONTHLY_Q = """
adx('{ClusterUri}/Hub').Costs()
| where ChargePeriodStart >= startofmonth(ago(400d))
| summarize EffectiveCost = sum(todouble(EffectiveCost)), BilledCost = sum(todouble(BilledCost)), Rows = count()
    by Month = startofmonth(ChargePeriodStart)
| order by Month asc
"""

SETTINGS_Q = """
adx('{ClusterUri}/Ingestion').HubSettings()
| take 1
"""

SCOPES_Q = """
adx('{ClusterUri}/Ingestion').HubScopes()
| take 200
"""

# ---------------------------------------------------------------------------
# Storage and network
# ---------------------------------------------------------------------------

STORAGE_Q = HUB_RES + """
| where type =~ 'microsoft.storage/storageaccounts'
| project id, Purpose = iff(name contains 'script', 'Deployment scripts', 'Data lake'),
    Sku = tostring(sku.name), DataLake = tostring(properties.isHnsEnabled),
    PublicNetwork = tostring(properties.publicNetworkAccess),
    DefaultAction = tostring(properties.networkAcls.defaultAction),
    SharedKey = tostring(properties.allowSharedKeyAccess), MinTls = tostring(properties.minimumTlsVersion),
    Provisioning = tostring(properties.provisioningState), HubName = tostring(split(Hub, '/')[8])
| order by HubName asc, Purpose asc
"""

NETWORK_Q = HUB_RES + """
| where type in~ ('microsoft.network/virtualnetworks', 'microsoft.network/natgateways',
    'microsoft.network/publicipaddresses', 'microsoft.network/networksecuritygroups')
| project id, Type = tostring(split(type, '/')[1]), HubName = tostring(split(Hub, '/')[8]),
    AddressSpace = strcat_array(properties.addressSpace.addressPrefixes, ', '),
    SubnetCount = array_length(properties.subnets),
    IpAddress = tostring(properties.ipAddress), Provisioning = tostring(properties.provisioningState)
| order by HubName asc, Type asc
"""

SUBNETS_Q = HUB_RES + """
| where type =~ 'microsoft.network/virtualnetworks'
| mv-expand s = properties.subnets
| project Subnet = tostring(s.name), Prefix = tostring(s.properties.addressPrefix),
    Delegation = tostring(s.properties.delegations[0].properties.serviceName),
    NatGateway = tostring(split(tostring(s.properties.natGateway.id), '/')[8]),
    Nsg = tostring(split(tostring(s.properties.networkSecurityGroup.id), '/')[8]),
    UsedIps = array_length(s.properties.ipConfigurations), VirtualNetwork = name,
    HubName = tostring(split(Hub, '/')[8])
| order by HubName asc, Subnet asc
"""

# Private endpoints that point at a hub resource, wherever the endpoint lives.
PRIVATE_ENDPOINTS_Q = """
resources
| where type =~ 'microsoft.network/privateendpoints'
| mv-expand c = array_concat(properties.privateLinkServiceConnections, properties.manualPrivateLinkServiceConnections)
| extend Target = tolower(tostring(c.properties.privateLinkServiceId))
| join kind=inner (
    resources
    | extend Hub = tolower(tostring(tags['cm-resource-parent']))
    | where Hub in~ ({Hub})
    | project Target = tolower(id), HubName = tostring(split(Hub, '/')[8])
  ) on Target
| project id, Target, SubResource = strcat_array(c.properties.groupIds, ', '),
    Connection = tostring(c.properties.privateLinkServiceConnectionState.status),
    Provisioning = tostring(properties.provisioningState), HubName
| order by case(Connection =~ 'Approved', 1, 0) asc, HubName asc
"""

IDENTITIES_Q = HUB_RES + """
| where type in~ ('microsoft.managedidentity/userassignedidentities', 'microsoft.datafactory/factories',
    'microsoft.kusto/clusters')
| project id, Kind = iff(type =~ 'microsoft.managedidentity/userassignedidentities', 'User-assigned',
        tostring(identity.type)),
    PrincipalId = coalesce(tostring(properties.principalId), tostring(identity.principalId)),
    HubName = tostring(split(Hub, '/')[8])
| order by HubName asc
"""

COVERAGE_Q = ALERT_COVERAGE + """
| project id, Type = tostring(split(Type, '/')[1]), Rules, Missing,
    Covered = iff(isempty(Missing), 'Yes', 'No')
| order by Covered asc
"""

# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

# Data Factory writes either resource-specific tables (ADF*) or AzureDiagnostics, depending on the diagnostic
# setting's mode. Read both, loosely, and keep only the hubs' factories.
PIPELINE_RUNS = """
union isfuzzy=true (datatable(TimeGenerated: datetime)[]),
    (ADFPipelineRun
     | extend Pipeline = tostring(column_ifexists('PipelineName', '')), Status = tostring(column_ifexists('Status', '')),
         RunId = tostring(column_ifexists('RunId', '')), Failure = tostring(column_ifexists('FailureType', '')),
         Start = todatetime(column_ifexists('Start', datetime(null))), End = todatetime(column_ifexists('End', datetime(null)))),
    (AzureDiagnostics
     | where ResourceProvider =~ 'MICROSOFT.DATAFACTORY' and Category =~ 'PipelineRuns'
     | extend Pipeline = tostring(column_ifexists('pipelineName_s', '')), Status = tostring(column_ifexists('status_s', '')),
         RunId = tostring(column_ifexists('runId_g', '')), Failure = tostring(column_ifexists('failureType_s', '')),
         Start = todatetime(column_ifexists('start_t', datetime(null))), End = todatetime(column_ifexists('end_t', datetime(null))))
| where TimeGenerated {TimeRange}
| where _ResourceId in~ ({Factories})
| where Status in~ ('Succeeded', 'Failed', 'Cancelled')
| extend Factory = tostring(split(_ResourceId, '/')[8]), Stage = tostring(split(Pipeline, '_')[0])"""

ACTIVITY_RUNS = """
union isfuzzy=true (datatable(TimeGenerated: datetime)[]),
    (ADFActivityRun
     | extend Pipeline = tostring(column_ifexists('PipelineName', '')), Activity = tostring(column_ifexists('ActivityName', '')),
         ActivityType = tostring(column_ifexists('ActivityType', '')), Status = tostring(column_ifexists('Status', '')),
         ErrorCode = tostring(column_ifexists('ErrorCode', '')), Error = tostring(column_ifexists('ErrorMessage', ''))),
    (AzureDiagnostics
     | where ResourceProvider =~ 'MICROSOFT.DATAFACTORY' and Category =~ 'ActivityRuns'
     | extend Pipeline = tostring(column_ifexists('pipelineName_s', '')), Activity = tostring(column_ifexists('activityName_s', '')),
         ActivityType = tostring(column_ifexists('activityType_s', '')), Status = tostring(column_ifexists('status_s', '')),
         ErrorCode = tostring(column_ifexists('errorCode_s', '')), Error = tostring(column_ifexists('errorMessage_s', '')))
| where TimeGenerated {TimeRange}
| where _ResourceId in~ ({Factories})"""

TRIGGER_RUNS = """
union isfuzzy=true (datatable(TimeGenerated: datetime)[]),
    (ADFTriggerRun
     | extend Trigger = tostring(column_ifexists('TriggerName', '')), Status = tostring(column_ifexists('Status', '')),
         TriggerType = tostring(column_ifexists('TriggerType', ''))),
    (AzureDiagnostics
     | where ResourceProvider =~ 'MICROSOFT.DATAFACTORY' and Category =~ 'TriggerRuns'
     | extend Trigger = tostring(column_ifexists('triggerName_s', '')), Status = tostring(column_ifexists('status_s', '')),
         TriggerType = tostring(column_ifexists('triggerType_s', '')))
| where TimeGenerated {TimeRange}
| where _ResourceId in~ ({Factories})"""

RUNS_CHART_Q = PIPELINE_RUNS + """
| summarize Runs = dcount(RunId) by bin(TimeGenerated, {TimeRange:grain}), Status
"""

PIPELINE_SUMMARY_Q = PIPELINE_RUNS + """
| summarize arg_max(TimeGenerated, Status, Failure), Runs = dcount(RunId), Failed = dcountif(RunId, Status =~ 'Failed'),
    AvgMinutes = round(avgif(datetime_diff('second', End, Start), Status =~ 'Succeeded') / 60.0, 1),
    LastSuccess = maxif(TimeGenerated, Status =~ 'Succeeded')
    by Factory, Stage, Pipeline
| project Factory, Stage, Pipeline, LastStatus = Status, LastRun = TimeGenerated, LastSuccess, Runs, Failed,
    AvgMinutes, LastFailure = Failure
| order by case(LastStatus =~ 'Failed', 0, 1) asc, Failed desc
"""

ACTIVITY_ERRORS_Q = ACTIVITY_RUNS + r"""
| where Status =~ 'Failed'
| extend Pattern = replace_regex(substring(Error, 0, 250), @'[0-9a-fA-F]{8}-[0-9a-fA-F-]{27}|\d+', '#')
| summarize Failures = count(), LastSeen = max(TimeGenerated), Sample = take_any(substring(Error, 0, 500))
    by Pipeline, Activity, ActivityType, ErrorCode, Pattern
| project-away Pattern
| order by Failures desc
| take 100
"""

TRIGGER_Q = TRIGGER_RUNS + """
| summarize arg_max(TimeGenerated, Status), Runs = count(), Failed = countif(Status =~ 'Failed') by Trigger, TriggerType
| project Trigger, TriggerType, LastStatus = Status, LastRun = TimeGenerated, Runs, Failed
| order by Failed desc, Trigger asc
"""

# Data Explorer ingestion diagnostics (resource-specific tables). The hub ingests each export through the
# *_raw tables, whose update policies fill *_final_v* tables.
FAILED_INGESTION_Q = """
union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (FailedIngestion)
| where TimeGenerated {TimeRange}
| where _ResourceId in~ ({Clusters})
| summarize Failures = count(), LastSeen = max(TimeGenerated),
    Sample = take_any(substring(tostring(column_ifexists('Details', '')), 0, 400)),
    Source = take_any(tostring(column_ifexists('IngestionSourcePath', '')))
    by Database = tostring(column_ifexists('Database', '')), Table = tostring(column_ifexists('Table', '')),
    ErrorCode = tostring(column_ifexists('ErrorCode', '')), FailureStatus = tostring(column_ifexists('FailureStatus', ''))
| order by LastSeen desc
"""

SUCCEEDED_INGESTION_Q = """
union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (SucceededIngestion)
| where TimeGenerated {TimeRange}
| where _ResourceId in~ ({Clusters})
| summarize Ingestions = count(), LastIngested = max(TimeGenerated)
    by Database = tostring(column_ifexists('Database', '')), Table = tostring(column_ifexists('Table', ''))
| order by Database asc, Table asc
"""

INGESTION_CHART_Q = """
union isfuzzy=true (datatable(TimeGenerated: datetime)[]),
    (SucceededIngestion | extend Result = 'Succeeded'), (FailedIngestion | extend Result = 'Failed')
| where TimeGenerated {TimeRange}
| where _ResourceId in~ ({Clusters})
| summarize Ingestions = count() by bin(TimeGenerated, {TimeRange:grain}), Result
"""

ADX_COMMANDS_Q = """
union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (ADXCommand)
| where TimeGenerated {TimeRange}
| where _ResourceId in~ ({Clusters})
| where tostring(column_ifexists('State', '')) !~ 'Completed'
| summarize Commands = count(), LastSeen = max(TimeGenerated),
    Reason = take_any(substring(tostring(column_ifexists('FailureReason', '')), 0, 400)),
    Sample = take_any(substring(tostring(column_ifexists('Text', '')), 0, 200))
    by Database = tostring(column_ifexists('DatabaseName', '')), CommandType = tostring(column_ifexists('CommandType', '')),
    State = tostring(column_ifexists('State', ''))
| order by LastSeen desc
"""

# Cost Management writes exports into msexports; the pipelines turn them into parquet in ingestion. A container
# that stops receiving files is an export (or a pipeline) that stopped.
BLOB_ARRIVALS_Q = """
union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (StorageBlobLogs)
| where TimeGenerated {TimeRange}
| where _ResourceId in~ ({StorageAccounts})
| where OperationName in ('PutBlob', 'PutBlockList', 'FlushFile', 'CreatePathFile', 'CopyBlob')
| extend Path = tostring(split(tostring(parse_url(Uri).Path), '?')[0])
| extend Container = tostring(split(Path, '/')[1])
| where Container in ('msexports', 'ingestion', 'config')
| summarize Files = count(), Manifests = countif(Path endswith 'manifest.json'), LastFile = max(TimeGenerated),
    Writers = strcat_array(make_set(AuthenticationType, 4), ', ')
    by StorageAccount = tostring(split(_ResourceId, '/')[8]), Container
| order by StorageAccount asc, Container asc
"""

BLOB_ERRORS_Q = """
union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (StorageBlobLogs)
| where TimeGenerated {TimeRange}
| where _ResourceId in~ ({StorageAccounts})
| where toint(StatusCode) >= 400 and StatusCode !in ('404', '409')
| summarize Errors = count(), LastSeen = max(TimeGenerated), Callers = strcat_array(make_set(CallerIpAddress, 5), ', ')
    by StorageAccount = tostring(split(_ResourceId, '/')[8]), OperationName, StatusCode, StatusText, AuthenticationType
| order by Errors desc
"""

ACTIVITY_Q = """
AzureActivity
| where TimeGenerated {TimeRange}
| where CategoryValue =~ 'Administrative'
| where ResourceProviderValue in~ ('Microsoft.DataFactory', 'Microsoft.Kusto', 'Microsoft.Storage', 'Microsoft.KeyVault',
    'Microsoft.Resources', 'Microsoft.CostManagement', 'Microsoft.Network', 'Microsoft.ManagedIdentity')
| where tolower(ResourceGroup) in~ ({HubResourceGroups})
| summarize Count = count(), LastSeen = max(TimeGenerated), Callers = strcat_array(make_set(Caller, 5), ', ')
    by Operation = OperationNameValue, Status = ActivityStatusValue, ResourceGroup
| order by case(Status =~ 'Failure', 0, 1) asc, LastSeen desc
"""

# Every hub resource that can log, against the last record it wrote to any table in the workspace.
SENDING_Q = """
arg("").Resources
| extend Hub = tolower(tostring(tags['cm-resource-parent']))
| where Hub in~ ({Hub})
| where type in~ ('microsoft.datafactory/factories', 'microsoft.kusto/clusters', 'microsoft.storage/storageaccounts',
    'microsoft.keyvault/vaults')
| project ResourceId = tolower(id), Type = tostring(split(type, '/')[1])
| join kind=leftouter (
    union withsource=LogTable_ *
    | where TimeGenerated {TimeRange}
    | where _ResourceId has_any ('/microsoft.datafactory/', '/microsoft.kusto/', '/microsoft.storage/', '/microsoft.keyvault/')
    | extend ResourceId = strcat_array(array_slice(split(tolower(_ResourceId), '/'), 0, 8), '/')
    | summarize Records = count(), LastRecord = max(TimeGenerated), Tables = strcat_array(make_set(LogTable_, 8), ', ')
        by ResourceId
  ) on ResourceId
| extend Status = case(isnull(LastRecord), 'No logs', LastRecord < ago(1d), 'Stale', 'Logging')
| project ResourceId, Type, Status, Records, LastRecord, Tables
| order by case(Status == 'No logs', 0, Status == 'Stale', 1, 2) asc
"""

# ---------------------------------------------------------------------------
# Parameters and tabs
# ---------------------------------------------------------------------------


def hub_resource_param(name, label, rtype, description, extra=""):
    p = resource_param(name, label, HUB_RES + f"\n| where type =~ '{rtype}'" + extra)
    p["id"] = gid(f"{P}-param-{name}")
    p["description"] = description
    return p


def global_params():
    hub = {
        "id": gid(f"{P}-param-Hub"), "version": "KqlParameterItem/1.0", "name": "Hub", "label": "FinOps hubs",
        "type": 2, "isRequired": True, "multiSelect": True, "quote": "'", "delimiter": ",",
        "query": HUB_PARAM_Q.strip(), "crossComponentResources": ["{Subscription}"],
        "typeSettings": {"additionalResourceOptions": ["value::all"], "showDefault": False},
        "defaultValue": "value::all", "value": ["value::all"], "queryType": 1,
        "resourceType": "microsoft.resourcegraph/resources",
        "description": "Hubs are found by the cm-resource-parent tag the hub template puts on every resource.",
    }
    rgs = hidden_arg_param(P, "HubResourceGroups", HUB_RES + """
| summarize by rg = tolower(resourceGroup)
| summarize value = strcat_array(make_list(strcat("'", rg, "'")), ',')""")
    return params(f"{P}-params", [
        subscription_param(P),
        hub,
        time_param(P, DAY_MS, [h * HOUR_MS for h in (4, 12)] + [d * DAY_MS for d in (1, 3, 7, 14, 30)],
                   "Applies to metrics, pipeline runs, changes and log panels."),
        workspace_param(P, "Optional. The workspace the hub resources' diagnostic settings send to. Enables the Logs "
                           "tab and the data checks on the Data Explorer tab."),
        free_text_param(P, "LatestVersion", "Latest version",
                        "The current FinOps toolkit release. Hubs whose ftk-version tag is lower are flagged.",
                        LATEST),
        hub_resource_param("Factories", "Data factories", ADF, "The hubs' data factories."),
        hub_resource_param("Clusters", "Data Explorer clusters", ADX, "The hubs' Data Explorer clusters."),
        hub_resource_param("StorageAccounts", "Storage accounts", STG,
                           "The hubs' data lake storage accounts (the deployment script account is left out).",
                           "\n| where name !contains 'script'"),
        hub_resource_param("Vaults", "Key vaults", KV, "Remote hubs only: the vault holding the remote hub's key."),
        rgs,
        {"id": gid(f"{P}-param-selectedTab"), "version": "KqlParameterItem/1.0", "name": "selectedTab", "type": 1,
         "value": "overview", "isHiddenWhenLocked": True},
    ])


def single_param(name, label, rtype, description):
    return {
        "id": gid(f"{P}-param-{name}"), "version": "KqlParameterItem/1.0", "name": name, "label": label,
        "type": 5, "isRequired": False, "multiSelect": False,
        "query": HUB_RES.strip() + f"\n| where type =~ '{rtype}'\n| project id",
        "crossComponentResources": ["{Subscription}"],
        "typeSettings": {"additionalResourceOptions": ["value::1"], "showDefault": False},
        "defaultValue": "value::1", "queryType": 1, "resourceType": "microsoft.resourcegraph/resources",
        "description": description,
    }


def tabs():
    return {"type": 11, "content": {"version": "LinkItem/1.0", "style": "tabs", "links": [
        {"id": gid(f"{P}-tab-" + key), "cellValue": "selectedTab", "linkTarget": "parameter",
         "linkLabel": label, "subTarget": key, "style": "link"} for key, label in TABS
    ]}, "name": f"{P}-tabs"}


def found(param):
    return {"parameterName": param, "comparison": "isNotEqualTo", "value": ""}


YES_NO = dict(good=["Yes"], warn=["No"])
RUN_STATUS = status_fmt("Status", good=["Succeeded"], warn=["InProgress", "Queued", "Cancelling", "Cancelled"],
                        bad=["Failed"])
TRIGGER_STATE = status_fmt("State", good=["Started"], bad=["Stopped", "Disabled"])
CONNECTION = status_fmt("Connection", good=["Approved"], warn=["Pending"], bad=["Rejected", "Disconnected"])
LOGGING = status_fmt("Status", good=["Logging"], warn=["Stale"], bad=["No logs"])
CHANGE = status_fmt("ChangeType", good=["Create"], warn=["Update"], bad=["Delete"])


def overview_tab():
    return group(f"{P}-tab-overview", [
        *[arg(f"{P}-tile-{key}", "", q, vis="tiles", tiles=big_number_tiles("Signal", "State", "Value", "Detail"),
              fixed_px=ONE_TILE) for key, q in TILES],
        text(f"{P}-tile-note", TILE_NOTE, "info"),
        arg(f"{P}-hubs", "FinOps hubs", HUBS_Q,
            formatters=[health_fmt(), status_fmt("UpToDate", good=["Current"], warn=["Behind"], neutral=["Unknown"]),
                        status_fmt("Network", good=["Private", "Private (NAT gateway)"], neutral=["Public"]),
                        low_is_good("Leftovers", 1, 1), hidden("Hub")],
            labels={"UpToDate": "Version check", "DataStore": "Data store", "RemoteHub": "Remote hub",
                    "Leftovers": "Leftover scripts", "ResourceGroup": "Resource group"},
            no_data="No FinOps hubs found. A hub's resources carry the tag cm-resource-parent = "
                    ".../providers/Microsoft.Cloud/hubs/<name>; check the subscriptions selected."),
        metric_grid(f"{P}-adf-kpis", "Data Factory runs per factory (time range)", ADF, "Factories", [
            ("PipelineSucceededRuns", SUM, "Pipelines succeeded", None),
            ("PipelineFailedRuns", SUM, "Pipelines failed", ("low", 1, 1)),
            ("ActivityFailedRuns", SUM, "Activities failed", ("low", 1, 1)),
            ("TriggerSucceededRuns", SUM, "Triggers succeeded", None),
            ("TriggerFailedRuns", SUM, "Triggers failed", ("low", 1, 1)),
        ], size=3, visible_when=found("Factories")),
        metric_grid(f"{P}-adx-kpis", "Data Explorer per cluster (time range)", ADX, "Clusters", [
            ("KeepAlive", AVG, "Keep alive", ("high", 1, 0.9)),
            ("CPU", AVG, "CPU %", ("low", 70, 85)),
            ("IngestionUtilization", AVG, "Ingestion utilisation %", ("low", 70, 90)),
            ("CacheUtilization", AVG, "Cache utilisation %", ("low", 80, 95)),
            ("IngestionLatencyInSeconds", AVG, "Ingestion latency (s)", None),
        ], size=3, visible_when=found("Clusters")),
        arg(f"{P}-inventory", "Hub resources", INVENTORY_Q,
            formatters=[resource_link(), health_fmt(), PROVISIONING],
            labels={"HubName": "Hub", "id": "Resource"}, group_by="HubName",
            no_data="No hub resources."),
        arg(f"{P}-service-health", "Service Health events for Data Factory, Data Explorer, Storage, Key Vault and "
            "Cost Management (active, or updated in the last 30 days)", SERVICE_HEALTH_Q,
            formatters=[status_fmt("EventType", warn=["PlannedMaintenance", "HealthAdvisory"], bad=["ServiceIssue"]),
                        status_fmt("Status", warn=["Active"], neutral=["Resolved"])],
            labels={"EventType": "Type", "LastUpdate": "Last update", "TrackingId": "Tracking id"},
            no_data="No Service Health events for the services a hub uses."),
        arg(f"{P}-advisor", "Advisor recommendations for hub resources", ADVISOR_Q, width=50,
            formatters=[resource_link("Resource"), status_fmt("Impact", warn=["Medium"], bad=["High"],
                                                              neutral=["Low"])],
            no_data="No Advisor recommendations for hub resources."),
        arg(f"{P}-health-history", "Resource Health changes (time range, up to 14 days)", HEALTH_HISTORY_Q,
            width=50, formatters=[resource_link(), health_fmt(), health_fmt("Previous")],
            labels={"id": "Resource"}, no_data="No Resource Health changes in the time range."),
        arg(f"{P}-changes", "Changes to hub resources (time range, up to 14 days)", CHANGES_Q,
            formatters=[resource_link("Resource"), CHANGE],
            labels={"ChangeType": "Change", "ChangedBy": "Changed by"}, no_data="No changes in the time range."),
    ], tab="overview")


def pipelines_tab():
    factory = single_param("Factory", "Data factory", ADF,
                           "Triggers, runs and managed private endpoints are read from Azure Resource Manager for "
                           "one factory at a time.")
    window = {"lastUpdatedAfter": "{TimeRange:startISO}", "lastUpdatedBefore": "{TimeRange:endISO}"}
    runs = export_row(arm(f"{P}-runs", "Pipeline runs (time range, newest 100). Select a run to see its activities",
                          "{Factory}/queryPipelineRuns", ADF_API, [
                              ("Pipeline", "$.pipelineName", None), ("Status", "$.status", None),
                              ("Start", "$.runStart", "datetime"), ("End", "$.runEnd", "datetime"),
                              ("DurationMs", "$.durationInMs", "number"), ("InvokedBy", "$.invokedBy.name", None),
                              ("Message", "$.message", None), ("RunId", "$.runId", None)],
                          body={**window, "orderBy": [{"orderBy": "RunStart", "order": "DESC"}]},
                          formatters=[RUN_STATUS],
                          labels={"DurationMs": "Duration (ms)", "InvokedBy": "Invoked by", "RunId": "Run id"},
                          no_data="No pipeline runs in the time range."), "RunId", "RunId")
    items = [
        text(f"{P}-adf-note", "How a hub moves data: Cost Management writes an export into **msexports** → trigger "
             "`msexports_ManifestAdded` runs **msexports_ExecuteETL** (→ msexports_ETL_ingestion), which writes "
             "parquet into **ingestion** → trigger `ingestion_ManifestAdded` runs **ingestion_ExecuteETL** "
             "(→ ingestion_ETL_dataExplorer), which ingests into Data Explorer. The **config_** pipelines manage "
             "exports (`config_DailySchedule`, `config_MonthlySchedule`, `config_SettingsUpdated`) and backfill. "
             "Every trigger below should be **Started**.", "info"),
        arm(f"{P}-triggers", "Triggers", "{Factory}/triggers", ADF_API, [
            ("Trigger", "$.name", None), ("State", "$.properties.runtimeState", None),
            ("Type", "$.properties.type", None),
            ("Pipeline", "$.properties.pipelines[0].pipelineReference.referenceName", None),
            ("BlobPath", "$.properties.typeProperties.blobPathBeginsWith", None),
            ("Frequency", "$.properties.typeProperties.recurrence.frequency", None)],
            formatters=[TRIGGER_STATE], labels={"BlobPath": "Blob path begins with"}, width=60,
            no_data="No triggers: the hub deployment did not finish."),
        arm(f"{P}-mpe", "Managed private endpoints", "{Factory}/managedVirtualNetworks/default/managedPrivateEndpoints",
            ADF_API, [
                ("Endpoint", "$.name", None), ("Connection", "$.properties.connectionState.status", None),
                ("Target", "$.properties.privateLinkResourceId", None), ("SubResource", "$.properties.groupId", None),
                ("Provisioning", "$.properties.provisioningState", None)],
            formatters=[CONNECTION, PROVISIONING], labels={"SubResource": "Sub-resource"}, width=40,
            no_data="No managed private endpoints (a hub with public access has none)."),
        metrics(f"{P}-runs-chart", "Pipeline runs", ADF, "Factory", [
            m(ADF, "PipelineSucceededRuns", SUM), m(ADF, "PipelineFailedRuns", SUM),
            m(ADF, "PipelineCancelledRuns", SUM)], width=50),
        metrics(f"{P}-failed-by-pipeline", "Failed pipeline runs by pipeline", ADF, "Factory", [
            m(ADF, "PipelineFailedRuns", SUM, split="Name")], width=50),
        metrics(f"{P}-failed-activities", "Failed activity runs by pipeline", ADF, "Factory", [
            m(ADF, "ActivityFailedRuns", SUM, split="PipelineName")], width=50),
        metrics(f"{P}-failed-triggers", "Failed trigger runs by trigger", ADF, "Factory", [
            m(ADF, "TriggerFailedRuns", SUM, split="Name")], width=50),
        runs,
        when_set(arm(f"{P}-activities", "Activity runs for the selected pipeline run",
                     "{Factory}/pipelineruns/{RunId}/queryActivityruns", ADF_API, [
                         ("Activity", "$.activityName", None), ("Type", "$.activityType", None),
                         ("Status", "$.status", None), ("Start", "$.activityRunStart", "datetime"),
                         ("End", "$.activityRunEnd", "datetime"), ("DurationMs", "$.durationInMs", "number"),
                         ("ErrorCode", "$.error.errorCode", None), ("Error", "$.error.message", None)],
                     body={**window, "orderBy": [{"orderBy": "ActivityRunStart", "order": "ASC"}]},
                     formatters=[RUN_STATUS], labels={"DurationMs": "Duration (ms)", "ErrorCode": "Error code"},
                     no_data="No activity runs for this pipeline run."), "RunId"),
        arm(f"{P}-trigger-runs", "Trigger runs (time range, newest 100)", "{Factory}/queryTriggerRuns", ADF_API, [
            ("Trigger", "$.triggerName", None), ("Status", "$.status", None), ("Type", "$.triggerType", None),
            ("Time", "$.triggerRunTimestamp", "datetime"), ("Message", "$.message", None)],
            body={**window, "orderBy": [{"orderBy": "TriggerRunTimestamp", "order": "DESC"}]},
            formatters=[RUN_STATUS], no_data="No trigger runs in the time range."),
        arm(f"{P}-diag", "Diagnostic settings", "{Factory}/providers/Microsoft.Insights/diagnosticSettings",
            "2021-05-01-preview", [
                ("Setting", "$.name", None), ("Workspace", "$.properties.workspaceId", None),
                ("Mode", "$.properties.logAnalyticsDestinationType", None),
                ("Logs", "$.properties.logs[0].enabled", None)],
            no_data="No diagnostic settings: pipeline run history is only kept 45 days in Data Factory, and the "
                    "Logs tab has nothing to read."),
    ]
    return group(f"{P}-tab-pipelines", [params(f"{P}-adf-params", [factory])] + [when_set(i, "Factory") for i in items],
                 tab="pipelines")


def adx_tab():
    cluster = single_param("Cluster", "Data Explorer cluster", ADX,
                           "Configuration, databases and data checks are for one cluster at a time.")
    uri = hidden_arg_param(P, "ClusterUri", "resources\n| where id =~ '{Cluster}'\n| project value = tostring(properties.uri)")
    data_checks = [
        text(f"{P}-adx-data-h", "### Data in the hub"),
        text(f"{P}-adx-data-hint", "Select a **Log Analytics workspace** at the top to check the data itself: these "
             "panels read the cluster's **Hub** and **Ingestion** databases through a cross-service `adx()` query. "
             "You need at least *Viewer* on those databases, and the portal must be able to reach the cluster.",
             "info", visible_when=WORKSPACE_UNSET),
        *[la(f"{P}-adx-fresh-{fn}", "", freshness_q(fn, col, daily), time=False, vis="tiles",
             tiles=big_number_tiles("Signal", "State", "Value", "Detail"), fixed_px=ONE_TILE,
             no_data=f"Could not read {fn}()") for fn, col, daily in DATASETS],
        text(f"{P}-adx-fresh-note", "Rows in each Hub database function (latest FOCUS schema). **Costs** and "
             "**CommitmentDiscountUsage** turn amber when the latest charge is more than 3 days old; any dataset is "
             "red when empty. A tile showing an error means the function is missing (an older hub) or the cluster "
             "cannot be reached.", "info"),
        la(f"{P}-adx-monthly", "Cost per month (Costs(), last 13 months): a gap is a month that was not exported or "
           "not ingested", MONTHLY_Q, time=False, vis="barchart", width=60,
           no_data="No cost data in the Hub database."),
        la(f"{P}-adx-monthly-t", "Rows per month", MONTHLY_Q, time=False, width=40, no_data="No cost data."),
        la(f"{P}-adx-settings", "Hub settings (Ingestion database, HubSettings())", SETTINGS_Q, time=False, width=50,
           no_data="No hub settings recorded."),
        la(f"{P}-adx-scopes", "Scopes the hub exports (HubScopes())", SCOPES_Q, time=False, width=50,
           no_data="No scopes recorded: the hub has no managed exports, or exports are configured by hand."),
    ]
    items = [
        arg(f"{P}-adx-config", "Cluster", CLUSTER_Q,
            formatters=[status_fmt("State", good=["Running"], warn=["Starting", "Stopping", "Updating"],
                                   bad=["Stopped", "Unavailable"]),
                        PROVISIONING, status_fmt("Tier", good=["Standard"], warn=["Basic"]),
                        {"columnMatch": "Uri", "formatter": 7, "formatOptions": {"linkTarget": "Url"}}],
            labels={"AutoStop": "Auto-stop", "OptimizedAutoscale": "Optimized autoscale",
                    "PublicNetwork": "Public network", "StreamingIngest": "Streaming ingest"}),
        text(f"{P}-adx-note", "**Tier Basic** is the *Dev (No SLA)* SKU: a single node with no SLA. **Auto-stop** "
             "stops a cluster nobody queries for 5 days, and a stopped cluster cannot ingest, so turn it off for a hub. "
             "The hub keeps `*_raw` tables for 0 days and `*_final_v*` tables for 13 months by default; v15 no longer "
             "resets your retention when you redeploy.", "info"),
        arm(f"{P}-adx-dbs", "Databases", "{Cluster}/databases", ADX_API, [
            ("Database", "$.name", None), ("Kind", "$.kind", None),
            ("HotCache", "$.properties.hotCachePeriod", None), ("SoftDelete", "$.properties.softDeletePeriod", None),
            ("SizeBytes", "$.properties.statistics.size", "number"),
            ("Provisioning", "$.properties.provisioningState", None)],
            formatters=[PROVISIONING], labels={"HotCache": "Hot cache", "SoftDelete": "Retention (soft delete)",
                                               "SizeBytes": "Size (bytes)"},
            no_data="No databases: the hub deployment did not finish."),
        metrics(f"{P}-adx-keepalive", "Keep alive (1 = responding)", ADX, "Cluster", [m(ADX, "KeepAlive", AVG)],
                width=50),
        metrics(f"{P}-adx-cpu", "CPU and cache utilisation %", ADX, "Cluster",
                [m(ADX, "CPU", AVG), m(ADX, "CacheUtilization", AVG)], width=50),
        metrics(f"{P}-adx-ing-result", "Ingestion result", ADX, "Cluster",
                [m(ADX, "IngestionResult", SUM, split="IngestionResultDetails")], width=50),
        metrics(f"{P}-adx-ing-latency", "Ingestion latency (s) and utilisation %", ADX, "Cluster",
                [m(ADX, "IngestionLatencyInSeconds", AVG), m(ADX, "IngestionUtilization", AVG)], width=50),
        metrics(f"{P}-adx-ing-volume", "Ingestion volume (MB) by database", ADX, "Cluster",
                [m(ADX, "IngestionVolumeInMB", SUM, split="Database")], width=50),
        metrics(f"{P}-adx-queries", "Query duration by status, throttled queries", ADX, "Cluster",
                [m(ADX, "QueryDuration", AVG, split="QueryStatus"), m(ADX, "TotalNumberOfThrottledQueries", MAX)],
                width=50),
        *[when_set(i, "ClusterUri") for i in data_checks],
        arm(f"{P}-adx-diag", "Diagnostic settings", "{Cluster}/providers/Microsoft.Insights/diagnosticSettings",
            "2021-05-01-preview", [
                ("Setting", "$.name", None), ("Workspace", "$.properties.workspaceId", None),
                ("Mode", "$.properties.logAnalyticsDestinationType", None)],
            no_data="No diagnostic settings: failed ingestions are not logged anywhere."),
    ]
    return group(f"{P}-tab-adx", [
        text(f"{P}-adx-none", "No Data Explorer cluster in the selected hubs. A hub that stores data in **Microsoft "
             "Fabric** (Real-Time Intelligence eventhouse) or in storage only has none; monitor a Fabric eventhouse "
             "from the Fabric capacity metrics app.", "info",
             visible_when={"parameterName": "Clusters", "comparison": "isEqualTo", "value": ""}),
        params(f"{P}-adx-params", [cluster, uri]),
    ] + [when_set(i, "Cluster") for i in items], tab="adx")


def storage_tab():
    scope = free_text_param(P, "ExportScope", "Export scope",
                            "The Cost Management scope the exports are defined at, for example "
                            "/providers/Microsoft.Billing/billingAccounts/1234567 or /subscriptions/<id>.")
    exports = arm(f"{P}-exports", "Cost Management exports at this scope (check the destination is a hub's storage "
                  "account and container msexports)", "{ExportScope}/providers/Microsoft.CostManagement/exports",
                  "2023-07-01-preview", [
                      ("Export", "$.name", None), ("Dataset", "$.properties.definition.type", None),
                      ("Version", "$.properties.definition.dataSet.configuration.dataVersion", None),
                      ("Schedule", "$.properties.schedule.status", None),
                      ("Recurrence", "$.properties.schedule.recurrence", None),
                      ("Status", "$.properties.runHistory.value[0].properties.status", None),
                      ("LastRun", "$.properties.runHistory.value[0].properties.processingEndTime", "datetime"),
                      ("Error", "$.properties.runHistory.value[0].properties.error.message", None),
                      ("NextRun", "$.properties.nextRunTimeEstimate", "datetime"),
                      ("Container", "$.properties.deliveryInfo.destination.container", None),
                      ("Destination", "$.properties.deliveryInfo.destination.resourceId", None)],
                  url_params=[("$expand", "runHistory")],
                  formatters=[status_fmt("Status", good=["Completed", "Succeeded"], warn=["InProgress", "Queued"],
                                         bad=["Failed", "Timeout"]),
                              status_fmt("Schedule", good=["Active"], warn=["Inactive"]),
                              status_fmt("Container", good=["msexports"], warn=["ingestion"]),
                              resource_link("Destination")],
                  labels={"LastRun": "Last run", "NextRun": "Next run (estimate)", "Status": "Last run status"},
                  no_data="No exports at this scope, or you need Cost Management Reader on it.")
    return group(f"{P}-tab-storage", [
        arg(f"{P}-storage", "Hub storage accounts", STORAGE_Q,
            formatters=[resource_link(), PROVISIONING,
                        status_fmt("DataLake", good=["true"], bad=["false"]),
                        status_fmt("PublicNetwork", good=["Disabled"], neutral=["Enabled"])],
            labels={"DataLake": "Hierarchical namespace", "PublicNetwork": "Public network",
                    "DefaultAction": "Firewall default", "SharedKey": "Shared key", "MinTls": "Min TLS",
                    "HubName": "Hub"}, no_data="No hub storage accounts."),
        metric_grid(f"{P}-stg-kpis", "Data lake storage accounts (time range)", STG, "StorageAccounts", [
            ("Availability", AVG, "Availability %", ("high", 99.9, 99)),
            ("Transactions", SUM, "Transactions", None),
            ("SuccessE2ELatency", AVG, "E2E latency (ms)", None),
            ("UsedCapacity", AVG, "Used capacity", None),
        ], size=3, visible_when=found("StorageAccounts")),
        metrics(f"{P}-stg-tx", "Transactions by response type", STG, "StorageAccounts",
                [m(STG, "Transactions", SUM, split="ResponseType")], width=50, visible_when=found("StorageAccounts")),
        metrics(f"{P}-stg-cap", "Used capacity", STG, "StorageAccounts",
                [m(STG, "UsedCapacity", AVG)], width=50, visible_when=found("StorageAccounts")),
        text(f"{P}-exports-h", "### Cost Management exports\n"
             "A hub only gets data when an export writes into its **msexports** container (FOCUS cost, price sheet, "
             "reservation details, recommendations and transactions). Managed exports (hub v0.x settings) are created "
             "by `config_ConfigureExports`; otherwise they are created by hand. Enter the scope the exports are "
             "defined at to check their last run."),
        params(f"{P}-exports-params", [scope]),
        when_set(exports, "ExportScope"),
    ], tab="storage")


def network_tab():
    return group(f"{P}-tab-network", [
        text(f"{P}-net-note", "v15 adds **VNet** and **private network** modes with an opt-in **NAT gateway**. In "
             "private mode the storage account, Key Vault and Data Explorer cluster are reached through private "
             "endpoints, and Data Factory through managed private endpoints (on the Data Factory tab), all of which "
             "must be **Approved**. Deployment scripts run in container instances in their own subnet, and need "
             "outbound access (the NAT gateway) to finish.", "info"),
        arg(f"{P}-net", "Networking resources", NETWORK_Q, width=50,
            formatters=[resource_link(), PROVISIONING],
            labels={"HubName": "Hub", "AddressSpace": "Address space", "SubnetCount": "Subnets",
                    "IpAddress": "IP address"}, no_data="No networking resources: the hubs use public access."),
        arg(f"{P}-subnets", "Subnets", SUBNETS_Q, width=50,
            labels={"NatGateway": "NAT gateway", "Nsg": "NSG", "UsedIps": "IP configurations",
                    "VirtualNetwork": "Virtual network", "HubName": "Hub"}, no_data="No hub virtual networks."),
        arg(f"{P}-pe", "Private endpoints to hub resources", PRIVATE_ENDPOINTS_Q,
            formatters=[resource_link(), resource_link("Target"), CONNECTION, PROVISIONING],
            labels={"id": "Private endpoint", "SubResource": "Sub-resource", "HubName": "Hub"},
            no_data="No private endpoints point at hub resources."),
        arg(f"{P}-identities", "Managed identities", IDENTITIES_Q, width=50,
            formatters=[resource_link()], labels={"PrincipalId": "Principal id", "HubName": "Hub"},
            no_data="No identities."),
        arg(f"{P}-coverage", "Metric alert rules on factories and clusters", COVERAGE_Q, width=50,
            formatters=[resource_link(), status_fmt("Covered", **YES_NO)], labels={"Missing": "No alert on"},
            no_data="No factories or clusters."),
        text(f"{P}-coverage-note", "Suggested alerts: Data Factory `PipelineFailedRuns` and `TriggerFailedRuns` "
             "(total > 0), Data Explorer `IngestionResult` split by result (failures > 0) and `KeepAlive` (< 1). A "
             "log alert on `ADFPipelineRun` or `FailedIngestion` works too, but is not counted here.", "info"),
        metrics(f"{P}-kv", "Key Vault availability and API results (remote hubs)", KV, "Vaults",
                [m(KV, "Availability", AVG), m(KV, "ServiceApiResult", SUM, split="StatusCode")],
                visible_when=found("Vaults")),
    ], tab="network")


def logs_tab():
    return group(f"{P}-tab-logs", [
        text(f"{P}-la-hint", "Select a **Log Analytics workspace** at the top. Send the data factories' *Pipeline "
             "runs*, *Activity runs* and *Trigger runs*, the clusters' *Succeeded/Failed ingestion* and *Command*, and "
             "the storage accounts' blob *StorageWrite* logs to it. Resource-specific mode is best; AzureDiagnostics "
             "works for Data Factory.", "info", visible_when=WORKSPACE_UNSET),
        la(f"{P}-la-sending", "Hub resources by last record in the workspace", SENDING_Q,
           formatters=[resource_link("ResourceId"), LOGGING],
           labels={"ResourceId": "Resource", "LastRecord": "Last record"}, no_data="No hub resources."),
        text(f"{P}-la-adf-h", "### Data Factory"),
        la(f"{P}-la-runs", "Pipeline runs by status", RUNS_CHART_Q, vis="timechart", width=50,
           no_data="No pipeline runs logged in the time range."),
        la(f"{P}-la-triggers", "Trigger runs", TRIGGER_Q, width=50,
           formatters=[status_fmt("LastStatus", good=["Succeeded"], bad=["Failed"])],
           labels={"LastStatus": "Last status", "LastRun": "Last run", "TriggerType": "Type"},
           no_data="No trigger runs logged in the time range."),
        la(f"{P}-la-pipelines", "Pipelines: last status, last success and failures", PIPELINE_SUMMARY_Q,
           formatters=[status_fmt("LastStatus", good=["Succeeded"], warn=["Cancelled"], bad=["Failed"])],
           labels={"LastStatus": "Last status", "LastRun": "Last run", "LastSuccess": "Last success",
                   "AvgMinutes": "Avg minutes (succeeded)", "LastFailure": "Failure type"},
           no_data="No pipeline runs logged in the time range."),
        la(f"{P}-la-activity-errors", "Failed activities by error", ACTIVITY_ERRORS_Q,
           labels={"ActivityType": "Type", "ErrorCode": "Error code", "LastSeen": "Last seen"},
           no_data="No failed activities in the time range."),
        text(f"{P}-la-adx-h", "### Data Explorer"),
        la(f"{P}-la-ing-chart", "Ingestions by result", INGESTION_CHART_Q, vis="timechart", width=50,
           no_data="No ingestion logged in the time range."),
        la(f"{P}-la-ing-ok", "Last successful ingestion per table", SUCCEEDED_INGESTION_Q, width=50,
           labels={"LastIngested": "Last ingested"}, no_data="No successful ingestion logged in the time range."),
        la(f"{P}-la-ing-failed", "Failed ingestions", FAILED_INGESTION_Q,
           formatters=[status_fmt("FailureStatus", warn=["Transient"], bad=["Permanent"])],
           labels={"ErrorCode": "Error code", "FailureStatus": "Failure", "LastSeen": "Last seen"},
           no_data="No failed ingestions in the time range."),
        la(f"{P}-la-commands", "Commands that did not complete", ADX_COMMANDS_Q,
           labels={"CommandType": "Command", "LastSeen": "Last seen"},
           no_data="No failed commands in the time range."),
        text(f"{P}-la-stg-h", "### Storage"),
        la(f"{P}-la-blobs", "Files written per container", BLOB_ARRIVALS_Q, width=50,
           labels={"StorageAccount": "Storage account", "LastFile": "Last file"},
           no_data="No writes to msexports, ingestion or config logged in the time range."),
        la(f"{P}-la-blob-errors", "Storage errors (excluding 404 and 409)", BLOB_ERRORS_Q, width=50,
           labels={"StorageAccount": "Storage account", "OperationName": "Operation", "StatusCode": "Code",
                   "StatusText": "Status", "AuthenticationType": "Auth"},
           no_data="No storage errors in the time range."),
        text(f"{P}-la-act-h", "### Azure operations"),
        la(f"{P}-la-activity", "Operations in the hubs' resource groups (activity log)", ACTIVITY_Q,
           formatters=[status_fmt("Status", good=["Succeeded", "Success"], warn=["Started", "Accepted"],
                                  bad=["Failed", "Failure"])],
           labels={"ResourceGroup": "Resource group", "LastSeen": "Last seen"},
           no_data="No operations in the time range (or the activity log is not sent to this workspace)."),
    ], tab="logs")


def workbook():
    return notebook([
        text(f"{P}-header", "# FinOps hubs\n"
             "Are the FinOps hubs healthy and up to date, are the Cost Management exports landing, are the Data "
             "Factory pipelines and triggers running, and is Azure Data Explorer ingesting and holding current data? "
             "Built for FinOps toolkit **v15**; works with earlier hubs."),
        global_params(),
        tabs(),
        overview_tab(),
        pipelines_tab(),
        adx_tab(),
        storage_tab(),
        network_tab(),
        logs_tab(),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
