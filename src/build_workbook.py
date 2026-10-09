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


VALUE_TEXT = "{0}{1}"
ICON_ONLY = "​"  # zero-width space: show the icon without the status word


def _t(op, value, rep, text=VALUE_TEXT):
    return {"operator": op, "thresholdValue": value, "representation": rep, "text": text}


def status_fmt(col, good=(), warn=(), bad=(), neutral=(), text=VALUE_TEXT):
    """Icon formatter for string status columns."""
    grid = [_t("==", v, "success", text) for v in good]
    grid += [_t("==", v, "2", text) for v in warn]
    grid += [_t("==", v, "4", text) for v in bad]
    grid += [_t("==", v, "unknown", text) for v in neutral]
    grid.append(_t("Default", None, "Blank", text))
    return {"columnMatch": col, "formatter": 18, "formatOptions": _icons(grid)}


def health_fmt(col="Health", text=VALUE_TEXT):
    return status_fmt(col, good=["Available"], warn=["Degraded"], bad=["Unavailable"], neutral=["Unknown"], text=text)


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

def text(name, md, style=None, visible_when=None):
    content = {"json": md}
    if style:
        content["style"] = style
    item = {"type": 1, "content": content, "name": name}
    if visible_when:
        item["conditionalVisibility"] = visible_when
    return item


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
        content["size"] = 3
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

Q_HUBS = "resources\n| where type =~ 'microsoft.network/virtualhubs'"
Q_FIREWALLS = "resources\n| where type =~ 'microsoft.network/azurefirewalls'"
Q_CIRCUITS = "resources\n| where type =~ 'microsoft.network/expressroutecircuits'"
Q_ER_GATEWAYS = "resources\n| where type =~ 'microsoft.network/expressroutegateways'"
Q_VPN_GATEWAYS = "resources\n| where type =~ 'microsoft.network/vpngateways'"
Q_P2S_GATEWAYS = "resources\n| where type =~ 'microsoft.network/p2svpngateways'"
Q_AVS = "resources\n| where type =~ 'microsoft.avs/privateclouds'"
Q_STORAGE = "resources\n| where type =~ 'microsoft.storage/storageaccounts'"
Q_AGENT_VMSS = ("resources\n| where type =~ 'microsoft.compute/virtualmachinescalesets'"
                "\n| where name matches regex @'{BuildAgentPattern}'")
Q_BASTIONS = "resources\n| where type =~ 'microsoft.network/bastionhosts'"
Q_PUBLIC_IPS = "resources\n| where type =~ 'microsoft.network/publicipaddresses'"
Q_KEYVAULTS = "resources\n| where type =~ 'microsoft.keyvault/vaults'"

PLATFORM_TYPES = [
    "microsoft.network/virtualwans",
    "microsoft.network/virtualhubs",
    "microsoft.network/azurefirewalls",
    "microsoft.network/expressroutecircuits",
    "microsoft.network/expressroutegateways",
    "microsoft.network/vpngateways",
    "microsoft.network/p2svpngateways",
    "microsoft.network/vpnsites",
    "microsoft.network/virtualnetworkgateways",
    "microsoft.network/bastionhosts",
    "microsoft.network/ddosprotectionplans",
    "microsoft.network/privatednszones",
    "microsoft.network/dnsresolvers",
    "microsoft.keyvault/vaults",
    "microsoft.avs/privateclouds",
    "microsoft.desktopvirtualization/hostpools",
    "microsoft.storage/storageaccounts",
    "microsoft.compute/virtualmachinescalesets",
    "microsoft.operationalinsights/workspaces",
    "microsoft.recoveryservices/vaults",
]
TYPE_LIST = ", ".join(f"'{t}'" for t in PLATFORM_TYPES)

# Every platform resource we care about, tagged with a Service, joined to Resource Health.
# Resource Health in ARG only covers some types, so a config-derived status is used as fallback.
Q_INVENTORY_HEALTH = f"""
resources
| where type in~ ({TYPE_LIST})
| where type !~ 'microsoft.compute/virtualmachinescalesets' or name matches regex @'{{BuildAgentPattern}}'
| extend gatewayType = tostring(properties.gatewayType)
| extend Service = case(
    type in~ ('microsoft.network/virtualwans', 'microsoft.network/virtualhubs'), 'Virtual WAN',
    type =~ 'microsoft.network/azurefirewalls', 'Azure Firewall',
    type in~ ('microsoft.network/expressroutecircuits', 'microsoft.network/expressroutegateways'), 'ExpressRoute',
    type =~ 'microsoft.network/virtualnetworkgateways' and gatewayType =~ 'ExpressRoute', 'ExpressRoute',
    type in~ ('microsoft.network/vpngateways', 'microsoft.network/p2svpngateways', 'microsoft.network/vpnsites', 'microsoft.network/virtualnetworkgateways'), 'VPN',
    type =~ 'microsoft.network/bastionhosts', 'Bastion',
    type =~ 'microsoft.network/ddosprotectionplans', 'DDoS Protection',
    type in~ ('microsoft.network/privatednszones', 'microsoft.network/dnsresolvers'), 'DNS',
    type =~ 'microsoft.keyvault/vaults', 'Key Vault',
    type =~ 'microsoft.avs/privateclouds', 'Azure VMware Solution',
    type =~ 'microsoft.desktopvirtualization/hostpools', 'Azure Virtual Desktop',
    type =~ 'microsoft.storage/storageaccounts', 'Storage',
    type =~ 'microsoft.operationalinsights/workspaces', 'Log Analytics',
    type =~ 'microsoft.recoveryservices/vaults', 'Backup & DR',
    'Build Agents')
| extend provisioning = tostring(properties.provisioningState),
    routingState = tostring(properties.routingState),
    ingestion = tostring(properties.workspaceCapping.dataIngestionStatus),
    recordSetPct = 100.0 * todouble(properties.numberOfRecordSets) / todouble(properties.maxNumberOfRecordSets)
| extend ConfigHealth = case(
        provisioning =~ 'Failed', 'Unavailable',
        routingState =~ 'Failed', 'Unavailable',
        tostring(properties.dnsResolverState) =~ 'Disconnected', 'Unavailable',
        tostring(properties.circuitProvisioningState) =~ 'Disabled', 'Unavailable',
        tostring(properties.statusOfPrimary) =~ 'unavailable', 'Unavailable',
        ingestion in~ ('OverQuota', 'ForceOff', 'SubscriptionSuspended'), 'Unavailable',
        type =~ 'microsoft.network/expressroutecircuits' and tostring(properties.serviceProviderProvisioningState) !~ 'Provisioned', 'Degraded',
        routingState =~ 'Provisioning', 'Degraded',
        ingestion =~ 'ApproachingQuota', 'Degraded',
        recordSetPct >= 80, 'Degraded',
        type =~ 'microsoft.network/privatednszones' and toint(properties.numberOfVirtualNetworkLinks) == 0, 'Degraded',
        provisioning in~ ('Updating', 'Deleting', 'Canceled'), 'Degraded',
        'Available'),
    ConfigReason = case(
        provisioning =~ 'Failed', 'Provisioning failed',
        routingState in~ ('Failed', 'Provisioning'), strcat('Hub routing state: ', routingState),
        tostring(properties.dnsResolverState) =~ 'Disconnected', 'DNS resolver disconnected',
        tostring(properties.circuitProvisioningState) =~ 'Disabled', 'Circuit disabled',
        type =~ 'microsoft.network/expressroutecircuits' and tostring(properties.serviceProviderProvisioningState) !~ 'Provisioned',
            strcat('Provider state: ', tostring(properties.serviceProviderProvisioningState)),
        tostring(properties.statusOfPrimary) =~ 'unavailable', 'Primary region unavailable',
        ingestion in~ ('OverQuota', 'ForceOff', 'SubscriptionSuspended', 'ApproachingQuota'), strcat('Ingestion: ', ingestion),
        recordSetPct >= 80, strcat('Record sets at ', round(recordSetPct, 0), '% of limit'),
        type =~ 'microsoft.network/privatednszones' and toint(properties.numberOfVirtualNetworkLinks) == 0, 'Zone not linked to any VNet',
        provisioning in~ ('Updating', 'Deleting', 'Canceled'), strcat('Provisioning: ', provisioning),
        '')
| project id = tolower(id), Service, Type = type, ResourceGroup = resourceGroup, SubscriptionId = subscriptionId,
    Location = location, ConfigHealth, ConfigReason
| join kind=leftouter (
    healthresources
    | where type =~ 'microsoft.resourcehealth/availabilitystatuses'
    | project id = tostring(split(tolower(id), '/providers/microsoft.resourcehealth/')[0]),
        Health = tostring(properties.availabilityState),
        Reason = tostring(properties.summary),
        Since = todatetime(properties.occurredTime)
  ) on id
| project-away id1
| extend Signal = iff(isempty(Health), 'Config state', 'Resource Health')
| extend Health = iff(isempty(Health), ConfigHealth, Health),
    Reason = iff(isempty(Reason), ConfigReason, Reason)
| project-away ConfigHealth, ConfigReason
"""

