"""Generates the Enterprise Scale (ALZ) platform health workbook.

Run:  python src/build_workbook.py
Out:  workbook/alz-platform-health.workbook.json

The workbook JSON is verbose and repetitive (GUIDs, threshold formatters,
metric definitions), so it is built from small helpers here. Edit this file,
re-run it, and commit both the script and the generated JSON.
"""

import json
import pathlib
import uuid

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "alz-platform-health.workbook.json"

# Stable GUIDs so regenerating the workbook produces a minimal diff.
_NS = uuid.UUID("6f1c2a0e-6d5e-4f0e-9c8a-2b1d4e7f9a10")


def gid(key):
    return str(uuid.uuid5(_NS, key))


DAY_MS = 86400000

# Aggregation enum used by workbook metrics items.
SUM, MIN, MAX, AVG, COUNT = 1, 2, 3, 4, 7


# ---------------------------------------------------------------------------
# Grid formatters
# ---------------------------------------------------------------------------

def _icons(grid):
    return {"thresholdsOptions": "icons", "thresholdsGrid": grid}


def _t(op, value, rep):
    return {"operator": op, "thresholdValue": value, "representation": rep, "text": "{0}{1}"}


def status_fmt(col, good=(), warn=(), bad=(), neutral=()):
    """Icon formatter for string status columns."""
    grid = [_t("==", v, "success") for v in good]
    grid += [_t("==", v, "2") for v in warn]
    grid += [_t("==", v, "4") for v in bad]
    grid += [_t("==", v, "unknown") for v in neutral]
    grid.append(_t("Default", None, "Blank"))
    return {"columnMatch": col, "formatter": 18, "formatOptions": _icons(grid)}


def health_fmt(col="Health"):
    return status_fmt(col, good=["Available"], warn=["Degraded"], bad=["Unavailable"], neutral=["Unknown"])


def low_is_good(col, warn, crit):
    """Icon formatter for numeric columns where higher values are worse (CPU, SNAT...)."""
    return {"columnMatch": col, "formatter": 18, "formatOptions": _icons([
        _t(">=", str(crit), "4"),
        _t(">=", str(warn), "2"),
        _t("Default", None, "success"),
    ])}


def high_is_good(col, warn, crit):
    """Icon formatter for numeric columns where lower values are worse (availability...)."""
    return {"columnMatch": col, "formatter": 18, "formatOptions": _icons([
        _t("<", str(crit), "4"),
        _t("<", str(warn), "2"),
        _t("Default", None, "success"),
    ])}


def resource_link(col="id"):
    return {"columnMatch": col, "formatter": 13, "formatOptions": {"linkTarget": "Resource", "showIcon": True}}


def hidden(col):
    return {"columnMatch": col, "formatter": 5}


PROVISIONING = status_fmt("Provisioning", good=["Succeeded"], warn=["Updating", "Creating", "Deleting"], bad=["Failed", "Canceled"])


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

def text(name, md, style=None):
    content = {"json": md}
    if style:
        content["style"] = style
    return {"type": 1, "content": content, "name": name}


def _query(name, title, query, *, query_type, resource_type, resources, vis="table",
           formatters=None, labels=None, tiles=None, chart=None, width=None, size=0,
           no_data=None, group_by=None, visible_when=None, time=False):
    content = {
        "version": "KqlItem/1.0",
        "query": query.strip(),
        "size": size,
        "title": title,
        "queryType": query_type,
        "resourceType": resource_type,
        "crossComponentResources": resources,
        "visualization": vis,
    }
    if time:
        content["timeContextFromParameter"] = "TimeRange"
        content["timeContext"] = {"durationMs": DAY_MS}
    if no_data:
        content["noDataMessage"] = no_data
    if vis == "table":
        content["showExportToExcel"] = True
        grid = {"formatters": formatters or [], "filter": True}
        if labels:
            grid["labelSettings"] = [{"columnId": k, "label": v} for k, v in labels.items()]
        if group_by:
            grid["hierarchySettings"] = {"treeType": 1, "groupBy": [group_by], "expandTopLevel": False}
        content["gridSettings"] = grid
    if tiles:
        content["tileSettings"] = tiles
    if chart:
        content["chartSettings"] = chart
    item = {"type": 3, "content": content, "name": name}
    if width:
        item["customWidth"] = str(width)
    if visible_when:
        item["conditionalVisibility"] = visible_when
    return item


def arg(name, title, query, **kw):
    """Azure Resource Graph query scoped to the selected subscriptions."""
    return _query(name, title, query, query_type=1, resource_type="microsoft.resourcegraph/resources",
                  resources=["{Subscription}"], **kw)


WORKSPACE_SET = {"parameterName": "Workspace", "comparison": "isNotEqualTo", "value": ""}
WORKSPACE_UNSET = {"parameterName": "Workspace", "comparison": "isEqualTo", "value": ""}


def la(name, title, query, **kw):
    """Log Analytics query against the selected workspace(s); hidden until one is picked."""
    kw.setdefault("visible_when", WORKSPACE_SET)
    return _query(name, title, query, query_type=0, resource_type="microsoft.operationalinsights/workspaces",
                  resources=["{Workspace}"], time=True, **kw)


def m(namespace, metric, agg, split=None, limit=10):
    spec = {"namespace": namespace, "metric": f"{namespace}--{metric}", "aggregation": agg}
    if split:
        spec.update({"splitBy": split, "splitBySortOrder": -1, "splitByLimit": limit})
    return spec


def metrics(name, title, resource_type, param, specs, *, grid=False, formatters=None, labels=None,
            width=None, size=0):
    content = {
        "chartId": "workbook" + gid(name),
        "version": "MetricsItem/2.0",
        "size": size,
        "chartType": 0 if grid else 2,
        "resourceType": resource_type,
        "metricScope": 0,
        "resourceParameter": param,
        "resourceIds": ["{" + param + "}"],
        "timeContextFromParameter": "TimeRange",
        "timeContext": {"durationMs": DAY_MS},
        "metrics": specs,
        "title": title,
        "showOpenInMe": True,
    }
    if grid:
        content["gridFormatType"] = 1
        content["visualization"] = "table"
        timelines = [hidden(f"{s['metric']} Timeline") for s in specs]
        content["gridSettings"] = {
            "formatters": [hidden("Subscription"), resource_link("Name")] + timelines + (formatters or []),
            "labelSettings": [{"columnId": k, "label": v} for k, v in (labels or {}).items()],
            "filter": True,
        }
    item = {"type": 10, "content": content, "name": name}
    if width:
        item["customWidth"] = str(width)
    return item


