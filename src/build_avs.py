"""Generates the Azure VMware Solution workbook.

Run:  python src/build_avs.py
Out:  workbook/avs.workbook.json

Are the private clouds healthy, do they have room to grow, are they connected and monitored, and what are vCenter,
ESXi and NSX saying? Health, configuration, alert coverage and the hub connection come from Resource Graph;
CPU, memory and vSAN from platform metrics; clusters, add-ons, Global Reach, NSX segments, DNS forwarding and run
command history from Azure Resource Manager, one private cloud at a time; and the VMware syslog from Log Analytics
when a workspace is selected. Built from the helpers in build_workbook.py so the workbooks look alike.
"""

import pathlib

from build_workbook import (AVG, DAY_MS, ONE_TILE, PROVISIONING, Q_AVS, TWO_METRIC_TILES, WORKSPACE_UNSET, arg,
                            arm, big_number_tiles, gid, group, health_fmt, la, m, metric_grid, metric_tiles, metrics,
                            notebook, params, resource_link, resource_param, status_fmt, subscription_param, text,
                            time_param, when_set, workspace_param, write_workbook)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "avs.workbook.json"

P = "avsw"
NS = "microsoft.avs/privateclouds"
API = "2023-09-01"
HOUR_MS = 3600000

TABS = [
    ("overview", "Overview"),
    ("capacity", "Capacity"),
    ("cloud", "Private cloud"),
    ("logs", "Logs"),
]

# ---------------------------------------------------------------------------
# Shared Resource Graph fragments
# ---------------------------------------------------------------------------

# Each private cloud with its Resource Health state; provisioning state stands in where Resource Health has no
# record.
CLOUDS = f"""
resources
| where type =~ '{NS}'
| project id = tolower(id), Sku = tostring(sku.name),
    MgmtHosts = toint(properties.managementCluster.clusterSize),
    Availability = tostring(properties.availability.strategy),
    Internet = tostring(properties.internet),
    Encryption = tostring(properties.encryption.status),
    NetworkBlock = tostring(properties.networkBlock),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup, Location = location
| join kind=leftouter (
    healthresources
    | where type =~ 'microsoft.resourcehealth/availabilitystatuses'
    | where tolower(id) has '/microsoft.avs/privateclouds/'
    | project id = tostring(split(tolower(id), '/providers/microsoft.resourcehealth/')[0]),
        RhHealth = tostring(properties.availabilityState), Reason = tostring(properties.summary)
  ) on id
| project-away id1
| extend Health = case(isnotempty(RhHealth), RhHealth, Provisioning =~ 'Failed', 'Unavailable',
        Provisioning =~ 'Succeeded', 'Available', 'Degraded'),
    Reason = iff(isempty(RhHealth), strcat('Provisioning: ', Provisioning), Reason)
| project-away RhHealth"""

# The ExpressRoute circuit each private cloud comes with, and the connections that use it: a Virtual WAN
# ExpressRoute gateway lists its connections inside the gateway, a virtual network gateway has a separate
# connection resource. One join only: Resource Graph allows a table once on the right of a join.
ER_GATEWAY = "microsoft.network/expressroutegateways"
HUB_CONNECTIONS = f"""
resources
| where type =~ '{NS}'
| project id = tolower(id), circuit = tolower(tostring(properties.circuit.expressRouteID))
| join kind=leftouter (
    resources
    | where type =~ '{ER_GATEWAY}'
        or type =~ 'microsoft.network/connections' and tostring(properties.connectionType) =~ 'ExpressRoute'
    | extend isHub = type =~ '{ER_GATEWAY}'
    | mv-expand c = iff(isHub, properties.expressRouteConnections, pack_array(properties))
    | project circuit = tolower(iff(isHub,
            tostring(split(tostring(c.properties.expressRouteCircuitPeering.id), '/peerings/')[0]),
            tostring(c.peer.id))),
        Connection = iff(isHub, tostring(c.name), name),
        Gateway = iff(isHub, id, tostring(c.virtualNetworkGateway1.id)),
        ConnectionState = tostring(iff(isHub, c.properties.provisioningState, c.provisioningState)),
        RoutingWeight = toint(iff(isHub, c.properties.routingWeight, c.routingWeight))
    | where isnotempty(circuit)
  ) on circuit
| project-away circuit1"""