# Governance / security / backup signals for the Overview tiles. Each table needs its own query:
# ARG does not allow these tables to be combined in one union.
GOVERNANCE_TILES = [
    ("policy", """
policyresources
| where type =~ 'microsoft.policyinsights/policystates'
| summarize Total = dcount(tostring(properties.resourceId)),
    Bad = dcountif(tostring(properties.resourceId), tostring(properties.complianceState) =~ 'NonCompliant')
| project Signal = 'Policy compliance',
    Display = iff(Total == 0, '—', strcat(round(100.0 * (Total - Bad) / Total, 1), '%')),
    Detail = strcat(Bad, ' non-compliant resources'),
    State = case(Total == 0, 'Unknown', Bad == 0, 'Available', 'Degraded')
"""),
    ("defender", """
securityresources
| where type in~ ('microsoft.security/securescores', 'microsoft.security/locations/alerts')
| extend isScore = type =~ 'microsoft.security/securescores',
    isActiveAlert = type =~ 'microsoft.security/locations/alerts' and tostring(properties.Status) =~ 'Active'
| summarize Score = avgif(toreal(properties.score.percentage), isScore), Subs = countif(isScore),
    Alerts = countif(isActiveAlert), High = countif(isActiveAlert and tostring(properties.Severity) =~ 'High')
| project Signal = 'Defender for Cloud',
    Display = iff(Subs == 0, '—', strcat(round(Score * 100, 0), '%')),
    Detail = strcat('secure score · ', Alerts, ' alerts (', High, ' high)'),
    State = case(High > 0, 'Unavailable', Subs == 0, 'Unknown', Score < 0.5, 'Unavailable', Score < 0.8 or Alerts > 0, 'Degraded', 'Available')
"""),
    ("advisor", """
advisorresources
| where type =~ 'microsoft.advisor/recommendations'
| where tostring(properties.impact) =~ 'High'
| summarize Total = count(),
    Reliability = countif(tostring(properties.category) =~ 'HighAvailability'),
    Security = countif(tostring(properties.category) =~ 'Security')
| project Signal = 'Advisor (high impact)', Display = tostring(Total),
    Detail = strcat(Reliability, ' reliability · ', Security, ' security'),
    State = case(Reliability > 0, 'Degraded', 'Available')
"""),
    ("backup", """
recoveryservicesresources
| where type =~ 'microsoft.recoveryservices/vaults/backupjobs'
| where todatetime(properties.startTime) > ago(1d)
| summarize Failed = countif(tostring(properties.status) =~ 'Failed'), Jobs = count()
| project Signal = 'Backup jobs (24h)', Display = tostring(Failed),
    Detail = strcat(Failed, ' failed of ', Jobs, ' jobs'),
    State = case(Jobs == 0, 'Unknown', Failed > 0, 'Unavailable', 'Available')
"""),
]

# AVD session host status, shared by the Overview and AVD tabs.
AVD_LATEST_HOSTS = """
WVDAgentHealthStatus
| where TimeGenerated {TimeRange}
| summarize arg_max(TimeGenerated, *) by SessionHostName
| extend HostPool = tostring(split(_ResourceId, '/')[8])
| extend Status = iff(TimeGenerated < ago(30m), 'NoRecentHeartbeat', Status)
"""
AVD_STATUS_TILES_Q = AVD_LATEST_HOSTS + "| summarize Hosts = count() by Status\n| order by Hosts desc"
AVD_HOST_STATES = dict(good=["Available"], warn=["Upgrading", "NeedsAssistance", "Shutdown"],
                       bad=["Unavailable", "NoRecentHeartbeat", "UpgradeFailed", "NoHeartbeat"])
AVD_HOST_STATUS = status_fmt("Status", **AVD_HOST_STATES)
AVD_STATUS_TILES = {
    "titleContent": {"columnMatch": "Status", "formatter": 1},
    "leftContent": status_fmt("Status", **AVD_HOST_STATES, text=ICON_ONLY),
    "rightContent": {"columnMatch": "Hosts", "formatter": 12, "formatOptions": {"palette": "none"}},
    "showBorder": True,
}

SUBSCRIPTION_NAMES = """
| join kind=leftouter (
    resourcecontainers
    | where type =~ 'microsoft.resources/subscriptions'
    | project subscriptionId, Subscription = name
  ) on subscriptionId
"""


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

TABS = [
    ("overview", "Overview"),
    ("vwan", "Virtual WAN"),
    ("firewall", "Azure Firewall"),
    ("expressroute", "ExpressRoute"),
    ("vpn", "VPN"),
    ("shared", "Shared Services"),
    ("buildagents", "Build Agents"),
    ("avs", "Azure VMware Solution"),
    ("avd", "Azure Virtual Desktop"),
    ("storage", "Storage"),
    ("governance", "Governance & Security"),
    ("management", "Monitoring & Backup"),
    ("throughput", "Throughput"),
]


def state_tiles(title_col, state_col, value_col, detail_col=None):
    t = {
        "titleContent": {"columnMatch": title_col, "formatter": 1},
        "leftContent": health_fmt(state_col, text=ICON_ONLY),
        "rightContent": {"columnMatch": value_col, "formatter": 1},
        "showBorder": True,
    }
    if detail_col:
        t["secondaryContent"] = {"columnMatch": detail_col, "formatter": 1}
    return t


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
    service_health_tile_q = """
servicehealthresources
| where type =~ 'microsoft.resourcehealth/events'
| where tostring(properties.Status) =~ 'Active'
| extend EventType = tostring(properties.EventType), TrackingId = tostring(properties.TrackingId)
| summarize Total = dcount(TrackingId),
    Issues = dcountif(TrackingId, EventType =~ 'ServiceIssue'),
    Maintenance = dcountif(TrackingId, EventType =~ 'PlannedMaintenance'),
    Advisories = dcountif(TrackingId, EventType !in~ ('ServiceIssue', 'PlannedMaintenance'))
| project Service = 'Azure Service Health', Total,
    Status = case(Issues > 0, 'Unavailable', Total > 0, 'Degraded', 'Available'),
    Summary = strcat(Issues, ' service issues · ', Maintenance, ' maintenance · ', Advisories, ' advisories')
"""
    unhealthy_q = Q_INVENTORY_HEALTH + """
| where Health != 'Available'
| project id, Service, Health, Signal, Reason, Since, ResourceGroup, Location
| order by case(Health == 'Unavailable', 0, Health == 'Degraded', 1, 2) asc, Service asc
"""
    all_q = Q_INVENTORY_HEALTH + """
| project id, Service, Health, Signal, Reason, Type, ResourceGroup, Location
| order by Service asc
"""
    alerts_q = f"""
alertsmanagementresources
| where type =~ 'microsoft.alertsmanagement/alerts'
| extend e = properties.essentials
| where tostring(e.monitorCondition) =~ 'Fired' and tostring(e.alertState) !~ 'Closed'
| where tolower(tostring(e.targetResourceType)) in~ ({TYPE_LIST})
| project Severity = tostring(e.severity), Alert = name, Target = tostring(e.targetResource),
    State = tostring(e.alertState), Fired = todatetime(e.startDateTime)
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
    sev = {"columnMatch": "Severity", "formatter": 18, "formatOptions": _icons(
        [_t("==", f"Sev{i}", f"Sev{i}") for i in range(5)] + [_t("Default", None, "Blank")])}
    service_tiles = state_tiles("Service", "Status", "Total", "Summary")
    service_tiles["rightContent"] = {"columnMatch": "Total", "formatter": 12, "formatOptions": {"palette": "none"}}
    return group("tab-overview", [
        text("overview-intro",
             "Status comes from **Azure Resource Health** where available; otherwise from the resource's "
             "configuration state (provisioning, hub routing state, circuit/provider state, DNS limits, workspace "
             "ingestion) — see the *Signal* column. Each service tab adds metric-based health.", "info"),
        text("overview-glance-h", "### At a glance"),
        arg("overview-servicehealth-tile", "", service_health_tile_q, vis="tiles", tiles=service_tiles, width=12),
        *[arg(f"overview-{key}", "", q, vis="tiles", tiles=state_tiles("Signal", "State", "Display", "Detail"), width=12)
          for key, q in GOVERNANCE_TILES],
        arg("overview-tiles", "Platform services", summary_q, vis="tiles", tiles=service_tiles,
            no_data="No platform resources found in the selected subscriptions."),
        la("overview-avd-host-tiles", "Azure Virtual Desktop session hosts", AVD_STATUS_TILES_Q, vis="tiles",
           tiles=AVD_STATUS_TILES, no_data="No AVD session host data in the selected workspace."),
        text("overview-avd-hint", "Select the **Log Analytics workspace** at the top to see AVD session host status here.",
             "info", visible_when=WORKSPACE_UNSET),
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


def vwan_tab():
    ns = "microsoft.network/virtualhubs"
    wans_q = """