def metric_grid(name, title, resource_type, param, cols, **kw):
    """cols: list of (metric, aggregation, label, formatter-or-None)."""
    specs = [m(resource_type, metric, agg) for metric, agg, _, _ in cols]
    labels = {f"{resource_type}--{metric}": label for metric, _, label, _ in cols}
    fmts = []
    for metric, _, _, fmt in cols:
        if fmt:
            kind, warn, crit = fmt
            col = f"{resource_type}--{metric}$"
            fmts.append(low_is_good(col, warn, crit) if kind == "low" else high_is_good(col, warn, crit))
    return metrics(name, title, resource_type, param, specs, grid=True, formatters=fmts, labels=labels, **kw)


def resource_param(name, label, arg_query, hidden_when_locked=False):
    """Multi-select resource picker populated from ARG, defaulting to all matches."""
    p = {
        "id": gid("param-" + name),
        "version": "KqlParameterItem/1.0",
        "name": name,
        "label": label,
        "type": 5,
        "isRequired": False,
        "multiSelect": True,
        "quote": "'",
        "delimiter": ",",
        "query": arg_query.strip() + "\n| project id",
        "crossComponentResources": ["{Subscription}"],
        "typeSettings": {"additionalResourceOptions": ["value::all"], "showDefault": False},
        "defaultValue": "value::all",
        "value": ["value::all"],
        "queryType": 1,
        "resourceType": "microsoft.resourcegraph/resources",
    }
    if hidden_when_locked:
        p["isHiddenWhenLocked"] = True
    return p


def params(name, plist):
    return {"type": 9, "content": {"version": "KqlParameterItem/1.0", "parameters": plist, "style": "pills",
                                    "queryType": 1, "resourceType": "microsoft.resourcegraph/resources"},
            "name": name}


def group(name, items, tab=None):
    g = {"type": 12, "content": {"version": "NotebookGroup/1.0", "groupType": "editable", "items": items}, "name": name}
    if tab:
        g["conditionalVisibility"] = {"parameterName": "selectedTab", "comparison": "isEqualTo", "value": tab}
    return g


# ---------------------------------------------------------------------------
# Shared ARG fragments
# ---------------------------------------------------------------------------

Q_FIREWALLS = "resources\n| where type =~ 'microsoft.network/azurefirewalls'"
Q_CIRCUITS = "resources\n| where type =~ 'microsoft.network/expressroutecircuits'"
Q_ER_GATEWAYS = ("resources\n| where type =~ 'microsoft.network/virtualnetworkgateways'"
                 " and tostring(properties.gatewayType) =~ 'ExpressRoute'")
Q_VPN_GATEWAYS = ("resources\n| where type =~ 'microsoft.network/virtualnetworkgateways'"
                  " and tostring(properties.gatewayType) =~ 'Vpn'")
Q_VWAN_VPN_GATEWAYS = "resources\n| where type =~ 'microsoft.network/vpngateways'"
Q_AVS = "resources\n| where type =~ 'microsoft.avs/privateclouds'"
Q_STORAGE = "resources\n| where type =~ 'microsoft.storage/storageaccounts'"
Q_AGENT_VMSS = ("resources\n| where type =~ 'microsoft.compute/virtualmachinescalesets'"
                "\n| where name matches regex @'{BuildAgentPattern}'")
Q_AGENT_VMS = ("resources\n| where type =~ 'microsoft.compute/virtualmachines'"
               "\n| where name matches regex @'{BuildAgentPattern}'")

PLATFORM_TYPES = [
    "microsoft.network/azurefirewalls",
    "microsoft.network/expressroutecircuits",
    "microsoft.network/expressroutegateways",
    "microsoft.network/virtualnetworkgateways",
    "microsoft.network/vpngateways",
    "microsoft.network/p2svpngateways",
    "microsoft.network/connections",
    "microsoft.avs/privateclouds",
    "microsoft.desktopvirtualization/hostpools",
    "microsoft.storage/storageaccounts",
    "microsoft.devopsinfrastructure/pools",
    "microsoft.compute/virtualmachinescalesets",
    "microsoft.compute/virtualmachines",
]
TYPE_LIST = ", ".join(f"'{t}'" for t in PLATFORM_TYPES)