# Metric alert rules that watch each private cloud, by the metric they watch. A rule scoped to the resource
# group or subscription counts when it targets private clouds.
ALERT_COVERAGE = f"""
resources
| where type =~ '{NS}'
| extend rid = tolower(id), sub = tolower(strcat('/subscriptions/', subscriptionId))
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
| extend applies = isnotempty(rule) and (scopeKey == rid or target == '{NS}')
| summarize Rules = dcountif(rule, applies),
    Vsan = countif(applies and metric == 'diskusedpercentage'),
    Cpu = countif(applies and metric == 'effectivecpuaverage'),
    Memory = countif(applies and metric == 'usageaverage')
    by id = rid
| extend Missing = trim(@'[, ]+', strcat(iff(Vsan == 0, 'vSAN, ', ''), iff(Cpu == 0, 'CPU, ', ''),
    iff(Memory == 0, 'memory', '')))"""

SERVICE_HEALTH = """
servicehealthresources
| where type =~ 'microsoft.resourcehealth/events'
| where tostring(properties.Impact) has 'VMware'"""

ADVISOR = f"""
advisorresources
| where type =~ 'microsoft.advisor/recommendations'
| where tostring(properties.impactedField) =~ '{NS}'"""

# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

TILES = [
    ("clouds", CLOUDS + """
| summarize Total = count(), Hosts = sum(MgmtHosts),
    Unavailable = countif(Health =~ 'Unavailable'), Degraded = countif(Health !~ 'Available' and Health !~ 'Unavailable')
| project Signal = 'Private clouds', Value = Total,
    Detail = strcat(Unavailable + Degraded, ' unhealthy · ', Hosts, ' management hosts'),
    State = case(Total == 0, 'Unknown', Unavailable > 0, 'Unavailable', Degraded > 0, 'Degraded', 'Available')
"""),
    ("connected", HUB_CONNECTIONS + """
| summarize Connections = countif(isnotempty(Connection)) by id
| summarize Total = count(), NotConnected = countif(Connections == 0)
| project Signal = 'Not connected to a hub', Value = NotConnected,
    Detail = strcat('of ', Total, ' private clouds'),
    State = case(Total == 0, 'Unknown', NotConnected > 0, 'Degraded', 'Available')
"""),
    ("alerts", ALERT_COVERAGE + """
| summarize Total = count(), Gaps = countif(isnotempty(Missing))
| project Signal = 'Missing CPU, memory or vSAN alerts', Value = Gaps,
    Detail = strcat('of ', Total, ' private clouds'),
    State = case(Total == 0, 'Unknown', Gaps > 0, 'Degraded', 'Available')
"""),
    ("health", SERVICE_HEALTH + """
| where tostring(properties.Status) =~ 'Active'
| extend EventType = tostring(properties.EventType), TrackingId = tostring(properties.TrackingId)
| summarize Total = dcount(TrackingId), Issues = dcountif(TrackingId, EventType =~ 'ServiceIssue'),
    Maintenance = dcountif(TrackingId, EventType =~ 'PlannedMaintenance')
| project Signal = 'Active Service Health events', Value = Total,
    Detail = strcat(Issues, ' issues · ', Maintenance, ' maintenance'),
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
Thresholds: CPU and memory warn at **80%** and are critical at **90%**. vSAN warns at **70%** and is critical at
**75%**: AVS needs 25% of each vSAN datastore free to stay within its SLA. *Not connected to a hub* means no
ExpressRoute connection you can see uses the private cloud's circuit; a gateway in a subscription you cannot read
counts as not connected."""

CLOUDS_Q = CLOUDS + """
| project id, Health, Reason, Sku, MgmtHosts, Availability, Internet, Encryption, NetworkBlock, Provisioning,
    ResourceGroup, Location
| order by case(Health =~ 'Unavailable', 0, Health =~ 'Available', 2, 1) asc, id asc
"""

COVERAGE_Q = ALERT_COVERAGE + """
| project id, CPU = iff(Cpu > 0, 'Yes', 'No'), Memory = iff(Memory > 0, 'Yes', 'No'), vSAN = iff(Vsan > 0, 'Yes', 'No'),
    Rules
| order by case(CPU == 'No' or Memory == 'No' or vSAN == 'No', 0, 1) asc
"""

ADVISOR_Q = ADVISOR + """
| project Impact = tostring(properties.impact), Category = tostring(properties.category),
    Problem = tostring(properties.shortDescription.problem), Solution = tostring(properties.shortDescription.solution),
    PrivateCloud = tostring(properties.impactedValue), Updated = todatetime(properties.lastUpdated)
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

HEALTH_HISTORY_Q = """
healthresourcechanges
| where tostring(properties.targetResourceType) =~ 'microsoft.resourcehealth/availabilitystatuses'
| extend Time = todatetime(properties.changeAttributes.timestamp)
| where Time >= todatetime('{TimeRange:startISO}')
| extend id = tostring(split(tolower(tostring(properties.targetResourceId)), '/providers/microsoft.resourcehealth/')[0])
| where id has '/microsoft.avs/privateclouds/'
| extend state = properties.changes['properties.availabilityState']
| where isnotempty(tostring(state.newValue))
| project Time, id, Previous = tostring(state.previousValue), Health = tostring(state.newValue)
| order by Time desc
| take 500
"""

# ---------------------------------------------------------------------------
# Private cloud (one at a time)
# ---------------------------------------------------------------------------

CONFIG_Q = """
resources
| where id =~ '{Cloud}'
| project vCenter = tostring(properties.endpoints.vcsa), NsxManager = tostring(properties.endpoints.nsxtManager),
    HcxManager = tostring(properties.endpoints.hcxCloudManager),
    NetworkBlock = tostring(properties.networkBlock),
    ExtendedBlocks = strcat_array(properties.extendedNetworkBlocks, ', '),
    Internet = tostring(properties.internet), DnsZoneType = tostring(properties.dnsZoneType),
    Availability = tostring(properties.availability.strategy), Zone = tostring(properties.availability.zone),
    SecondaryZone = tostring(properties.availability.secondaryZone),
    Encryption = tostring(properties.encryption.status), Identity = tostring(identity.type)
"""

CLOUD_CONNECTIONS_Q = HUB_CONNECTIONS + """
| where id =~ '{Cloud}'
| project Connection, Gateway, State = iff(isempty(Connection), 'Not connected', ConnectionState), RoutingWeight
"""

CHANGES_Q = """
resourcechanges
| where tolower(tostring(properties.targetResourceId)) startswith tolower('{Cloud}')
| extend Time = todatetime(properties.changeAttributes.timestamp)
| where Time >= todatetime('{TimeRange:startISO}')
| project Time, Resource = tostring(properties.targetResourceId), ChangeType = tostring(properties.changeType),
    Properties = strcat_array(bag_keys(properties.changes), ', '),
    ChangedBy = tostring(properties.changeAttributes.changedBy),
    Client = tostring(properties.changeAttributes.clientType),
    Operation = tostring(properties.changeAttributes.operation)
| order by Time desc
| take 200
"""

# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

# VMware syslog from vCenter, ESXi, vSAN and NSX (the private cloud's diagnostic setting, category VMwareSyslog).
# Read the columns loosely, and fall back to an empty table where the workspace has none.
SYSLOG = """
union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (AVSSyslog)
| where TimeGenerated {TimeRange}
| extend Message = tostring(column_ifexists('Message', '')), Host = tostring(column_ifexists('HostName', '')),
    Source = tostring(column_ifexists('AppName', '')), Severity = tolower(tostring(column_ifexists('Severity', '')))
| extend Level = case(Severity in ('emerg', 'emergency', 'alert', 'crit', 'critical', 'err', 'error'), 'Error',
    Severity in ('warning', 'warn'), 'Warning', 'Info')"""

LEVELS_Q = SYSLOG + """
| summarize Records = count() by bin(TimeGenerated, {TimeRange:grain}), Level
"""

SOURCES_Q = SYSLOG + """
| where Level != 'Info'
| summarize Records = count(), Hosts = dcount(Host), LastSeen = max(TimeGenerated), Sample = take_any(substring(Message, 0, 300))
    by Source, Level
| order by Level asc, Records desc
"""

# Numbers and GUIDs are blanked out so the same message about different objects counts as one.
PATTERNS_Q = SYSLOG + r"""
| where Level == 'Error'
| extend Pattern = replace_regex(substring(Message, 0, 200), @'[0-9a-fA-F]{8}-[0-9a-fA-F-]{27}|\d+', '#')
| summarize Records = count(), Hosts = dcount(Host), LastSeen = max(TimeGenerated) by Source, Pattern
| top 50 by Records desc
"""

# vCenter writes "Alarm '<name>' on <object> changed from <colour> to <colour>".
ALARMS_Q = SYSLOG + r"""
| where Message has 'Alarm' and Message has 'changed from'
| extend Alarm = extract(@"Alarm '([^']+)'", 1, Message),
    Object = extract(@"Alarm '[^']+' on (.+?) changed from", 1, Message),
    To = extract(@'changed from \w+ to (\w+)', 1, Message)
| where isnotempty(Alarm)
| summarize arg_max(TimeGenerated, To), Raised = countif(To in~ ('Yellow', 'Red')) by Alarm, Object
| where Raised > 0
| project Alarm, Object, Now = To, Raised, LastChange = TimeGenerated
| order by case(Now =~ 'Red', 0, Now =~ 'Yellow', 1, 2) asc, Raised desc
"""

# NSX distributed and gateway firewall packet logs, for rules with logging turned on:
# "... FIREWALL_PKTLOG: <id> INET match DROP 1005 IN 52 TCP 10.0.0.1/50432->10.0.1.4/443 ..."
DFW_Q = SYSLOG + r"""
| where Message has 'FIREWALL_PKTLOG' and Message has_any ('DROP', 'REJECT')
| extend f = extract_all(@'INET\s+\w+\s+(\w+)\s+(\d+)\s+(IN|OUT)\s+\d+\s+(\w+)\s+([\d.]+)/?(\d*)->([\d.]+)/?(\d*)', Message)[0]
| where array_length(f) > 0
| summarize Flows = count(), LastSeen = max(TimeGenerated)
    by Action = tostring(f[0]), Rule = tostring(f[1]), Direction = tostring(f[2]), Protocol = tostring(f[3]),
    SourceIp = tostring(f[4]), DestinationIp = tostring(f[6]), Port = tostring(f[7])
| top 200 by Flows desc
"""

ACTIVITY_Q = """
AzureActivity
| where TimeGenerated {TimeRange}
| where ResourceProviderValue =~ 'Microsoft.AVS' and CategoryValue =~ 'Administrative'
| summarize Count = count(), LastSeen = max(TimeGenerated), Callers = strcat_array(make_set(Caller, 5), ', ')
    by Operation = OperationNameValue, Status = ActivityStatusValue, PrivateCloud = tostring(split(_ResourceId, '/')[8])
| order by LastSeen desc
"""

# Every private cloud from Resource Graph, against the last record each wrote to any table in the workspace.
SENDING_Q = f"""
arg("").Resources
| where type =~ '{NS}'
| project ResourceId = tolower(id), ResourceGroup = resourceGroup
| join kind=leftouter (
    union withsource=LogTable_ *
    | where TimeGenerated {{TimeRange}}
    | where _ResourceId has '/microsoft.avs/privateclouds/'
    | extend ResourceId = strcat_array(array_slice(split(tolower(_ResourceId), '/'), 0, 8), '/')
    | summarize Records = count(), LastRecord = max(TimeGenerated), Tables = strcat_array(make_set(LogTable_, 8), ', ')
        by ResourceId
  ) on ResourceId
| extend Status = case(isnull(LastRecord), 'No logs', LastRecord < ago(1d), 'Stale', 'Logging')
| project ResourceId, Status, Records, LastRecord, Tables, ResourceGroup
| order by case(Status == 'No logs', 0, Status == 'Stale', 1, 2) asc
"""

# ---------------------------------------------------------------------------
# Parameters and tabs
# ---------------------------------------------------------------------------


def global_params():
    clouds = resource_param("PrivateClouds", "Private clouds", Q_AVS)
    clouds["id"] = gid(f"{P}-param-PrivateClouds")
    clouds["description"] = "The private clouds the metric charts show."
    return params(f"{P}-params", [
        subscription_param(P),
        time_param(P, DAY_MS, [h * HOUR_MS for h in (4, 12)] + [d * DAY_MS for d in (1, 3, 7, 14, 30)],
                   "Applies to metrics, changes and log panels."),
        workspace_param(P, "Optional. The workspace the private clouds' diagnostic settings send VMware syslog to. "
                           "Enables the Logs tab."),
        clouds,
        {"id": gid(f"{P}-param-selectedTab"), "version": "KqlParameterItem/1.0", "name": "selectedTab", "type": 1,
         "value": "overview", "isHiddenWhenLocked": True},
    ])


def tabs():
    return {"type": 11, "content": {"version": "LinkItem/1.0", "style": "tabs", "links": [
        {"id": gid(f"{P}-tab-" + key), "cellValue": "selectedTab", "linkTarget": "parameter",
         "linkLabel": label, "subTarget": key, "style": "link"} for key, label in TABS
    ]}, "name": f"{P}-tabs"}


CLOUDS_FOUND = {"parameterName": "PrivateClouds", "comparison": "isNotEqualTo", "value": ""}
YES_NO = dict(good=["Yes"], warn=["No"])
STATE = status_fmt("State", good=["Succeeded", "Connected"], warn=["Updating", "Connecting", "Building"],
                   bad=["Failed", "Not connected", "Disconnected"])


def url(col):
    return {"columnMatch": col, "formatter": 7, "formatOptions": {"linkTarget": "Url"}}


def overview_tab():
    return group(f"{P}-tab-overview", [
        *[arg(f"{P}-tile-{key}", "", q, vis="tiles", tiles=big_number_tiles("Signal", "State", "Value", "Detail"),
              fixed_px=ONE_TILE) for key, q in TILES],
        metrics(f"{P}-tile-cpu", "", NS, "PrivateClouds", [m(NS, "EffectiveCpuAverage", AVG)],
                tiles=metric_tiles(80, 90), fixed_px=TWO_METRIC_TILES, visible_when=CLOUDS_FOUND),
        metrics(f"{P}-tile-mem", "", NS, "PrivateClouds", [m(NS, "UsageAverage", AVG)],
                tiles=metric_tiles(80, 90), fixed_px=TWO_METRIC_TILES, visible_when=CLOUDS_FOUND),
        metrics(f"{P}-tile-vsan", "", NS, "PrivateClouds", [m(NS, "DiskUsedPercentage", AVG)],
                tiles=metric_tiles(70, 75), fixed_px=TWO_METRIC_TILES, visible_when=CLOUDS_FOUND),
        text(f"{P}-tile-note", TILE_NOTE, "info"),
        arg(f"{P}-clouds", "Private clouds", CLOUDS_Q, formatters=[resource_link(), health_fmt(), PROVISIONING],
            labels={"id": "Private cloud", "MgmtHosts": "Management hosts", "NetworkBlock": "Network block"},
            no_data="No Azure VMware Solution private clouds found."),
        arg(f"{P}-coverage", "Metric alert rules per private cloud", COVERAGE_Q, width=50,
            formatters=[resource_link(), status_fmt("CPU", **YES_NO), status_fmt("Memory", **YES_NO),
                        status_fmt("vSAN", **YES_NO)],
            labels={"id": "Private cloud", "Rules": "Rules in total"}, no_data="No private clouds."),
        arg(f"{P}-advisor", "Advisor recommendations", ADVISOR_Q, width=50,
            formatters=[status_fmt("Impact", warn=["Medium"], bad=["High"], neutral=["Low"])],
            labels={"PrivateCloud": "Private cloud"}, no_data="No Advisor recommendations for AVS."),
        text(f"{P}-coverage-note", "Microsoft recommends metric alerts on at least vSAN used % "
             "(`DiskUsedPercentage`, above 70%), CPU (`EffectiveCpuAverage`, above 80%) and memory "
             "(`UsageAverage`, above 80%). A rule counts when it is enabled and scoped to the private cloud, or to "
             "its resource group or subscription with private clouds as the target type.", "info"),
        arg(f"{P}-service-health", "Service Health events for Azure VMware Solution (active, or updated in the last "
            "30 days)", SERVICE_HEALTH_Q,
            formatters=[status_fmt("EventType", warn=["PlannedMaintenance", "HealthAdvisory"], bad=["ServiceIssue"]),
                        status_fmt("Status", warn=["Active"], neutral=["Resolved"])],
            labels={"EventType": "Type", "LastUpdate": "Last update", "TrackingId": "Tracking id"},
            no_data="No Service Health events for Azure VMware Solution."),
        arg(f"{P}-health-history", "Resource Health changes (time range, up to 14 days)", HEALTH_HISTORY_Q,
            formatters=[resource_link(), health_fmt(), health_fmt("Previous")],
            labels={"id": "Private cloud"}, no_data="No Resource Health changes in the time range."),
    ], tab="overview")


def capacity_tab():
    return group(f"{P}-tab-capacity", [
        text(f"{P}-vsan-note", "AVS needs **25% vSAN slack space** in every datastore to stay within its SLA, so "
             "keep vSAN used below **75%**. CPU or memory above 80% for days at a time is a sign the cluster needs "
             "another host; a host takes time to add, so act on the trend rather than the peak.", "warning"),
        metric_grid(f"{P}-kpis", "Key metrics per private cloud (time range)", NS, "PrivateClouds", [
            ("EffectiveCpuAverage", AVG, "CPU %", ("low", 80, 90)),
            ("UsageAverage", AVG, "Memory %", ("low", 80, 90)),
            ("DiskUsedPercentage", AVG, "vSAN used %", ("low", 70, 75)),
            ("UsedLatest", AVG, "Datastore used", None),
            ("CapacityLatest", AVG, "Datastore capacity", None),
        ], size=3),
        metrics(f"{P}-cpu", "CPU % by cluster", NS, "PrivateClouds",
                [m(NS, "EffectiveCpuAverage", AVG, split="clustername")], width=50),
        metrics(f"{P}-mem", "Memory % by cluster", NS, "PrivateClouds",
                [m(NS, "UsageAverage", AVG, split="clustername")], width=50),
        metrics(f"{P}-vsan", "vSAN used % by datastore", NS, "PrivateClouds",
                [m(NS, "DiskUsedPercentage", AVG, split="dsname")], width=50),
        metrics(f"{P}-ds", "Datastore used and capacity", NS, "PrivateClouds",
                [m(NS, "UsedLatest", AVG, split="dsname"), m(NS, "CapacityLatest", AVG, split="dsname")], width=50),
    ], tab="capacity")


def cloud_tab():
    cloud = {
        "id": gid(f"{P}-param-Cloud"), "version": "KqlParameterItem/1.0", "name": "Cloud", "label": "Private cloud",
        "type": 5, "isRequired": False, "multiSelect": False,
        "query": Q_AVS + "\n| project id", "crossComponentResources": ["{Subscription}"],
        "typeSettings": {"additionalResourceOptions": ["value::1"], "showDefault": False},
        "defaultValue": "value::1", "queryType": 1, "resourceType": "microsoft.resourcegraph/resources",
        "description": "Clusters, add-ons, Global Reach, NSX and run commands are read from Azure Resource Manager "
                       "for one private cloud at a time.",
    }
    items = [
        text(f"{P}-config-h", "### Configuration"),
        arg(f"{P}-config", "Endpoints, network and resilience", CONFIG_Q,
            formatters=[url("vCenter"), url("NsxManager"), url("HcxManager"),
                        status_fmt("Internet", good=["Disabled"], warn=["Enabled"]),
                        status_fmt("Encryption", good=["Enabled"], neutral=["Disabled", ""])],
            labels={"NsxManager": "NSX Manager", "HcxManager": "HCX Cloud Manager", "NetworkBlock": "Network block",
                    "ExtendedBlocks": "Extended network blocks", "DnsZoneType": "DNS zone type",
                    "SecondaryZone": "Secondary zone", "Encryption": "Customer-managed keys"}),
        arm(f"{P}-clusters", "Clusters", "{Cloud}/clusters", API, [
            ("Cluster", "$.name", None), ("Host type", "$.sku.name", None), ("Hosts", "$.properties.clusterSize", None),
            ("Provisioning", "$.properties.provisioningState", None)],
            formatters=[PROVISIONING], width=50, no_data="No clusters returned."),
        arm(f"{P}-addons", "Add-ons (HCX, SRM, vSphere Replication, Arc)", "{Cloud}/addons", API, [
            ("Add-on", "$.properties.addonType", None), ("Name", "$.name", None),
            ("Provisioning", "$.properties.provisioningState", None)],
            formatters=[PROVISIONING], width=50, no_data="No add-ons."),
        text(f"{P}-net-h", "### Connectivity"),
        arg(f"{P}-hub", "ExpressRoute connections that use this private cloud's circuit", CLOUD_CONNECTIONS_Q,
            formatters=[resource_link("Gateway"), STATE], labels={"RoutingWeight": "Routing weight"}),
        arm(f"{P}-global-reach", "Global Reach connections (to on-premises or another private cloud)",
            "{Cloud}/globalReachConnections", API, [
                ("Name", "$.name", None), ("State", "$.properties.circuitConnectionStatus", None),
                ("Peer circuit", "$.properties.peerExpressRouteCircuit", None),
                ("Address prefix", "$.properties.addressPrefix", None),
                ("Provisioning", "$.properties.provisioningState", None)],
            formatters=[STATE, PROVISIONING], no_data="No Global Reach connections."),
        arm(f"{P}-segments", "NSX segments", "{Cloud}/workloadNetworks/default/segments", API, [
            ("Segment", "$.properties.displayName", None), ("Gateway address", "$.properties.subnet.gatewayAddress", None),
            ("Connected gateway", "$.properties.connectedGateway", None), ("Status", "$.properties.status", None),
            ("Provisioning", "$.properties.provisioningState", None)],
            formatters=[status_fmt("Status", good=["SUCCESS"], bad=["FAILURE"]), PROVISIONING], width=60,
            no_data="No NSX segments, or they were created in NSX Manager rather than through Azure."),
        arm(f"{P}-dns-zones", "DNS forwarder zones", "{Cloud}/workloadNetworks/default/dnsZones", API, [
            ("Zone", "$.properties.displayName", None), ("Domains", "$.properties.domain", None),
            ("DNS servers", "$.properties.dnsServerIps", None), ("Source IP", "$.properties.sourceIp", None),
            ("Provisioning", "$.properties.provisioningState", None)],
            formatters=[PROVISIONING], width=40, no_data="No DNS forwarder zones."),
        text(f"{P}-net-note", "The private cloud's ExpressRoute circuit is managed by Microsoft. It reaches Azure "
             "through a connection from a hub's ExpressRoute gateway, using an authorisation key, and reaches "
             "on-premises through Global Reach. The Platform health workbook's ExpressRoute and Throughput tabs "
             "chart the gateway. Segments and DNS zones made in NSX Manager rather than through Azure do not "
             "appear here.", "info"),
        text(f"{P}-ops-h", "### Operations"),
        arm(f"{P}-run-commands", "Run command history", "{Cloud}/scriptExecutions", API, [
            ("Run", "$.name", None), ("Command", "$.properties.scriptCmdletId", None),
            ("State", "$.properties.provisioningState", None),
            ("Submitted", "$.properties.submittedAt", "datetime"), ("Finished", "$.properties.finishedAt", "datetime"),
            ("Failure", "$.properties.failureReason", None)],
            formatters=[status_fmt("State", good=["Succeeded"], warn=["Running", "Pending", "Cancelling", "Cancelled"],
                                   bad=["Failed"])],
            sort_desc="Submitted", no_data="No run commands have been run."),
        arm(f"{P}-diag", "Diagnostic settings", "{Cloud}/providers/Microsoft.Insights/diagnosticSettings",
            "2021-05-01-preview", [
                ("Setting", "$.name", None), ("Workspace", "$.properties.workspaceId", None),
                ("Storage account", "$.properties.storageAccountId", None),
                ("Event hub", "$.properties.eventHubAuthorizationRuleId", None),
                ("Logs", "$.properties.logs[0].enabled", None), ("Metrics", "$.properties.metrics[0].enabled", None)],
            no_data="No diagnostic settings: VMware syslog is not being collected for this private cloud."),
        arg(f"{P}-changes", "Changes to the private cloud (time range, up to 14 days)", CHANGES_Q,
            formatters=[resource_link("Resource"), status_fmt("ChangeType", good=["Create"], warn=["Update"],
                                                              bad=["Delete"])],
            labels={"ChangeType": "Change", "ChangedBy": "Changed by"},
            no_data="No changes in the time range."),
    ]
    return group(f"{P}-tab-cloud", [params(f"{P}-cloud-params", [cloud])] + [when_set(i, "Cloud") for i in items],
                 tab="cloud")


def logs_tab():
    return group(f"{P}-tab-logs", [
        text(f"{P}-la-hint", "Select a **Log Analytics workspace** at the top. The logs come from each private "
             "cloud's diagnostic setting (category *VMware Syslog*, table `AVSSyslog`), which carries vCenter, ESXi, "
             "vSAN and NSX syslog.", "info", visible_when=WORKSPACE_UNSET),
        la(f"{P}-la-sending", "Private clouds by last record in the workspace", SENDING_Q,
           formatters=[resource_link("ResourceId"), status_fmt("Status", good=["Logging"], warn=["Stale"],
                                                               bad=["No logs"])],
           labels={"ResourceId": "Private cloud", "LastRecord": "Last record"}, no_data="No private clouds."),
        la(f"{P}-la-levels", "Syslog records by level", LEVELS_Q, vis="timechart", width=50,
           no_data="No VMware syslog in the time range."),
        la(f"{P}-la-sources", "Errors and warnings by source", SOURCES_Q, width=50,
           formatters=[status_fmt("Level", warn=["Warning"], bad=["Error"])], labels={"LastSeen": "Last seen"},
           no_data="No errors or warnings in the time range."),
        la(f"{P}-la-alarms", "vCenter alarms raised (time range)", ALARMS_Q,
           formatters=[status_fmt("Now", good=["Green"], warn=["Yellow"], bad=["Red"], neutral=["Gray"])],
           labels={"Now": "Latest state", "Raised": "Times raised", "LastChange": "Last change"},
           no_data="No vCenter alarms turned yellow or red in the time range."),
        la(f"{P}-la-patterns", "Most frequent error messages", PATTERNS_Q, labels={"LastSeen": "Last seen"},
           no_data="No errors in the time range."),
        la(f"{P}-la-dfw", "NSX firewall: dropped and rejected flows", DFW_Q,
           labels={"SourceIp": "Source", "DestinationIp": "Destination", "LastSeen": "Last seen"},
           no_data="No dropped flows logged. NSX only logs flows for rules that have logging turned on."),
        la(f"{P}-la-activity", "Azure operations on private clouds (activity log)", ACTIVITY_Q,
           formatters=[status_fmt("Status", good=["Succeeded", "Success"], warn=["Started", "Accepted"],
                                  bad=["Failed", "Failure"])],
           labels={"PrivateCloud": "Private cloud", "LastSeen": "Last seen"},
           no_data="No Azure operations on private clouds in the time range (or the activity log is not sent to "
                   "this workspace)."),
    ], tab="logs")


def workbook():
    return notebook([
        text(f"{P}-header", "# Azure VMware Solution\n"
             "Are the private clouds healthy, do they have room to grow, are they connected and monitored, and what "
             "are vCenter, ESXi and NSX reporting?"),
        global_params(),
        tabs(),
        overview_tab(),
        capacity_tab(),
        cloud_tab(),
        logs_tab(),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