resources
| where type =~ 'microsoft.network/virtualwans'
| project id,
    WanType = tostring(properties.type),
    Hubs = array_length(properties.virtualHubs),
    VpnSites = array_length(properties.vpnSites),
    BranchToBranch = tostring(properties.allowBranchToBranchTraffic),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup, Location = location
"""
    hubs_q = Q_HUBS + """
| project id,
    Wan = tostring(split(tostring(properties.virtualWan.id), '/')[8]),
    AddressPrefix = tostring(properties.addressPrefix),
    RoutingState = tostring(properties.routingState),
    RoutingPreference = tostring(properties.hubRoutingPreference),
    MinRoutingUnits = toint(properties.virtualRouterAutoScaleConfiguration.minCapacity),
    Secured = isnotempty(tostring(properties.azureFirewall.id)),
    ExpressRoute = isnotempty(tostring(properties.expressRouteGateway.id)),
    S2SVpn = isnotempty(tostring(properties.vpnGateway.id)),
    P2SVpn = isnotempty(tostring(properties.p2SVpnGateway.id)),
    Provisioning = tostring(properties.provisioningState),
    Location = location
"""
    peerings_q = """
resources
| where type =~ 'microsoft.network/virtualnetworks'
| mv-expand p = properties.virtualNetworkPeerings
| extend remote = tostring(p.properties.remoteVirtualNetwork.id)
| where isnotempty(remote)
| extend RemoteVnet = tostring(split(remote, '/')[8])
| project id,
    ConnectedTo = iff(RemoteVnet startswith 'HV_', strcat('vWAN hub: ', tostring(split(RemoteVnet, '_')[1])), RemoteVnet),
    PeeringState = tostring(p.properties.peeringState),
    SyncLevel = tostring(p.properties.peeringSyncLevel),
    AddressSpace = strcat_array(properties.addressSpace.addressPrefixes, ', '),
    ResourceGroup = resourceGroup
| order by case(PeeringState =~ 'Connected', 1, 0) asc, ConnectedTo asc
"""
    return group("tab-vwan", [
        params("vwan-params", [resource_param("Hubs", "Hubs", Q_HUBS)]),
        arg("vwan-wans", "Virtual WANs", wans_q, formatters=[resource_link(), PROVISIONING],
            labels={"id": "Virtual WAN"}, no_data="No Virtual WANs found."),
        arg("vwan-hubs", "Virtual hubs", hubs_q, formatters=[
            resource_link(), PROVISIONING,
            status_fmt("RoutingState", good=["Provisioned"], warn=["Provisioning"], bad=["Failed"], neutral=["None"]),
        ], labels={"id": "Hub", "MinRoutingUnits": "Min routing units"}, no_data="No virtual hubs found."),
        metric_grid("vwan-kpis", "Hub router metrics (over time range)", ns, "Hubs", [
            ("SpokeVMUtilization", MAX, "Spoke VM utilisation % (max)", ("low", 80, 95)),
            ("RoutingInfrastructureUnits", MAX, "Routing infra units", None),
            ("CountOfRoutesLearnedFromPeer", MAX, "Routes learned (max)", None),
            ("VirtualHubDataProcessed", SUM, "Data processed", None),
        ]),
        text("vwan-riu-note", "Each routing infrastructure unit supports ~1,000 spoke VMs. If *Spoke VM utilisation* "
             "approaches 100%, raise the hub's minimum routing units.", "info"),
        metrics("vwan-bgp", "Hub BGP peer status by peer (1 = up)", ns, "Hubs",
                [m(ns, "BgpPeerStatus", MAX, split="bgppeerip")], width=50),
        metrics("vwan-spoke-util", "Spoke VM utilisation %", ns, "Hubs", [m(ns, "SpokeVMUtilization", MAX)], width=50),
        metrics("vwan-routes", "Routes learned from peers", ns, "Hubs",
                [m(ns, "CountOfRoutesLearnedFromPeer", MAX, split="bgppeerip")], width=50),
        metrics("vwan-data", "Hub data processed", ns, "Hubs", [m(ns, "VirtualHubDataProcessed", SUM)], width=50),
        arg("vwan-peerings", "Spoke VNet connections (peerings)", peerings_q, formatters=[
            resource_link(),
            status_fmt("PeeringState", good=["Connected"], warn=["Initiated"], bad=["Disconnected"]),
            status_fmt("SyncLevel", good=["FullyInSync"], warn=["LocalNotInSync", "RemoteNotInSync", "LocalAndRemoteNotInSync"]),
        ], labels={"id": "Spoke VNet"}, no_data="No VNet peerings found."),
    ], tab="vwan")


def firewall_tab():
    ns = "microsoft.network/azurefirewalls"
    inventory_q = Q_FIREWALLS + """