# Every platform resource we care about, tagged with a Service, joined to Resource Health.
Q_INVENTORY_HEALTH = f"""
resources
| where type in~ ({TYPE_LIST})
| where type !in~ ('microsoft.compute/virtualmachinescalesets', 'microsoft.compute/virtualmachines') or name matches regex @'{{BuildAgentPattern}}'
| extend gatewayType = tostring(properties.gatewayType), connectionType = tostring(properties.connectionType)
| extend Service = case(
    type =~ 'microsoft.network/azurefirewalls', 'Azure Firewall',
    type in~ ('microsoft.network/expressroutecircuits', 'microsoft.network/expressroutegateways'), 'ExpressRoute',
    type =~ 'microsoft.network/virtualnetworkgateways' and gatewayType =~ 'ExpressRoute', 'ExpressRoute',
    type =~ 'microsoft.network/connections' and connectionType =~ 'ExpressRoute', 'ExpressRoute',
    type in~ ('microsoft.network/virtualnetworkgateways', 'microsoft.network/vpngateways', 'microsoft.network/p2svpngateways', 'microsoft.network/connections'), 'VPN Gateway',
    type =~ 'microsoft.avs/privateclouds', 'Azure VMware Solution',
    type =~ 'microsoft.desktopvirtualization/hostpools', 'Azure Virtual Desktop',
    type =~ 'microsoft.storage/storageaccounts', 'Storage',
    'Build Agents')
| extend provisioning = tostring(properties.provisioningState),
    powerState = tostring(properties.extended.instanceView.powerState.code)
| extend ConfigHealth = case(
    provisioning =~ 'Failed', 'Unavailable',
    tostring(properties.circuitProvisioningState) =~ 'Disabled', 'Unavailable',
    tostring(properties.statusOfPrimary) =~ 'unavailable', 'Unavailable',
    powerState =~ 'PowerState/stopped', 'Degraded',
    type =~ 'microsoft.network/expressroutecircuits' and tostring(properties.serviceProviderProvisioningState) !~ 'Provisioned', 'Degraded',
    provisioning in~ ('Updating', 'Deleting', 'Canceled'), 'Degraded',
    provisioning =~ 'Succeeded' or isempty(provisioning), 'Available',
    'Unknown')
| project id = tolower(id), Service, Type = type, ResourceGroup = resourceGroup, SubscriptionId = subscriptionId, Location = location, ConfigHealth
| join kind=leftouter (
    healthresources
    | where type =~ 'microsoft.resourcehealth/availabilitystatuses'
    | project id = tostring(split(tolower(id), '/providers/microsoft.resourcehealth/')[0]),
        Health = tostring(properties.availabilityState),
        Reason = tostring(properties.reasonType),
        Detail = tostring(properties.summary),
        Since = todatetime(properties.occurredTime)
  ) on id
| project-away id1
| extend Signal = iff(isempty(Health), 'Config state', 'Resource Health')
| extend Health = iff(isempty(Health), ConfigHealth, Health)
"""


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

TABS = [
    ("overview", "Overview"),
    ("firewall", "Azure Firewall"),
    ("expressroute", "ExpressRoute"),
    ("vpn", "VPN Gateways"),
    ("buildagents", "Build Agents"),
    ("avs", "Azure VMware Solution"),
    ("avd", "Azure Virtual Desktop"),
    ("storage", "Storage"),
    ("throughput", "Throughput"),
]


def overview_tab():
    summary_q = Q_INVENTORY_HEALTH + """
| summarize Total = count(),
    Healthy = countif(Health == 'Available'),
    Degraded = countif(Health == 'Degraded'),
    Unavailable = countif(Health == 'Unavailable'),
    Unknown = countif(Health == 'Unknown') by Service
| extend Status = case(Unavailable > 0, 'Unavailable', Degraded > 0, 'Degraded', Healthy == Total, 'Available', 'Unknown')
| extend Summary = strcat(Healthy, ' healthy · ', Degraded + Unavailable, ' issues · ', Unknown, ' unknown')
| order by Service asc
"""
    tiles = {
        "titleContent": {"columnMatch": "Service", "formatter": 1},
        "leftContent": health_fmt("Status"),
        "rightContent": {"columnMatch": "Total", "formatter": 12, "formatOptions": {"palette": "none"},
                         "numberFormat": {"unit": 17, "options": {"style": "decimal", "maximumFractionDigits": 0}}},
        "secondaryContent": {"columnMatch": "Summary", "formatter": 1},
        "showBorder": True,
    }
    unhealthy_q = Q_INVENTORY_HEALTH + """
| where Health != 'Available'
| project id, Service, Health, Signal, Reason, Detail, Since, ResourceGroup, Location
| order by case(Health == 'Unavailable', 0, Health == 'Degraded', 1, 2) asc, Service asc
"""
    all_q = Q_INVENTORY_HEALTH + """
| project id, Service, Health, Signal, Reason, Since, Type, ResourceGroup, Location
| order by Service asc
"""
    alerts_q = f"""
alertsmanagementresources
| where type =~ 'microsoft.alertsmanagement/alerts'
| extend e = properties.essentials
| where tostring(e.monitorCondition) =~ 'Fired' and tostring(e.alertState) !~ 'Closed'
| where tolower(tostring(e.targetResourceType)) in~ ({TYPE_LIST})
| project Severity = tostring(e.severity), Alert = name, Target = tostring(e.targetResource),
    State = tostring(e.alertState), Fired = todatetime(e.startDateTime), SubscriptionId = subscriptionId
| order by Severity asc, Fired desc
"""
    service_health_q = """
servicehealthresources
| where type =~ 'microsoft.resourcehealth/events'
| where tostring(properties.Status) =~ 'Active'
| project Title = tostring(properties.Title), EventType = tostring(properties.EventType),
    Level = tostring(properties.Level), TrackingId = tostring(properties.TrackingId),
    ImpactStart = todatetime(tolong(properties.ImpactStartTime)), SubscriptionId = subscriptionId
| summarize Subscriptions = dcount(SubscriptionId) by Title, EventType, Level, TrackingId, ImpactStart
| order by ImpactStart desc
"""
    sev = status_fmt("Severity")
    sev["formatOptions"]["thresholdsGrid"] = [_t("==", f"Sev{i}", f"Sev{i}") for i in range(5)] + [_t("Default", None, "Blank")]
    return group("tab-overview", [
        text("overview-intro",
             "Status comes from **Azure Resource Health** where available; otherwise it falls back to the "
             "resource's configuration state (provisioning, circuit/provider state, power state) — see the *Signal* column. "
             "Use each service tab for metric-based health (e.g. Firewall health %, BGP availability).", "info"),
        arg("overview-tiles", "Platform service health", summary_q, vis="tiles", tiles=tiles,
            no_data="No platform resources found in the selected subscriptions."),
        arg("overview-unhealthy", "Resources needing attention", unhealthy_q,
            formatters=[resource_link(), health_fmt()], labels={"id": "Resource"},
            no_data="All platform resources report Available.", width=60),
        arg("overview-alerts", "Fired alerts on platform resources", alerts_q,
            formatters=[sev, resource_link("Target")], no_data="No fired alerts.", width=40),
        arg("overview-servicehealth", "Active Azure Service Health events", service_health_q,
            formatters=[status_fmt("EventType", warn=["PlannedMaintenance", "HealthAdvisory"], bad=["ServiceIssue"])],
            no_data="No active Service Health events."),
        arg("overview-all", "All platform resources", all_q, group_by="Service",
            formatters=[resource_link(), health_fmt(), hidden("Type")], labels={"id": "Resource"}),
    ], tab="overview")