| project id,
    Tier = tostring(properties.sku.tier),
    Hub = iff(isnotempty(tostring(properties.virtualHub.id)), tostring(split(tostring(properties.virtualHub.id), '/')[8]), 'Hub VNet'),
    Policy = tostring(split(tostring(properties.firewallPolicy.id), '/')[8]),
    PublicIPs = toint(properties.hubIPAddresses.publicIPs['count']),
    PrivateIP = coalesce(tostring(properties.hubIPAddresses.privateIPAddress), tostring(properties.ipConfigurations[0].properties.privateIPAddress)),
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
    threats_q = """
union isfuzzy=true
    (AZFWThreatIntel | where TimeGenerated {TimeRange}
        | project TimeGenerated, Source = 'Threat intel', SourceIp, Destination = strcat(DestinationIp, ':', DestinationPort), Action, Detail = ThreatDescription),
    (AZFWIdpsSignature | where TimeGenerated {TimeRange}
        | project TimeGenerated, Source = 'IDPS', SourceIp, Destination = strcat(DestinationIp, ':', DestinationPort), Action, Detail = Description)
| summarize Hits = count(), LastSeen = max(TimeGenerated) by Source, Action, Detail, SourceIp, Destination
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
            ("ObservedCapacity", MAX, "Observed capacity units (max)", None),
            ("FirewallLatencyPng", AVG, "Latency probe (ms)", ("low", 10, 20)),
            ("DataProcessed", SUM, "Data processed", None),
        ]),
        metrics("firewall-health", "Health state %", ns, "Firewalls", [m(ns, "FirewallHealth", AVG)], width=50),
        metrics("firewall-throughput", "Throughput", ns, "Firewalls", [m(ns, "Throughput", AVG)], width=50),
        metrics("firewall-snat", "SNAT port utilisation % (max)", ns, "Firewalls", [m(ns, "SNATPortUtilization", MAX)], width=50),
        metrics("firewall-capacity", "Observed capacity units", ns, "Firewalls", [m(ns, "ObservedCapacity", MAX)], width=50),
        metrics("firewall-latency", "Latency probe (ms)", ns, "Firewalls", [m(ns, "FirewallLatencyPng", AVG)], width=50),
        metrics("firewall-rulehits", "Rule hits", ns, "Firewalls",
                [m(ns, "NetworkRuleHit", SUM), m(ns, "ApplicationRuleHit", SUM)], width=50),
        text("firewall-logs-hint", "Select a **Log Analytics workspace** at the top to see denied traffic and threat "
             "detections (requires resource-specific firewall logs, e.g. `AZFWNetworkRule`).", "info", visible_when=WORKSPACE_UNSET),
        la("firewall-denied", "Top denied flows", denied_q, width=50,
           no_data="No denied flows (or structured firewall logs are not enabled)."),
        la("firewall-threats", "Threat intel & IDPS detections", threats_q, width=50,
           no_data="No threat intel or IDPS hits."),
    ], tab="firewall")


def expressroute_tab():
    cns = "microsoft.network/expressroutecircuits"
    gns = "microsoft.network/expressroutegateways"
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
    gateways_q = Q_ER_GATEWAYS + """
| project id,
    Hub = tostring(split(tostring(properties.virtualHub.id), '/')[8]),
    MinScaleUnits = toint(properties.autoScaleConfiguration.bounds.min),
    Connections = array_length(properties.expressRouteConnections),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup, Location = location
"""
    connections_q = Q_ER_GATEWAYS + """
| mv-expand c = properties.expressRouteConnections
| project Gateway = id,
    Connection = tostring(c.name),
    Circuit = tostring(split(tostring(c.properties.expressRouteCircuitPeering.id), '/')[8]),
    RoutingWeight = toint(c.properties.routingWeight),
    InternetSecurity = tostring(c.properties.enableInternetSecurity),
    FastPath = tostring(c.properties.expressRouteGatewayBypass),
    Provisioning = tostring(c.properties.provisioningState)
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
            ("IngressBandwidthUtilization", MAX, "Max ingress util %", ("low", 70, 90)),
            ("EgressBandwidthUtilization", MAX, "Max egress util %", ("low", 70, 90)),
            ("QosDropBitsInPerSecond", AVG, "QoS drops in (bits/s)", None),
        ]),
        metrics("er-bgp", "BGP availability % by peering", cns, "Circuits",
                [m(cns, "BgpAvailability", AVG, split="PeeringType")], width=50),
        metrics("er-arp", "ARP availability % by peering", cns, "Circuits",
                [m(cns, "ArpAvailability", AVG, split="PeeringType")], width=50),
        metrics("er-bits", "Circuit throughput (bits/s)", cns, "Circuits",
                [m(cns, "BitsInPerSecond", AVG), m(cns, "BitsOutPerSecond", AVG)], width=50),
        metrics("er-util", "Circuit bandwidth utilisation % (max)", cns, "Circuits",
                [m(cns, "IngressBandwidthUtilization", MAX), m(cns, "EgressBandwidthUtilization", MAX)], width=50),
        arg("er-gateways", "vWAN ExpressRoute gateways", gateways_q, formatters=[resource_link(), PROVISIONING],
            labels={"id": "Gateway"}, no_data="No vWAN ExpressRoute gateways found.", width=40),
        arg("er-connections", "Gateway connections", connections_q,
            formatters=[resource_link("Gateway"), PROVISIONING],
            no_data="No ExpressRoute connections found.", width=60),
        metric_grid("er-gw-kpis", "Gateway key metrics (over time range)", gns, "ErGateways", [
            ("ExpressRouteGatewayCpuUtilization", AVG, "CPU %", ("low", 70, 85)),
            ("ExpressRouteGatewayBitsPerSecond", AVG, "Avg bits/s", None),
            ("ExpressRouteGatewayPacketsPerSecond", AVG, "Avg packets/s", None),
            ("ExpressRouteGatewayActiveFlows", MAX, "Max active flows", None),
            ("ExpressRouteGatewayCountOfRoutesLearnedFromPeer", MAX, "Routes learned", None),
        ]),
        metrics("er-gw-cpu", "Gateway CPU % by instance", gns, "ErGateways",
                [m(gns, "ExpressRouteGatewayCpuUtilization", AVG, split="roleInstance")], width=50),
        metrics("er-gw-bits", "Gateway throughput (bits/s)", gns, "ErGateways",
                [m(gns, "ExpressRouteGatewayBitsPerSecond", AVG)], width=50),
        metrics("er-gw-routes", "Routes learned by BGP peer", gns, "ErGateways",
                [m(gns, "ExpressRouteGatewayCountOfRoutesLearnedFromPeer", MAX, split="BgpPeerAddress")], width=50),
        metrics("er-gw-conn-bits", "Bits in/s by connection", gns, "ErGateways",
                [m(gns, "ErGatewayConnectionBitsInPerSecond", AVG, split="ConnectionName")], width=50),
    ], tab="expressroute")


def vpn_tab():
    ns = "microsoft.network/vpngateways"
    pns = "microsoft.network/p2svpngateways"
    gateways_q = """
resources
| where type in~ ('microsoft.network/vpngateways', 'microsoft.network/p2svpngateways')
| project id,
    Kind = iff(type =~ 'microsoft.network/vpngateways', 'Site-to-site', 'Point-to-site'),
    Hub = tostring(split(tostring(properties.virtualHub.id), '/')[8]),
    ScaleUnits = toint(properties.vpnGatewayScaleUnit),
    Connections = array_length(properties.connections),
    Bgp = tostring(properties.bgpSettings.asn),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup, Location = location
"""
    sites_q = """
resources
| where type =~ 'microsoft.network/vpnsites'
| project id,
    Vendor = tostring(properties.deviceProperties.deviceVendor),
    Model = tostring(properties.deviceProperties.deviceModel),
    Links = array_length(properties.vpnSiteLinks),
    LinkSpeedMbps = toint(properties.vpnSiteLinks[0].properties.linkProperties.linkSpeedInMbps),
    Provider = tostring(properties.vpnSiteLinks[0].properties.linkProperties.linkProviderName),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup, Location = location
"""
    connections_q = Q_VPN_GATEWAYS + """
| mv-expand c = properties.connections
| project Gateway = id,
    Connection = tostring(c.name),
    Site = tostring(split(tostring(c.properties.remoteVpnSite.id), '/')[8]),
    Links = array_length(c.properties.vpnLinkConnections),
    Bgp = tostring(c.properties.vpnLinkConnections[0].properties.enableBgp),
    InternetSecurity = tostring(c.properties.enableInternetSecurity),
    Provisioning = tostring(c.properties.provisioningState)
"""
    tunnel_q = """
AzureDiagnostics
| where TimeGenerated {TimeRange}
| where Category == 'TunnelDiagnosticLog'
| project TimeGenerated, Gateway = Resource,
    Connection = column_ifexists('instance_s', ''),
    RemoteIP = column_ifexists('remoteIP_s', ''),
    Status = column_ifexists('status_s', ''),
    Reason = column_ifexists('stateChangeReason_s', '')
| order by TimeGenerated desc
| take 200
"""
    return group("tab-vpn", [
        params("vpn-params", [
            resource_param("VpnGateways", "S2S gateways", Q_VPN_GATEWAYS),
            resource_param("P2SGateways", "P2S gateways", Q_P2S_GATEWAYS),
        ]),
        arg("vpn-gateways", "vWAN VPN gateways", gateways_q, formatters=[resource_link(), PROVISIONING],
            labels={"id": "Gateway"}, no_data="No vWAN VPN gateways found."),
        metric_grid("vpn-kpis", "Site-to-site key metrics (over time range)", ns, "VpnGateways", [
            ("BgpPeerStatus", AVG, "BGP peers up (1 = all)", ("high", 1, 0.5)),
            ("AverageBandwidth", AVG, "Avg S2S bandwidth", None),
            ("TunnelIngressPacketDropCount", SUM, "Ingress drops", None),
            ("TunnelEgressPacketDropCount", SUM, "Egress drops", None),
            ("TunnelIngressPacketDropTSMismatch", SUM, "Traffic selector mismatch drops", None),
        ]),
        metrics("vpn-tunnel-bw", "Tunnel bandwidth by connection", ns, "VpnGateways",
                [m(ns, "TunnelAverageBandwidth", AVG, split="ConnectionName")], width=50),
        metrics("vpn-bgp", "BGP peer status by peer (1 = up)", ns, "VpnGateways",
                [m(ns, "BgpPeerStatus", AVG, split="BgpPeerAddress")], width=50),
        metrics("vpn-drops", "Tunnel packet drops", ns, "VpnGateways",
                [m(ns, "TunnelIngressPacketDropCount", SUM), m(ns, "TunnelEgressPacketDropCount", SUM)], width=50),
        metrics("vpn-bytes", "Tunnel bytes in / out", ns, "VpnGateways",
                [m(ns, "TunnelIngressBytes", SUM), m(ns, "TunnelEgressBytes", SUM)], width=50),
        metrics("vpn-p2s-count", "P2S connections", pns, "P2SGateways", [m(pns, "P2SConnectionCount", SUM)], width=50),
        metrics("vpn-p2s-bw", "P2S bandwidth", pns, "P2SGateways", [m(pns, "P2SBandwidth", AVG)], width=50),
        arg("vpn-sites", "VPN sites", sites_q, formatters=[resource_link(), PROVISIONING],
            labels={"id": "Site"}, no_data="No VPN sites found.", width=50),
        arg("vpn-connections", "Site connections", connections_q,
            formatters=[resource_link("Gateway"), PROVISIONING], no_data="No VPN connections found.", width=50),
        la("vpn-tunnel-events", "Tunnel connect/disconnect events", tunnel_q,
           no_data="No tunnel events (or gateway diagnostic logs are not sent to this workspace)."),
    ], tab="vpn")


def shared_tab():
    bns, kns, pns = "microsoft.network/bastionhosts", "microsoft.keyvault/vaults", "microsoft.network/publicipaddresses"
    bastion_q = Q_BASTIONS + """
| project id,
    Sku = tostring(sku.name),
    ScaleUnits = toint(properties.scaleUnits),
    Tunneling = tostring(properties.enableTunneling),
    IpConnect = tostring(properties.enableIpConnect),
    Vnet = tostring(split(tostring(properties.ipConfigurations[0].properties.subnet.id), '/')[8]),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup, Location = location
"""
    ddos_plans_q = """
resources
| where type =~ 'microsoft.network/ddosprotectionplans'
| project id, ProtectedVnets = array_length(properties.virtualNetworks),
    Provisioning = tostring(properties.provisioningState), ResourceGroup = resourceGroup, Location = location
"""
    ddos_coverage_q = """
resources
| where type =~ 'microsoft.network/virtualnetworks'
| summarize Total = count(), Protected = countif(tobool(properties.enableDdosProtection))
| project Signal = 'VNets with DDoS Network Protection', Display = strcat(Protected, ' / ', Total),
    State = case(Total == 0, 'Unknown', Protected == Total, 'Available', 'Degraded')
| union (
    resources
    | where type =~ 'microsoft.network/publicipaddresses'
    | extend mode = tostring(properties.ddosSettings.protectionMode)
    | summarize Total = count(), IpProtected = countif(mode =~ 'Enabled'), Disabled = countif(mode =~ 'Disabled')
    | project Signal = 'Public IPs: IP Protection / explicitly disabled', Display = strcat(IpProtected, ' / ', Disabled),
        State = case(Disabled > 0, 'Degraded', 'Available'))
"""
    dns_zones_q = """
resources
| where type =~ 'microsoft.network/privatednszones'
| extend RecordSets = toint(properties.numberOfRecordSets),
    Links = toint(properties.numberOfVirtualNetworkLinks),
    RegistrationLinks = toint(properties.numberOfVirtualNetworkLinksWithRegistration)
| project id, RecordSets,
    RecordSetPct = round(100.0 * RecordSets / todouble(properties.maxNumberOfRecordSets), 1),
    Links,
    LinkPct = round(100.0 * Links / todouble(properties.maxNumberOfVirtualNetworkLinks), 1),
    RegistrationLinks,
    ResourceGroup = resourceGroup
| order by Links asc, RecordSetPct desc
"""
    resolvers_q = """
resources
| where type =~ 'microsoft.network/dnsresolvers'
| project id,
    State = tostring(properties.dnsResolverState),
    Vnet = tostring(split(tostring(properties.virtualNetwork.id), '/')[8]),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup, Location = location
"""
    kv_q = Q_KEYVAULTS + """
| project id,
    Sku = tostring(properties.sku.name),
    Rbac = tostring(properties.enableRbacAuthorization),
    SoftDelete = tostring(properties.enableSoftDelete),
    PurgeProtection = tostring(properties.enablePurgeProtection),
    PublicNetwork = tostring(properties.publicNetworkAccess),
    PrivateEndpoints = array_length(properties.privateEndpointConnections),
    ResourceGroup = resourceGroup, Location = location
"""
    yes_good = lambda col: status_fmt(col, good=["true"], warn=["false", ""])
    return group("tab-shared", [
        params("shared-params", [
            resource_param("Bastions", "Bastions", Q_BASTIONS),
            resource_param("KeyVaults", "Key vaults", Q_KEYVAULTS),
            resource_param("PublicIps", "Public IPs", Q_PUBLIC_IPS),
        ]),
        text("shared-bastion-h", "### Azure Bastion"),
        arg("shared-bastions", "Bastion hosts", bastion_q, formatters=[resource_link(), PROVISIONING],
            labels={"id": "Bastion"}, no_data="No Bastion hosts found."),
        metric_grid("shared-bastion-kpis", "Bastion metrics (over time range)", bns, "Bastions", [
            ("pingmesh", AVG, "Communication status", None),
            ("sessions", SUM, "Sessions", None),
            ("usage_user", AVG, "CPU usage", None),
            ("used", AVG, "Memory used", None),
        ], width=50),
        metrics("shared-bastion-sessions", "Bastion sessions", bns, "Bastions", [m(bns, "sessions", SUM)], width=50),
        text("shared-ddos-h", "### DDoS Protection"),
        arg("shared-ddos-coverage", "Coverage", ddos_coverage_q, vis="tiles",
            tiles=state_tiles("Signal", "State", "Display"), width=40),
        arg("shared-ddos-plans", "DDoS protection plans", ddos_plans_q, formatters=[resource_link(), PROVISIONING],
            labels={"id": "Plan"}, no_data="No DDoS protection plans found.", width=60),
        metrics("shared-ddos-attack", "Under DDoS attack (1 = yes)", pns, "PublicIps", [m(pns, "IfUnderDDoSAttack", MAX)], width=50),
        metrics("shared-ddos-dropped", "Packets dropped by DDoS mitigation", pns, "PublicIps",
                [m(pns, "PacketsDroppedDDoS", MAX)], width=50),
        text("shared-dns-h", "### DNS"),
        arg("shared-dns-resolvers", "DNS Private Resolvers", resolvers_q, formatters=[
            resource_link(), PROVISIONING, status_fmt("State", good=["Connected"], bad=["Disconnected"]),
        ], labels={"id": "Resolver"}, no_data="No DNS Private Resolvers found."),
        arg("shared-dns-zones", "Private DNS zones (limits & links)", dns_zones_q, formatters=[
            resource_link(), low_is_good("RecordSetPct", 70, 90), low_is_good("LinkPct", 70, 90),
            high_is_good("Links", 1, 1),
        ], labels={"id": "Zone", "RecordSetPct": "Record sets % of limit", "LinkPct": "VNet links % of limit"},
            no_data="No Private DNS zones found."),
        text("shared-kv-h", "### Key Vault"),
        metric_grid("shared-kv-kpis", "Key Vault metrics (over time range)", kns, "KeyVaults", [
            ("Availability", AVG, "Availability %", ("high", 99.9, 99)),
            ("SaturationShoebox", AVG, "Saturation %", ("low", 75, 90)),
            ("ServiceApiLatency", AVG, "Latency (ms)", ("low", 200, 1000)),
            ("ServiceApiHit", COUNT, "API hits", None),
        ]),
        metrics("shared-kv-results", "API results by status code", kns, "KeyVaults",
                [m(kns, "ServiceApiResult", COUNT, split="StatusCode")], width=50),
        metrics("shared-kv-availability", "Availability %", kns, "KeyVaults", [m(kns, "Availability", AVG)], width=50),
        arg("shared-kv-inventory", "Key vaults", kv_q, formatters=[
            resource_link(), yes_good("SoftDelete"), yes_good("PurgeProtection"), yes_good("Rbac"),
            status_fmt("PublicNetwork", good=["Disabled"], warn=["Enabled"]),
        ], labels={"id": "Key vault"}, no_data="No key vaults found."),
    ], tab="shared")