def firewall_tab():
    ns = "microsoft.network/azurefirewalls"
    inventory_q = Q_FIREWALLS + """
| project id,
    Tier = tostring(properties.sku.tier),
    Deployment = iff(isnotempty(tostring(properties.virtualHub.id)), 'vWAN hub', 'Hub VNet'),
    Policy = tostring(split(tostring(properties.firewallPolicy.id), '/')[8]),
    PrivateIP = coalesce(tostring(properties.ipConfigurations[0].properties.privateIPAddress), tostring(properties.hubIPAddresses.privateIPAddress)),
    Zones = tostring(zones),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup, Location = location
"""
    denied_q = """
union isfuzzy=true
    (AZFWNetworkRule | where TimeGenerated {TimeRange} | where Action == 'Deny'
        | project TimeGenerated, Rule = 'Network', SourceIp, Destination = strcat(DestinationIp, ':', DestinationPort), Protocol),
    (AZFWApplicationRule | where TimeGenerated {TimeRange} | where Action == 'Deny'
        | project TimeGenerated, Rule = 'Application', SourceIp, Destination = strcat(Fqdn, ':', DestinationPort), Protocol)
| summarize Hits = count(), LastSeen = max(TimeGenerated) by Rule, SourceIp, Destination, Protocol
| top 50 by Hits desc
"""
    return group("tab-firewall", [
        params("firewall-params", [resource_param("Firewalls", "Firewalls", Q_FIREWALLS)]),
        arg("firewall-inventory", "Firewalls", inventory_q, formatters=[resource_link(), PROVISIONING],
            labels={"id": "Firewall"}, no_data="No Azure Firewalls found."),
        metric_grid("firewall-kpis", "Key metrics (over time range)", ns, "Firewalls", [
            ("FirewallHealth", AVG, "Health %", ("high", 99, 90)),
            ("SNATPortUtilization", MAX, "Max SNAT %", ("low", 70, 90)),
            ("Throughput", AVG, "Avg throughput", None),
            ("FirewallLatencyPng", AVG, "Latency probe (ms)", ("low", 10, 20)),
            ("DataProcessed", SUM, "Data processed", None),
        ]),
        metrics("firewall-health", "Health state %", ns, "Firewalls", [m(ns, "FirewallHealth", AVG)], width=50),
        metrics("firewall-throughput", "Throughput", ns, "Firewalls", [m(ns, "Throughput", AVG)], width=50),
        metrics("firewall-snat", "SNAT port utilisation % (max)", ns, "Firewalls", [m(ns, "SNATPortUtilization", MAX)], width=50),
        metrics("firewall-latency", "Latency probe (ms)", ns, "Firewalls", [m(ns, "FirewallLatencyPng", AVG)], width=50),
        metrics("firewall-rulehits", "Rule hits", ns, "Firewalls",
                [m(ns, "NetworkRuleHit", SUM), m(ns, "ApplicationRuleHit", SUM)]),
        text("firewall-logs-hint", "Select a **Log Analytics workspace** at the top to see denied traffic "
             "(requires resource-specific firewall logs: `AZFWNetworkRule`, `AZFWApplicationRule`).", "info"),
        la("firewall-denied", "Top denied flows", denied_q, no_data="No denied flows (or structured firewall logs are not enabled)."),
    ], tab="firewall")


def expressroute_tab():
    cns = "microsoft.network/expressroutecircuits"
    gns = "microsoft.network/virtualnetworkgateways"
    circuits_q = Q_CIRCUITS + """
| project id,
    CircuitState = tostring(properties.circuitProvisioningState),
    ProviderState = tostring(properties.serviceProviderProvisioningState),
    Provider = tostring(properties.serviceProviderProperties.serviceProviderName),
    PeeringLocation = coalesce(tostring(properties.serviceProviderProperties.peeringLocation), tostring(properties.peeringLocation)),
    BandwidthMbps = coalesce(tolong(properties.serviceProviderProperties.bandwidthInMbps), tolong(properties.bandwidthInGbps) * 1000),
    Sku = strcat(tostring(sku.tier), ' / ', tostring(sku.family)),
    Peerings = array_length(properties.peerings),
    GlobalReach = tostring(properties.globalReachEnabled),
    ResourceGroup = resourceGroup, Location = location
"""
    gateways_q = """
resources
| where (type =~ 'microsoft.network/virtualnetworkgateways' and tostring(properties.gatewayType) =~ 'ExpressRoute')
    or type =~ 'microsoft.network/expressroutegateways'
| extend vwan = type =~ 'microsoft.network/expressroutegateways'
| project id,
    Deployment = iff(vwan, 'vWAN hub', 'Hub VNet'),
    Sku = iff(vwan, strcat(tostring(properties.autoScaleConfiguration.bounds.min), ' scale unit(s)'), tostring(properties.sku.name)),
    AttachedTo = iff(vwan, tostring(split(tostring(properties.virtualHub.id), '/')[8]),
        tostring(split(tostring(properties.ipConfigurations[0].properties.subnet.id), '/')[8])),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup, Location = location
"""
    connections_q = """
resources
| where type =~ 'microsoft.network/connections' and tostring(properties.connectionType) =~ 'ExpressRoute'
| project id,
    Gateway = tostring(split(tostring(properties.virtualNetworkGateway1.id), '/')[8]),
    Circuit = tostring(split(tostring(properties.peer.id), '/')[8]),
    RoutingWeight = toint(properties.routingWeight),
    FastPath = tostring(properties.expressRouteGatewayBypass),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup
"""
    return group("tab-expressroute", [
        params("er-params", [
            resource_param("Circuits", "Circuits", Q_CIRCUITS),
            resource_param("ErGateways", "ER gateways", Q_ER_GATEWAYS),
        ]),
        arg("er-circuits", "Circuits", circuits_q, formatters=[
            resource_link(),
            status_fmt("CircuitState", good=["Enabled"], bad=["Disabled"]),
            status_fmt("ProviderState", good=["Provisioned"], warn=["Provisioning", "NotProvisioned"], bad=["Deprovisioning"]),
        ], labels={"id": "Circuit"}, no_data="No ExpressRoute circuits found."),
        metric_grid("er-circuit-kpis", "Circuit key metrics (over time range)", cns, "Circuits", [
            ("BgpAvailability", AVG, "BGP availability %", ("high", 99.9, 90)),
            ("ArpAvailability", AVG, "ARP availability %", ("high", 99.9, 90)),
            ("BitsInPerSecond", AVG, "Avg bits in/s", None),
            ("BitsOutPerSecond", AVG, "Avg bits out/s", None),
        ]),
        metrics("er-bgp", "BGP availability % by peering", cns, "Circuits",
                [m(cns, "BgpAvailability", AVG, split="PeeringType")], width=50),
        metrics("er-arp", "ARP availability % by peering", cns, "Circuits",
                [m(cns, "ArpAvailability", AVG, split="PeeringType")], width=50),
        metrics("er-bits", "Circuit throughput (bits/s)", cns, "Circuits",
                [m(cns, "BitsInPerSecond", AVG), m(cns, "BitsOutPerSecond", AVG)]),
        arg("er-gateways", "ExpressRoute gateways", gateways_q, formatters=[resource_link(), PROVISIONING],
            labels={"id": "Gateway"}, no_data="No ExpressRoute gateways found.", width=50),
        arg("er-connections", "Gateway connections", connections_q, formatters=[resource_link(), PROVISIONING],
            labels={"id": "Connection"}, no_data="No ExpressRoute connections found.", width=50),
        metrics("er-gw-cpu", "Gateway CPU %", gns, "ErGateways", [m(gns, "ExpressRouteGatewayCpuUtilization", AVG)], width=50),
        metrics("er-gw-pps", "Gateway packets/s", gns, "ErGateways", [m(gns, "ExpressRouteGatewayPacketsPerSecond", AVG)], width=50),
        metrics("er-gw-routes", "Routes learned from peer", gns, "ErGateways",
                [m(gns, "ExpressRouteGatewayCountOfRoutesLearnedFromPeer", MAX)], width=50),
        metrics("er-gw-conn-bits", "Connection bits in/s by connection", gns, "ErGateways",
                [m(gns, "ErGatewayConnectionBitsInPerSecond", AVG, split="ConnectionName")], width=50),
    ], tab="expressroute")