def buildagents_tab():
    vmss = "microsoft.compute/virtualmachinescalesets"
    inventory_q = Q_AGENT_VMSS + """
| project id = tolower(id),
    Sku = tostring(sku.name),
    Capacity = tolong(sku.capacity),
    Orchestration = tostring(properties.orchestrationMode),
    Image = coalesce(tostring(split(tostring(properties.virtualMachineProfile.storageProfile.imageReference.id), '/')[10]),
        strcat(tostring(properties.virtualMachineProfile.storageProfile.imageReference.offer), ' ',
            tostring(properties.virtualMachineProfile.storageProfile.imageReference.sku))),
    Overprovision = tostring(properties.overprovision),
    UpgradePolicy = tostring(properties.upgradePolicy.mode),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup, Location = location
| join kind=leftouter (
    computeresources
    | where type =~ 'microsoft.compute/virtualmachinescalesets/virtualmachines'
    | extend id = tolower(strcat_array(array_slice(split(id, '/'), 0, 8), '/')),
        power = tostring(properties.extended.instanceView.powerState.code)
    | summarize Running = countif(power =~ 'PowerState/running'),
        Deallocated = countif(power =~ 'PowerState/deallocated'),
        Failed = countif(tostring(properties.provisioningState) =~ 'Failed') by id
  ) on id
| project-away id1
"""
    heartbeat_q = """
Heartbeat
| where TimeGenerated {TimeRange}
| where _ResourceId has '/virtualmachinescalesets/'
| extend ScaleSet = tostring(split(_ResourceId, '/')[8])
| where ScaleSet matches regex @'{BuildAgentPattern}'
| summarize LastHeartbeat = max(TimeGenerated) by ScaleSet, Computer
| extend Status = iff(LastHeartbeat < ago(15m), 'Silent', 'Reporting')
| order by Status asc, ScaleSet asc
"""
    disk_q = """
InsightsMetrics
| where TimeGenerated {TimeRange}
| where Namespace == 'LogicalDisk' and Name == 'FreeSpacePercentage'
| where _ResourceId has '/virtualmachinescalesets/'
| extend ScaleSet = tostring(split(_ResourceId, '/')[8]), Disk = tostring(parse_json(Tags)['vm.azm.ms/mountId'])
| where ScaleSet matches regex @'{BuildAgentPattern}'
| summarize arg_max(TimeGenerated, Val) by ScaleSet, Computer, Disk
| project ScaleSet, Computer, Disk, FreePercent = round(Val, 1), Updated = TimeGenerated
| order by FreePercent asc
"""
    return group("tab-buildagents", [
        text("agents-intro",
             "Build agent scale sets are found by **name** using the *Build agent name pattern* parameter at the top. "
             "Azure DevOps scale set agent pools expect **Overprovision = false** and **Upgrade policy = Manual**.", "info"),
        params("agents-params", [resource_param("AgentScaleSets", "Agent scale sets", Q_AGENT_VMSS)]),
        arg("agents-inventory", "Agent scale sets", inventory_q, formatters=[
            resource_link(), PROVISIONING,
            status_fmt("Overprovision", good=["false"], warn=["true"]),
            status_fmt("UpgradePolicy", good=["Manual"], warn=["Automatic", "Rolling"]),
            low_is_good("Failed", 1, 1),
        ], labels={"id": "Scale set"}, no_data="No scale sets matched the build agent name pattern."),
        metric_grid("agents-kpis", "Scale set metrics (over time range)", vmss, "AgentScaleSets", [
            ("Percentage CPU", AVG, "Avg CPU %", ("low", 80, 95)),
            ("Available Memory Percentage", AVG, "Avg free memory %", ("high", 20, 10)),
            ("OS Disk IOPS Consumed Percentage", AVG, "OS disk IOPS used %", ("low", 80, 95)),
            ("OS Disk Queue Depth", AVG, "OS disk queue depth", None),
            ("VmAvailabilityMetric", AVG, "VM availability", None),
        ]),
        metrics("agents-cpu", "CPU %", vmss, "AgentScaleSets", [m(vmss, "Percentage CPU", AVG)], width=50),
        metrics("agents-mem", "Available memory %", vmss, "AgentScaleSets", [m(vmss, "Available Memory Percentage", AVG)], width=50),
        metrics("agents-disk", "OS disk IOPS consumed %", vmss, "AgentScaleSets",
                [m(vmss, "OS Disk IOPS Consumed Percentage", AVG)], width=50),
        metrics("agents-net", "Network in / out", vmss, "AgentScaleSets",
                [m(vmss, "Network In Total", SUM), m(vmss, "Network Out Total", SUM)], width=50),
        la("agents-heartbeat", "Agent heartbeats (Azure Monitor Agent)", heartbeat_q, width=50,
           formatters=[status_fmt("Status", good=["Reporting"], bad=["Silent"])],
           no_data="No heartbeats — is the Azure Monitor Agent deployed to the agent scale sets?"),
        la("agents-diskfree", "Free disk space (VM insights)", disk_q, width=50,
           formatters=[high_is_good("FreePercent", 20, 10)],
           no_data="No disk data — requires VM insights on the agent scale sets."),
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
            ("DiskUsedPercentage", AVG, "vSAN used %", ("low", 70, 75)),
            ("UsedLatest", AVG, "Datastore used", None),
            ("CapacityLatest", AVG, "Datastore capacity", None),
        ]),
        metrics("avs-cpu", "CPU % by cluster", ns, "PrivateClouds",
                [m(ns, "EffectiveCpuAverage", AVG, split="clustername")], width=50),
        metrics("avs-mem", "Memory % by cluster", ns, "PrivateClouds",
                [m(ns, "UsageAverage", AVG, split="clustername")], width=50),
        metrics("avs-disk", "vSAN datastore used % by datastore", ns, "PrivateClouds",
                [m(ns, "DiskUsedPercentage", AVG, split="dsname")]),
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
    hosts_q = AVD_LATEST_HOSTS + """
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
    return group("tab-avd", [
        arg("avd-pools", "Host pools", pools_q, formatters=[resource_link()], labels={"id": "Host pool"},
            no_data="No AVD host pools found."),
        text("avd-workspace-hint", "Select the **Log Analytics workspace** that receives AVD diagnostics to see "
             "session host health, sessions, errors and connection quality.", "info", visible_when=WORKSPACE_UNSET),
        la("avd-host-tiles", "Session host status", AVD_STATUS_TILES_Q, vis="tiles", tiles=AVD_STATUS_TILES),
        la("avd-hosts", "Session hosts (latest heartbeat)", hosts_q, formatters=[AVD_HOST_STATUS],
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


def governance_tab():
    compliance_q = """