def vpn_tab():
    ns = "microsoft.network/virtualnetworkgateways"
    vns = "microsoft.network/vpngateways"
    gateways_q = """
resources
| where (type =~ 'microsoft.network/virtualnetworkgateways' and tostring(properties.gatewayType) =~ 'Vpn')
    or type in~ ('microsoft.network/vpngateways', 'microsoft.network/p2svpngateways')
| extend vwan = type !~ 'microsoft.network/virtualnetworkgateways'
| project id,
    Deployment = iff(vwan, 'vWAN hub', 'Hub VNet'),
    Sku = iff(vwan, strcat(tostring(properties.vpnGatewayScaleUnit), ' scale unit(s)'), tostring(properties.sku.name)),
    Generation = tostring(properties.vpnGatewayGeneration),
    ActiveActive = tostring(properties.activeActive),
    Bgp = tostring(properties.enableBgp),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup, Location = location
"""
    connections_q = """
resources
| where type =~ 'microsoft.network/connections' and tostring(properties.connectionType) in~ ('IPsec', 'Vnet2Vnet')
| project id,
    Gateway = tostring(split(tostring(properties.virtualNetworkGateway1.id), '/')[8]),
    Remote = coalesce(tostring(split(tostring(properties.localNetworkGateway2.id), '/')[8]),
        tostring(split(tostring(properties.virtualNetworkGateway2.id), '/')[8])),
    Type = tostring(properties.connectionType),
    Protocol = tostring(properties.connectionProtocol),
    Bgp = tostring(properties.enableBgp),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup
"""
    tunnel_q = """
AzureDiagnostics
| where TimeGenerated {TimeRange}
| where Category == 'TunnelDiagnosticLog'
| project TimeGenerated, Gateway = Resource,
    RemoteIP = column_ifexists('remoteIP_s', ''),
    Status = column_ifexists('status_s', ''),
    Reason = column_ifexists('stateChangeReason_s', '')
| order by TimeGenerated desc
| take 200
"""
    return group("tab-vpn", [
        params("vpn-params", [
            resource_param("VpnGateways", "VPN gateways", Q_VPN_GATEWAYS),
            resource_param("VwanVpnGateways", "vWAN VPN gateways", Q_VWAN_VPN_GATEWAYS),
        ]),
        arg("vpn-gateways", "VPN gateways", gateways_q, formatters=[resource_link(), PROVISIONING],
            labels={"id": "Gateway"}, no_data="No VPN gateways found."),
        metric_grid("vpn-kpis", "Gateway key metrics (over time range)", ns, "VpnGateways", [
            ("AverageBandwidth", AVG, "Avg S2S bandwidth", None),
            ("TunnelAverageBandwidth", AVG, "Avg tunnel bandwidth", None),
            ("P2SConnectionCount", MAX, "Max P2S connections", None),
            ("TunnelIngressPacketDropCount", SUM, "Ingress drops", None),
            ("TunnelEgressPacketDropCount", SUM, "Egress drops", None),
        ]),
        metrics("vpn-tunnel-bw", "Tunnel bandwidth by connection", ns, "VpnGateways",
                [m(ns, "TunnelAverageBandwidth", AVG, split="ConnectionName")], width=50),
        metrics("vpn-bgp", "BGP peer status (1 = up) by peer", ns, "VpnGateways",
                [m(ns, "BgpPeerStatus", AVG, split="BgpPeerAddress")], width=50),
        metrics("vpn-drops", "Tunnel packet drops", ns, "VpnGateways",
                [m(ns, "TunnelIngressPacketDropCount", SUM), m(ns, "TunnelEgressPacketDropCount", SUM)], width=50),
        metrics("vpn-p2s", "P2S connections", ns, "VpnGateways", [m(ns, "P2SConnectionCount", MAX)], width=50),
        metrics("vwan-vpn-tunnel-bw", "vWAN VPN tunnel bandwidth", vns, "VwanVpnGateways",
                [m(vns, "TunnelAverageBandwidth", AVG)]),
        arg("vpn-connections", "Site-to-site / VNet-to-VNet connections", connections_q,
            formatters=[resource_link(), PROVISIONING], labels={"id": "Connection"},
            no_data="No VPN connections found."),
        la("vpn-tunnel-events", "Tunnel connect/disconnect events", tunnel_q,
           no_data="No tunnel events (or gateway diagnostic logs are not sent to this workspace)."),
    ], tab="vpn")