policyresources
| where type =~ 'microsoft.policyinsights/policystates'
| summarize Total = dcount(tostring(properties.resourceId)),
    NonCompliant = dcountif(tostring(properties.resourceId), tostring(properties.complianceState) =~ 'NonCompliant')
    by subscriptionId
| extend CompliancePct = round(100.0 * (Total - NonCompliant) / Total, 1)
""" + SUBSCRIPTION_NAMES + """
| project Subscription = coalesce(Subscription, subscriptionId), CompliancePct, NonCompliant, Total
| order by CompliancePct asc
"""
    noncompliant_q = """
policyresources
| where type =~ 'microsoft.policyinsights/policystates'
| where tostring(properties.complianceState) =~ 'NonCompliant'
| extend assignmentId = tolower(tostring(properties.policyAssignmentId)),
    definitionId = tolower(tostring(properties.policyDefinitionId))
| summarize Resources = dcount(tostring(properties.resourceId)) by assignmentId, definitionId
| join kind=leftouter (
    policyresources
    | where type =~ 'microsoft.authorization/policyassignments'
    | project assignmentId = tolower(id), Assignment = tostring(properties.displayName)
  ) on assignmentId
| join kind=leftouter (
    policyresources
    | where type =~ 'microsoft.authorization/policydefinitions'
    | project definitionId = tolower(id), Policy = tostring(properties.displayName)
  ) on definitionId
| project Assignment = coalesce(Assignment, tostring(split(assignmentId, '/')[-1])),
    Policy = coalesce(Policy, tostring(split(definitionId, '/')[-1])),
    Resources
| order by Resources desc
"""
    score_q = """
securityresources
| where type =~ 'microsoft.security/securescores'
| project subscriptionId, ScorePct = round(100 * toreal(properties.score.percentage), 0),
    Current = toreal(properties.score.current), Max = toreal(properties.score.max)
""" + SUBSCRIPTION_NAMES + """
| project Subscription = coalesce(Subscription, subscriptionId), ScorePct, Current, Max
| order by ScorePct asc
"""
    controls_q = """
securityresources
| where type =~ 'microsoft.security/securescores/securescorecontrols'
| extend Unhealthy = toint(properties.unhealthyResourceCount)
| where Unhealthy > 0
| summarize Unhealthy = sum(Unhealthy), AvgScorePct = round(100 * avg(toreal(properties.score.percentage)), 0)
    by Control = tostring(properties.displayName)
| order by Unhealthy desc
"""
    alerts_q = """
securityresources
| where type =~ 'microsoft.security/locations/alerts'
| where tostring(properties.Status) =~ 'Active'
| project Severity = tostring(properties.Severity), Alert = tostring(properties.AlertDisplayName),
    Entity = tostring(properties.CompromisedEntity), Started = todatetime(properties.StartTimeUtc),
    Tactics = strcat_array(properties.Intent, ', ')
| order by case(Severity =~ 'High', 0, Severity =~ 'Medium', 1, 2) asc, Started desc
"""
    recs_q = """
securityresources
| where type =~ 'microsoft.security/assessments'
| where tostring(properties.status.code) =~ 'Unhealthy'
| extend Severity = tostring(properties.metadata.severity)
| where Severity in~ ('High', 'Medium')
| summarize Resources = count() by Recommendation = tostring(properties.displayName), Severity
| order by case(Severity =~ 'High', 0, 1) asc, Resources desc
"""
    advisor_q = """
advisorresources
| where type =~ 'microsoft.advisor/recommendations'
| extend Category = tostring(properties.category), Impact = tostring(properties.impact)
| where Impact in~ ('High', 'Medium')
| project Category = iff(Category =~ 'HighAvailability', 'Reliability', Category), Impact,
    Problem = tostring(properties.shortDescription.problem),
    Resource = tostring(properties.resourceMetadata.resourceId),
    Updated = todatetime(properties.lastUpdated)
| order by case(Impact =~ 'High', 0, 1) asc, Category asc
"""
    sev_fmt = status_fmt("Severity", warn=["Medium"], bad=["High"], neutral=["Low", "Informational"])
    return group("tab-governance", [
        text("gov-policy-h", "### Azure Policy"),
        arg("gov-compliance", "Compliance by subscription", compliance_q,
            formatters=[high_is_good("CompliancePct", 90, 70)], labels={"CompliancePct": "Compliant %"}, width=40),
        arg("gov-noncompliant", "Non-compliant policies", noncompliant_q, width=60,
            no_data="No non-compliant resources."),
        text("gov-defender-h", "### Microsoft Defender for Cloud"),
        arg("gov-score", "Secure score by subscription", score_q,
            formatters=[high_is_good("ScorePct", 80, 50)], labels={"ScorePct": "Score %"}, width=40),
        arg("gov-controls", "Security controls with unhealthy resources", controls_q, width=60),
        arg("gov-alerts", "Active security alerts", alerts_q, formatters=[sev_fmt], no_data="No active security alerts."),
        arg("gov-recs", "Unhealthy recommendations (high & medium)", recs_q, formatters=[sev_fmt]),
        text("gov-advisor-h", "### Azure Advisor"),
        arg("gov-advisor", "High & medium impact recommendations", advisor_q, group_by="Category",
            formatters=[resource_link("Resource"), status_fmt("Impact", warn=["Medium"], bad=["High"])]),
    ], tab="governance")


def management_tab():
    workspaces_q = """
resources
| where type =~ 'microsoft.operationalinsights/workspaces'
| project id,
    Sku = tostring(properties.sku.name),
    RetentionDays = toint(properties.retentionInDays),
    DailyCapGB = iff(todouble(properties.workspaceCapping.dailyQuotaGb) < 0, real(null), todouble(properties.workspaceCapping.dailyQuotaGb)),
    Ingestion = tostring(properties.workspaceCapping.dataIngestionStatus),
    PublicIngestion = tostring(properties.publicNetworkAccessForIngestion),
    ResourceGroup = resourceGroup, Location = location
"""
    ingestion_q = """
Usage
| where TimeGenerated {TimeRange}
| where IsBillable == true
| summarize GB = sum(Quantity) / 1000 by bin(TimeGenerated, {TimeRange:grain}), DataType
"""
    top_tables_q = """
Usage
| where TimeGenerated {TimeRange}
| where IsBillable == true
| summarize GB = round(sum(Quantity) / 1000, 2) by DataType
| top 15 by GB desc
"""
    operation_q = """
Operation
| where TimeGenerated {TimeRange}
| where OperationStatus in~ ('Warning', 'Error')
| summarize Count = count(), LastSeen = max(TimeGenerated), Detail = take_any(Detail)
    by OperationStatus, OperationCategory
| order by OperationStatus asc, Count desc
"""
    silent_q = """
Heartbeat
| where TimeGenerated {TimeRange}
| summarize LastHeartbeat = max(TimeGenerated) by Computer, Category, ResourceId = _ResourceId
| extend Status = iff(LastHeartbeat < ago(15m), 'Silent', 'Reporting')
| order by Status asc, LastHeartbeat asc
"""
    vaults_q = """
resources
| where type =~ 'microsoft.recoveryservices/vaults'
| project id,
    Redundancy = tostring(properties.redundancySettings.standardTierStorageRedundancy),
    CrossRegionRestore = tostring(properties.redundancySettings.crossRegionRestore),
    SoftDelete = tostring(properties.securitySettings.softDeleteSettings.softDeleteState),
    Immutability = tostring(properties.securitySettings.immutabilitySettings.state),
    PublicNetwork = tostring(properties.publicNetworkAccess),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup, Location = location
"""
    items_q = """
recoveryservicesresources
| where type =~ 'microsoft.recoveryservices/vaults/backupfabrics/protectioncontainers/protecteditems'
| project Vault = tostring(split(id, '/')[8]),
    Item = tostring(properties.friendlyName),
    WorkloadType = tostring(properties.workloadType),
    Health = tostring(properties.healthStatus),
    LastBackup = tostring(properties.lastBackupStatus),
    LastBackupTime = todatetime(properties.lastBackupTime),
    Protection = tostring(properties.protectionState)
| order by case(LastBackup =~ 'Failed', 0, Health !~ 'Passed', 1, 2) asc, LastBackupTime asc
"""
    jobs_q = """
recoveryservicesresources
| where type =~ 'microsoft.recoveryservices/vaults/backupjobs'
| where todatetime(properties.startTime) >= todatetime('{TimeRange:startISO}')
| where tostring(properties.status) !~ 'Completed'
| project Vault = tostring(split(id, '/')[8]),
    Item = tostring(properties.entityFriendlyName),
    Operation = tostring(properties.operation),
    Status = tostring(properties.status),
    Started = todatetime(properties.startTime),
    Error = tostring(properties.extendedInfo.propertyBag['Error Code'])
| order by Started desc
"""
    asr_q = """
recoveryservicesresources
| where type =~ 'microsoft.recoveryservices/vaults/replicationfabrics/replicationprotectioncontainers/replicationprotecteditems'
| project Vault = tostring(split(id, '/')[8]),
    Item = tostring(properties.friendlyName),
    Health = tostring(properties.replicationHealth),
    State = tostring(properties.protectionStateDescription),
    ActiveLocation = tostring(properties.activeLocation)
| order by case(Health =~ 'Critical', 0, Health =~ 'Warning', 1, 2) asc
"""
    return group("tab-management", [
        text("mgmt-la-h", "### Log Analytics"),
        arg("mgmt-workspaces", "Workspaces", workspaces_q, formatters=[
            resource_link(),
            status_fmt("Ingestion", good=["RespectQuota"], warn=["ApproachingQuota"], bad=["OverQuota", "ForceOff", "SubscriptionSuspended"]),
        ], labels={"id": "Workspace"}),
        text("mgmt-la-hint", "Select a **Log Analytics workspace** at the top to see ingestion, workspace errors and "
             "agent heartbeats.", "info", visible_when=WORKSPACE_UNSET),
        la("mgmt-ingestion", "Billable ingestion by table (GB)", ingestion_q, vis="barchart", width=60),
        la("mgmt-top-tables", "Top tables (GB)", top_tables_q, width=40),
        la("mgmt-operation", "Workspace health issues (Operation table)", operation_q,
           formatters=[status_fmt("OperationStatus", warn=["Warning"], bad=["Error"])],
           no_data="No workspace warnings or errors.", width=50),
        la("mgmt-heartbeat", "Agent heartbeats", silent_q, width=50,
           formatters=[status_fmt("Status", good=["Reporting"], bad=["Silent"]), resource_link("ResourceId")]),
        text("mgmt-backup-h", "### Backup & Site Recovery"),
        arg("mgmt-vaults", "Recovery Services vaults", vaults_q, formatters=[
            resource_link(), PROVISIONING,
            status_fmt("SoftDelete", good=["AlwaysON", "Enabled"], warn=["Disabled"]),
            status_fmt("Immutability", good=["Locked", "Unlocked"], warn=["Disabled", ""]),
        ], labels={"id": "Vault"}, no_data="No Recovery Services vaults found."),
        arg("mgmt-backup-jobs", "Backup jobs not completed (time range)", jobs_q,
            formatters=[status_fmt("Status", warn=["InProgress", "CompletedWithWarnings", "Cancelled"], bad=["Failed"])],
            no_data="All backup jobs in the time range completed.", width=50),
        arg("mgmt-backup-items", "Protected items", items_q, formatters=[
            status_fmt("Health", good=["Passed"], warn=["ActionSuggested"], bad=["ActionRequired"]),
            status_fmt("LastBackup", good=["Healthy"], bad=["Failed", "IRPending"]),
        ], no_data="No protected items.", width=50),
        arg("mgmt-asr", "Site Recovery replicated items", asr_q,
            formatters=[status_fmt("Health", good=["Normal"], warn=["Warning"], bad=["Critical"])],
            no_data="No Site Recovery replicated items."),
    ], tab="management")


def throughput_tab():
    fw, hub = "microsoft.network/azurefirewalls", "microsoft.network/virtualhubs"
    er, erg = "microsoft.network/expressroutecircuits", "microsoft.network/expressroutegateways"
    vpn, p2s = "microsoft.network/vpngateways", "microsoft.network/p2svpngateways"
    st = "microsoft.storage/storageaccounts"
    avd_bw_q = """
WVDConnectionNetworkData
| where TimeGenerated {TimeRange}
| summarize AvgBandwidth_KBps = avg(EstAvailableBandwidthKBps) by bin(TimeGenerated, {TimeRange:grain})
"""
    return group("tab-throughput", [
        text("tp-intro", "Traffic across the platform's network edge and data services for the selected time range.", "info"),
        params("tp-params", [
            resource_param("TpHubs", "Hubs", Q_HUBS, hidden_when_locked=True),
            resource_param("TpFirewalls", "Firewalls", Q_FIREWALLS, hidden_when_locked=True),
            resource_param("TpCircuits", "Circuits", Q_CIRCUITS, hidden_when_locked=True),
            resource_param("TpErGateways", "ER gateways", Q_ER_GATEWAYS, hidden_when_locked=True),
            resource_param("TpVpnGateways", "VPN gateways", Q_VPN_GATEWAYS, hidden_when_locked=True),
            resource_param("TpP2SGateways", "P2S gateways", Q_P2S_GATEWAYS, hidden_when_locked=True),
            resource_param("TpStorage", "Storage accounts", Q_STORAGE, hidden_when_locked=True),
        ]),
        metrics("tp-hub", "vWAN hub router data processed", hub, "TpHubs", [m(hub, "VirtualHubDataProcessed", SUM)], width=50),
        metrics("tp-fw", "Azure Firewall throughput", fw, "TpFirewalls", [m(fw, "Throughput", AVG)], width=50),
        metrics("tp-er", "ExpressRoute circuits (bits/s in & out)", er, "TpCircuits",
                [m(er, "BitsInPerSecond", AVG), m(er, "BitsOutPerSecond", AVG)], width=50),
        metrics("tp-er-gw", "ExpressRoute gateway throughput (bits/s)", erg, "TpErGateways",
                [m(erg, "ExpressRouteGatewayBitsPerSecond", AVG)], width=50),
        metrics("tp-vpn", "VPN gateway S2S bandwidth", vpn, "TpVpnGateways", [m(vpn, "AverageBandwidth", AVG)], width=50),
        metrics("tp-vpn-tunnels", "VPN tunnel bandwidth by connection", vpn, "TpVpnGateways",
                [m(vpn, "TunnelAverageBandwidth", AVG, split="ConnectionName")], width=50),
        metrics("tp-p2s", "P2S VPN bandwidth", p2s, "TpP2SGateways", [m(p2s, "P2SBandwidth", AVG)], width=50),
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
            "description": "The central platform workspace. Enables the log-based panels.",
        },
        {
            "id": gid("param-BuildAgentPattern"),
            "version": "KqlParameterItem/1.0",
            "name": "BuildAgentPattern",
            "label": "Build agent name pattern",
            "type": 1,
            "isRequired": True,
            "value": "(?i)(agent|build|ado|devops|runner)",
            "description": "Regex matched against scale set names to identify build agent pools.",
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
                 "Health, capacity and throughput of the shared platform: Virtual WAN connectivity (Firewall, "
                 "ExpressRoute, VPN), shared services, Azure VMware Solution, Azure Virtual Desktop, storage, "
                 "build agents, governance, monitoring and backup."),
            global_params(),
            tabs(),
            overview_tab(),
            vwan_tab(),
            firewall_tab(),
            expressroute_tab(),
            vpn_tab(),
            shared_tab(),
            buildagents_tab(),
            avs_tab(),
            avd_tab(),
            storage_tab(),
            governance_tab(),
            management_tab(),
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