def buildagents_tab():
    vmss = "microsoft.compute/virtualmachinescalesets"
    vm = "microsoft.compute/virtualmachines"
    inventory_q = """
resources
| where type in~ ('microsoft.compute/virtualmachinescalesets', 'microsoft.compute/virtualmachines', 'microsoft.devopsinfrastructure/pools')
| where type =~ 'microsoft.devopsinfrastructure/pools' or name matches regex @'{BuildAgentPattern}'
| extend Kind = case(type =~ 'microsoft.devopsinfrastructure/pools', 'Managed DevOps Pool',
    type =~ 'microsoft.compute/virtualmachinescalesets', 'Scale set', 'Virtual machine')
| extend PowerState = iff(type =~ 'microsoft.compute/virtualmachines',
    tostring(split(tostring(properties.extended.instanceView.powerState.code), '/')[1]), '')
| project id, Kind, PowerState,
    Size = case(type =~ 'microsoft.compute/virtualmachines', tostring(properties.hardwareProfile.vmSize),
        type =~ 'microsoft.compute/virtualmachinescalesets', tostring(sku.name),
        tostring(properties.fabricProfile.sku.name)),
    Capacity = case(type =~ 'microsoft.compute/virtualmachinescalesets', tolong(sku.capacity),
        type =~ 'microsoft.devopsinfrastructure/pools', tolong(properties.maximumConcurrency), tolong(1)),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup, Location = location
| order by Kind asc
"""
    return group("tab-buildagents", [
        text("agents-intro",
             "Build agents are found by **name** using the *Build agent name pattern* parameter at the top "
             "(a regex applied to VM and scale set names). Managed DevOps Pools are always included.", "info"),
        params("agents-params", [
            resource_param("AgentScaleSets", "Agent scale sets", Q_AGENT_VMSS),
            resource_param("AgentVms", "Agent VMs", Q_AGENT_VMS),
        ]),
        arg("agents-inventory", "Build agent infrastructure", inventory_q, formatters=[
            resource_link(), PROVISIONING,
            status_fmt("PowerState", good=["running"], warn=["stopped", "starting", "stopping"], neutral=["deallocated", "deallocating"]),
        ], labels={"id": "Resource"}, no_data="No build agents matched the name pattern."),
        metric_grid("agents-vmss-kpis", "Scale set metrics (over time range)", vmss, "AgentScaleSets", [
            ("Percentage CPU", AVG, "Avg CPU %", ("low", 80, 95)),
            ("Available Memory Bytes", MIN, "Min available memory", None),
            ("Network In Total", SUM, "Network in", None),
            ("Network Out Total", SUM, "Network out", None),
        ]),
        metrics("agents-vmss-cpu", "Scale set CPU %", vmss, "AgentScaleSets", [m(vmss, "Percentage CPU", AVG)], width=50),
        metrics("agents-vmss-net", "Scale set network", vmss, "AgentScaleSets",
                [m(vmss, "Network In Total", SUM), m(vmss, "Network Out Total", SUM)], width=50),
        metrics("agents-vm-cpu", "Agent VM CPU %", vm, "AgentVms", [m(vm, "Percentage CPU", AVG)], width=50),
        metrics("agents-vm-mem", "Agent VM available memory", vm, "AgentVms", [m(vm, "Available Memory Bytes", MIN)], width=50),
    ], tab="buildagents")


def avs_tab():
    ns = "microsoft.avs/privateclouds"
    inventory_q = Q_AVS + """
| project id,
    Sku = tostring(sku.name),
    MgmtClusterHosts = toint(properties.managementCluster.clusterSize),
    NetworkBlock = tostring(properties.networkBlock),
    Internet = tostring(properties.internet),
    Availability = tostring(properties.availability.strategy),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup, Location = location
"""
    return group("tab-avs", [
        params("avs-params", [resource_param("PrivateClouds", "Private clouds", Q_AVS)]),
        arg("avs-inventory", "Private clouds", inventory_q, formatters=[resource_link(), PROVISIONING],
            labels={"id": "Private cloud"}, no_data="No AVS private clouds found."),
        text("avs-vsan-note", "AVS requires **25% vSAN slack space** to stay within SLA — keep datastore usage below 75%.", "warning"),
        metric_grid("avs-kpis", "Key metrics (over time range)", ns, "PrivateClouds", [
            ("EffectiveCpuAverage", AVG, "CPU %", ("low", 80, 90)),
            ("UsageAverage", AVG, "Memory %", ("low", 80, 90)),
            ("DiskUsedPercentage", MAX, "vSAN used % (max)", ("low", 70, 75)),
            ("UsedLatest", MAX, "Datastore used", None),
            ("CapacityLatest", MAX, "Datastore capacity", None),
        ]),
        metrics("avs-cpu", "CPU % by cluster", ns, "PrivateClouds",
                [m(ns, "EffectiveCpuAverage", AVG, split="clustername")], width=50),
        metrics("avs-mem", "Memory % by cluster", ns, "PrivateClouds",
                [m(ns, "UsageAverage", AVG, split="clustername")], width=50),
        metrics("avs-disk", "vSAN datastore used % by cluster", ns, "PrivateClouds",
                [m(ns, "DiskUsedPercentage", MAX, split="clustername")]),
    ], tab="avs")


def avd_tab():
    pools_q = """
resources
| where type =~ 'microsoft.desktopvirtualization/hostpools'
| project id,
    PoolType = tostring(properties.hostPoolType),
    LoadBalancing = tostring(properties.loadBalancerType),
    MaxSessions = toint(properties.maxSessionLimit),
    AppGroupType = tostring(properties.preferredAppGroupType),
    StartVmOnConnect = tostring(properties.startVMOnConnect),
    Validation = tostring(properties.validationEnvironment),
    ResourceGroup = resourceGroup, Location = location
"""
    latest_hosts = """
WVDAgentHealthStatus
| where TimeGenerated {TimeRange}
| summarize arg_max(TimeGenerated, *) by SessionHostName
| extend HostPool = tostring(split(_ResourceId, '/')[8])
| extend Status = iff(TimeGenerated < ago(30m), 'NoRecentHeartbeat', Status)
"""
    status_tiles_q = latest_hosts + "| summarize Hosts = count() by Status\n| order by Hosts desc"
    hosts_q = latest_hosts + """
| project SessionHost = SessionHostName, HostPool, Status, LastHeartbeat = TimeGenerated,
    ActiveSessions = column_ifexists('ActiveSessions', int(null)),
    InactiveSessions = column_ifexists('InactiveSessions', int(null)),
    AgentVersion = column_ifexists('AgentVersion', '')
| order by Status asc, SessionHost asc
"""
    sessions_q = """
WVDConnections
| where TimeGenerated {TimeRange}
| where State == 'Connected'
| summarize Sessions = dcount(CorrelationId), Users = dcount(UserName) by bin(TimeGenerated, {TimeRange:grain})
"""
    errors_q = """
WVDErrors
| where TimeGenerated {TimeRange}
| summarize Errors = count(), Users = dcount(UserName), LastSeen = max(TimeGenerated), Message = take_any(Message)
    by Source, CodeSymbolic, ServiceError
| top 25 by Errors desc
"""
    rtt_q = """
WVDConnectionNetworkData
| where TimeGenerated {TimeRange}
| summarize P50_RTT_ms = percentile(EstRoundTripTimeInMs, 50), P95_RTT_ms = percentile(EstRoundTripTimeInMs, 95)
    by bin(TimeGenerated, {TimeRange:grain})
"""
    host_status = status_fmt("Status", good=["Available"], warn=["Upgrading", "NeedsAssistance", "Shutdown"],
                             bad=["Unavailable", "NoRecentHeartbeat", "UpgradeFailed", "NoHeartbeat"])
    tiles = {
        "titleContent": {"columnMatch": "Status", "formatter": 1},
        "leftContent": host_status,
        "rightContent": {"columnMatch": "Hosts", "formatter": 12, "formatOptions": {"palette": "none"}},
        "showBorder": True,
    }
    return group("tab-avd", [
        arg("avd-pools", "Host pools", pools_q, formatters=[resource_link()], labels={"id": "Host pool"},
            no_data="No AVD host pools found."),
        text("avd-workspace-hint", "Select the **Log Analytics workspace** that receives AVD diagnostics to see "
             "session host health, sessions, errors and connection quality.", "info"),
        la("avd-host-tiles", "Session host status", status_tiles_q, vis="tiles", tiles=tiles),
        la("avd-hosts", "Session hosts (latest heartbeat)", hosts_q, formatters=[host_status],
           no_data="No AVD agent health data in this workspace."),
        la("avd-sessions", "Connected sessions and users", sessions_q, vis="timechart", width=50),
        la("avd-rtt", "Connection round-trip time (ms)", rtt_q, vis="timechart", width=50),
        la("avd-errors", "Top connection errors", errors_q, no_data="No AVD errors in the time range."),
    ], tab="avd")


def storage_tab():
    ns = "microsoft.storage/storageaccounts"
    fns = "microsoft.storage/storageaccounts/fileservices"
    inventory_q = Q_STORAGE + """
| project id,
    Kind = kind, Sku = tostring(sku.name),
    Primary = tostring(properties.statusOfPrimary),
    Secondary = tostring(properties.statusOfSecondary),
    PublicNetwork = tostring(properties.publicNetworkAccess),
    PrivateEndpoints = array_length(properties.privateEndpointConnections),
    MinTls = tostring(properties.minimumTlsVersion),
    ResourceGroup = resourceGroup, Location = location
"""
    return group("tab-storage", [
        params("storage-params", [resource_param("StorageAccounts", "Storage accounts", Q_STORAGE)]),
        metric_grid("storage-kpis", "Key metrics (over time range)", ns, "StorageAccounts", [
            ("Availability", AVG, "Availability %", ("high", 99.9, 99)),
            ("SuccessE2ELatency", AVG, "E2E latency (ms)", ("low", 100, 500)),
            ("SuccessServerLatency", AVG, "Server latency (ms)", ("low", 50, 200)),
            ("Transactions", SUM, "Transactions", None),
            ("UsedCapacity", AVG, "Used capacity", None),
        ]),
        metrics("storage-availability", "Availability %", ns, "StorageAccounts", [m(ns, "Availability", AVG)], width=50),
        metrics("storage-latency", "End-to-end latency (ms)", ns, "StorageAccounts", [m(ns, "SuccessE2ELatency", AVG)], width=50),
        metrics("storage-tx-response", "Transactions by response type (watch for throttling)", ns, "StorageAccounts",
                [m(ns, "Transactions", SUM, split="ResponseType")], width=50),
        metrics("storage-files-tx", "Azure Files transactions by response type (FSLogix)", ns, "StorageAccounts",
                [m(fns, "Transactions", SUM, split="ResponseType")], width=50),
        arg("storage-inventory", "Storage accounts", inventory_q, formatters=[
            resource_link(),
            status_fmt("Primary", good=["available"], bad=["unavailable"]),
            status_fmt("Secondary", good=["available"], bad=["unavailable"]),
            status_fmt("PublicNetwork", good=["Disabled"], warn=["Enabled"]),
        ], labels={"id": "Storage account"}),
    ], tab="storage")


def throughput_tab():
    fw, er = "microsoft.network/azurefirewalls", "microsoft.network/expressroutecircuits"
    gw, st = "microsoft.network/virtualnetworkgateways", "microsoft.storage/storageaccounts"
    avd_bw_q = """
WVDConnectionNetworkData
| where TimeGenerated {TimeRange}
| summarize AvgBandwidth_KBps = avg(EstAvailableBandwidthKBps) by bin(TimeGenerated, {TimeRange:grain})
"""
    return group("tab-throughput", [
        text("tp-intro", "Traffic across the platform's network edge and data services for the selected time range.", "info"),
        params("tp-params", [
            resource_param("TpFirewalls", "Firewalls", Q_FIREWALLS, hidden_when_locked=True),
            resource_param("TpCircuits", "Circuits", Q_CIRCUITS, hidden_when_locked=True),
            resource_param("TpErGateways", "ER gateways", Q_ER_GATEWAYS, hidden_when_locked=True),
            resource_param("TpVpnGateways", "VPN gateways", Q_VPN_GATEWAYS, hidden_when_locked=True),
            resource_param("TpStorage", "Storage accounts", Q_STORAGE, hidden_when_locked=True),
        ]),
        metrics("tp-fw", "Azure Firewall throughput", fw, "TpFirewalls", [m(fw, "Throughput", AVG)], width=50),
        metrics("tp-fw-data", "Azure Firewall data processed", fw, "TpFirewalls", [m(fw, "DataProcessed", SUM)], width=50),
        metrics("tp-er", "ExpressRoute circuits (bits/s in & out)", er, "TpCircuits",
                [m(er, "BitsInPerSecond", AVG), m(er, "BitsOutPerSecond", AVG)], width=50),
        metrics("tp-er-gw", "ExpressRoute gateway connections (bits/s in)", gw, "TpErGateways",
                [m(gw, "ErGatewayConnectionBitsInPerSecond", AVG, split="ConnectionName")], width=50),
        metrics("tp-vpn", "VPN gateway S2S bandwidth", gw, "TpVpnGateways", [m(gw, "AverageBandwidth", AVG)], width=50),
        metrics("tp-vpn-tunnels", "VPN tunnel bandwidth by connection", gw, "TpVpnGateways",
                [m(gw, "TunnelAverageBandwidth", AVG, split="ConnectionName")], width=50),
        metrics("tp-storage", "Storage ingress / egress", st, "TpStorage",
                [m(st, "Ingress", SUM), m(st, "Egress", SUM)], width=50),
        la("tp-avd-bw", "AVD available bandwidth (KBps)", avd_bw_q, vis="timechart", width=50),
    ], tab="throughput")


# ---------------------------------------------------------------------------
# Workbook
# ---------------------------------------------------------------------------

def global_params():
    return params("global-params", [
        {
            "id": gid("param-Subscription"),
            "version": "KqlParameterItem/1.0",
            "name": "Subscription",
            "label": "Subscriptions",
            "type": 6,
            "isRequired": True,
            "multiSelect": True,
            "quote": "'",
            "delimiter": ",",
            "query": "summarize by subscriptionId\n| project value = strcat('/subscriptions/', subscriptionId), label = subscriptionId",
            "crossComponentResources": ["value::all"],
            "typeSettings": {"additionalResourceOptions": ["value::all"], "showDefault": False},
            "defaultValue": "value::all",
            "value": ["value::all"],
            "queryType": 1,
            "resourceType": "microsoft.resourcegraph/resources",
        },
        {
            "id": gid("param-TimeRange"),
            "version": "KqlParameterItem/1.0",
            "name": "TimeRange",
            "label": "Time range",
            "type": 4,
            "isRequired": True,
            "value": {"durationMs": DAY_MS},
            "typeSettings": {
                "selectableValues": [{"durationMs": ms} for ms in
                                     (3600000, 14400000, 43200000, DAY_MS, 3 * DAY_MS, 7 * DAY_MS, 30 * DAY_MS)],
                "allowCustom": True,
            },
        },
        {
            "id": gid("param-Workspace"),
            "version": "KqlParameterItem/1.0",
            "name": "Workspace",
            "label": "Log Analytics workspace",
            "type": 5,
            "isRequired": False,
            "multiSelect": True,
            "quote": "'",
            "delimiter": ",",
            "query": "resources\n| where type =~ 'microsoft.operationalinsights/workspaces'\n| project id",
            "crossComponentResources": ["{Subscription}"],
            "typeSettings": {"resourceTypeFilter": {"microsoft.operationalinsights/workspaces": True},
                             "additionalResourceOptions": [], "showDefault": False},
            "queryType": 1,
            "resourceType": "microsoft.resourcegraph/resources",
            "description": "Optional. Used for AVD, firewall and VPN log panels.",
        },
        {
            "id": gid("param-BuildAgentPattern"),
            "version": "KqlParameterItem/1.0",
            "name": "BuildAgentPattern",
            "label": "Build agent name pattern",
            "type": 1,
            "isRequired": True,
            "value": "(?i)(agent|build|ado|devops|runner)",
            "description": "Regex matched against VM / scale set names to identify build agents.",
        },
        {
            "id": gid("param-selectedTab"),
            "version": "KqlParameterItem/1.0",
            "name": "selectedTab",
            "type": 1,
            "value": "overview",
            "isHiddenWhenLocked": True,
        },
    ])


def tabs():
    return {"type": 11, "content": {"version": "LinkItem/1.0", "style": "tabs", "links": [
        {"id": gid("tab-" + key), "cellValue": "selectedTab", "linkTarget": "parameter",
         "linkLabel": label, "subTarget": key, "style": "link"} for key, label in TABS
    ]}, "name": "tabs"}


def workbook():
    return {
        "version": "Notebook/1.0",
        "items": [
            text("header", "# Enterprise Scale Platform Health\n"
                 "Health, capacity and throughput of the shared platform services: connectivity "
                 "(Firewall, ExpressRoute, VPN), Azure VMware Solution, Azure Virtual Desktop, storage and build agents."),
            global_params(),
            tabs(),
            overview_tab(),
            firewall_tab(),
            expressroute_tab(),
            vpn_tab(),
            buildagents_tab(),
            avs_tab(),
            avd_tab(),
            storage_tab(),
            throughput_tab(),
        ],
        "fallbackResourceIds": ["Azure Monitor"],
        "$schema": "https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json",
    }


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(workbook(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
