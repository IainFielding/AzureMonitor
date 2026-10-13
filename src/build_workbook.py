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


def _with_digits(fmt, digits):
    if digits is not None:
        fmt["numberFormat"] = {"unit": 0, "options": {"style": "decimal", "maximumFractionDigits": digits}}
    return fmt


def low_is_good(col, warn, crit, digits=None):
    """Icon formatter for numeric columns where higher values are worse (CPU, SNAT...)."""
    return _with_digits({"columnMatch": col, "formatter": 18, "formatOptions": _icons([
        _t(">=", str(crit), "4"),
        _t(">=", str(warn), "2"),
        _t("Default", None, "success"),
    ])}, digits)


def high_is_good(col, warn, crit, digits=None):
    """Icon formatter for numeric columns where lower values are worse (availability...)."""
    return _with_digits({"columnMatch": col, "formatter": 18, "formatOptions": _icons([
        _t("<", str(crit), "4"),
        _t("<", str(warn), "2"),
        _t("Default", None, "success"),
    ])}, digits)


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


# Items with few rows: size to content ("Full") rather than reserving a fixed medium-height panel.
FULL_HEIGHT = {
    "vwan-wans", "vwan-hubs", "vwan-kpis", "firewall-inventory", "firewall-kpis",
    "er-circuits", "er-circuit-kpis", "er-gateways", "er-connections", "er-gw-kpis",
    "vpn-sites", "vpn-connections", "shared-bastions", "shared-bastion-kpis", "shared-ddos-plans",
    "shared-dns-resolvers", "conn-monitors", "avs-inventory", "avs-kpis", "agents-inventory", "agents-kpis", "agw-inventory", "agw-kpis", "afd-inventory", "afd-kpis", "identity-kpis",
    "sec-score", "mgmt-vaults",
}


def _query(name, title, query, *, query_type, resource_type, resources, vis="table",
           formatters=None, labels=None, tiles=None, chart=None, width=None, size=0,
           no_data=None, group_by=None, visible_when=None, time=False):
    content = {
        "version": "KqlItem/1.0",
        "query": query.strip(),
        "size": 3 if name in FULL_HEIGHT else size,
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


def arm(name, title, path, api_version, columns, *, sort_desc=None, no_data=None, width=None,
        body=None, table="$.value", formatters=None, labels=None):
    """Call Azure Resource Manager: GET, or POST when a body is given.

    columns: list of (column, JSONPath, type-or-None), each path relative to a row of `table`.
    """
    request = {
        "version": "ARMEndpoint/1.0", "data": json.dumps(body) if body else None, "headers": [],
        "method": "POST" if body else "GET", "path": path,
        "urlParams": [{"key": "api-version", "value": api_version}], "batchDisabled": False,
        "transformers": [{"type": "jsonpath", "settings": {"tablePath": table, "columns": [
            {"path": jp, "columnid": col, **({"columnType": kind} if kind else {})} for col, jp, kind in columns]}}],
    }
    grid = {"formatters": formatters or [], "filter": True}
    if labels:
        grid["labelSettings"] = [{"columnId": k, "label": v} for k, v in labels.items()]
    if sort_desc:
        grid["sortBy"] = [{"itemKey": sort_desc, "sortOrder": 2}]
    content = {"version": "KqlItem/1.0", "query": json.dumps(request), "size": 0, "title": title, "queryType": 12,
               "visualization": "table", "showExportToExcel": True, "gridSettings": grid}
    if no_data:
        content["noDataMessage"] = no_data
    item = {"type": 3, "content": content, "name": name}
    if width:
        item["customWidth"] = str(width)
    return item


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
            width=None, size=0, tiles=None, visible_when=None):
    content = {
        "chartId": "workbook" + gid(name),
        "version": "MetricsItem/2.0",
        "size": 3 if name in FULL_HEIGHT else size,
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
        # No gridFormatType: the default is one row per resource with a column per metric.
        timelines = [{"columnMatch": f"{s['metric']} Timeline$", "formatter": 21,
                      "formatOptions": {"palette": "blue"}} for s in specs]
        timeline_labels = {f"{k} Timeline": f"{v} trend" for k, v in (labels or {}).items()}
        content["gridSettings"] = {
            "formatters": [hidden("Subscription"), resource_link("Name")] + timelines + (formatters or []),
            "labelSettings": [{"columnId": k, "label": v}
                              for k, v in {**(labels or {}), **timeline_labels, "Name": "Resource"}.items()],
            "filter": True,
        }
    if tiles:
        # One tile per resource and metric; the rows carry Metric, Value, Timeline and Name (the resource).
        content.update({"chartType": -1, "gridFormatType": 1, "tileSettings": tiles, "size": 3})
    item = {"type": 10, "content": content, "name": name}
    if width:
        item["customWidth"] = str(width)
    if visible_when:
        item["conditionalVisibility"] = visible_when
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
Q_STORAGE = ("resources\n| where type =~ 'microsoft.storage/storageaccounts'"
             "\n| where name matches regex @'{StoragePattern}' or resourceGroup matches regex @'{StoragePattern}'")
Q_AGENT_VMSS = ("resources\n| where type =~ 'microsoft.compute/virtualmachinescalesets'"
                "\n| where name matches regex @'{BuildAgentPattern}'")
Q_DC_VMS = ("resources\n| where type =~ 'microsoft.compute/virtualmachines'"
            "\n| where name matches regex @'{DcPattern}'")
Q_APP_GATEWAYS = "resources\n| where type =~ 'microsoft.network/applicationgateways'"
Q_FRONT_DOORS = ("resources\n| where type =~ 'microsoft.cdn/profiles'"
                 "\n| where tostring(sku.name) contains 'AzureFrontDoor'")
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
    "microsoft.cdn/profiles",          # Front Door Standard and Premium (other CDN profiles are filtered out)
    "microsoft.network/frontdoors",    # Front Door classic
]
TYPE_LIST = ", ".join(f"'{t}'" for t in PLATFORM_TYPES)

# Maps a resource `type` (and `gatewayType`, for virtual network gateways) to the Service shown on the Overview.
SERVICE_CASE = """| extend Service = case(
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
    type in~ ('microsoft.cdn/profiles', 'microsoft.network/frontdoors'), 'Front Door',
    'Build Agents')"""

# Every platform resource we care about, tagged with a Service, joined to Resource Health.
# Resource Health in ARG only covers some types, so a config-derived status is used as fallback.
Q_INVENTORY_HEALTH = f"""
resources
| where type in~ ({TYPE_LIST})
| where type !~ 'microsoft.compute/virtualmachinescalesets' or name matches regex @'{{BuildAgentPattern}}'
| where type !~ 'microsoft.cdn/profiles' or tostring(sku.name) contains 'AzureFrontDoor'
| extend gatewayType = tostring(properties.gatewayType)
{SERVICE_CASE}
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
    ("policy", "%", """
policyresources
| where type =~ 'microsoft.policyinsights/policystates'
| summarize Total = dcount(tostring(properties.resourceId)),
    Bad = dcountif(tostring(properties.resourceId), tostring(properties.complianceState) =~ 'NonCompliant')
| project Signal = 'Policy compliance',
    Value = iff(Total == 0, real(null), round(100.0 * (Total - Bad) / Total, 1)),
    Detail = strcat(Bad, ' non-compliant resources'),
    State = case(Total == 0, 'Unknown', Bad == 0, 'Available', 'Degraded')
"""),
    ("defender", "%", """
securityresources
| where type in~ ('microsoft.security/securescores', 'microsoft.security/locations/alerts')
| extend isScore = type =~ 'microsoft.security/securescores',
    isActiveAlert = type =~ 'microsoft.security/locations/alerts' and tostring(properties.Status) =~ 'Active'
| summarize Score = avgif(toreal(properties.score.percentage), isScore), Subs = countif(isScore),
    Alerts = countif(isActiveAlert), High = countif(isActiveAlert and tostring(properties.Severity) =~ 'High')
| project Signal = 'Defender for Cloud',
    Value = iff(Subs == 0, real(null), round(Score * 100, 0)),
    Detail = strcat('secure score · ', Alerts, ' alerts (', High, ' high)'),
    State = case(High > 0, 'Unavailable', Subs == 0, 'Unknown', Score < 0.5, 'Unavailable', Score < 0.8 or Alerts > 0, 'Degraded', 'Available')
"""),
    ("advisor", "", """
advisorresources
| where type =~ 'microsoft.advisor/recommendations'
| where tostring(properties.impact) =~ 'High'
| summarize Problems = dcount(tostring(properties.shortDescription.problem)), Total = count(),
    Reliability = countif(tostring(properties.category) =~ 'HighAvailability')
| project Signal = 'Advisor high-impact issues', Value = Problems,
    Detail = strcat(Total, ' affected resources (', Reliability, ' reliability)'),
    State = case(Reliability > 0, 'Degraded', 'Available')
"""),
    ("backup", "", """
recoveryservicesresources
| where type =~ 'microsoft.recoveryservices/vaults/backupjobs'
| where todatetime(properties.startTime) > ago(1d)
| summarize Failed = countif(tostring(properties.status) =~ 'Failed'), Jobs = count()
| project Signal = 'Backup jobs (24h)', Value = Failed,
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
| extend Status = iff(TimeGenerated < ago(30m), 'Offline', Status)
"""
AVD_STATUS_TILES_Q = AVD_LATEST_HOSTS + "| summarize Hosts = count() by Status\n| order by Hosts desc"
# 'Offline' = no heartbeat for 30 min, which is normal for deallocated hosts (Start VM on Connect).
AVD_HOST_STATES = dict(good=["Available"], warn=["Upgrading", "NeedsAssistance"],
                       bad=["Unavailable", "UpgradeFailed", "NoHeartbeat"], neutral=["Offline", "Shutdown"])
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
    ("firewall", "Firewall"),
    ("expressroute", "ExpressRoute"),
    ("vpn", "VPN"),
    ("connectivity", "Connectivity"),
    ("appdelivery", "App Delivery"),
    ("shared", "Shared"),
    ("identity", "Identity"),
    ("buildagents", "Agents"),
    ("avs", "AVS"),
    ("avd", "AVD"),
    ("storage", "Storage"),
    ("governance", "Governance"),
    ("security", "Security"),
    ("management", "Monitoring & Backup"),
    ("capacity", "Capacity"),
    ("throughput", "Throughput"),
]


# Width (%) of a slot that holds one tile. A tile has a fixed pixel width, so a slot narrower than its tile gets
# a horizontal scroll bar; these are the narrowest slots on the page and stay wider than a tile until the page
# itself is under about 1,000 pixels. Prefer one full-width item with many tiles where the queries allow it.
GLANCE_WIDTH = 20
AVS_TILE_WIDTH = 25


def big_number_tiles(title_col, state_col, value_col, detail_col, unit=""):
    t = state_tiles(title_col, state_col, value_col, detail_col)
    t["rightContent"] = {"columnMatch": value_col, "formatter": 12, "formatOptions": {"palette": "none"}}
    if unit == "%":
        t["rightContent"]["numberFormat"] = {"unit": 1, "options": {"style": "decimal", "maximumFractionDigits": 0}}
    return t


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


def metric_tiles(warn, crit):
    """Tile layout for a percentage metric where higher is worse: status icon, value, resource and trend."""
    return {
        "titleContent": {"columnMatch": "Metric", "formatter": 1},
        "subtitleContent": {"columnMatch": "Name", "formatter": 13,
                            "formatOptions": {"linkTarget": "Resource", "showIcon": False}},
        "leftContent": {"columnMatch": "Value", "formatter": 18, "formatOptions": _icons([
            _t(">=", str(crit), "4", ICON_ONLY), _t(">=", str(warn), "2", ICON_ONLY),
            _t("Default", None, "success", ICON_ONLY)])},
        "rightContent": {"columnMatch": "Value", "formatter": 12, "formatOptions": {"palette": "none"},
                         "numberFormat": {"unit": 1, "options": {"style": "decimal", "maximumFractionDigits": 0}}},
        "secondaryContent": {"columnMatch": "Timeline", "formatter": 21, "formatOptions": {"palette": "blue"}},
        "showBorder": True,
    }


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
    # Change Analysis keeps 14 days, so longer time ranges show at most that.
    changes_q = f"""
resourcechanges
| extend Time = todatetime(properties.changeAttributes.timestamp)
| where Time >= todatetime('{{TimeRange:startISO}}')
| extend id = tolower(tostring(properties.targetResourceId)),
    type = tolower(tostring(properties.targetResourceType)), gatewayType = ''
| where type in~ ({TYPE_LIST})
| where type !~ 'microsoft.compute/virtualmachinescalesets' or tostring(split(id, '/')[8]) matches regex @'{{BuildAgentPattern}}'
{SERVICE_CASE}
| project Time, id, Service, ChangeType = tostring(properties.changeType),
    Properties = strcat_array(bag_keys(properties.changes), ', '),
    ChangedBy = tostring(properties.changeAttributes.changedBy),
    Client = tostring(properties.changeAttributes.clientType),
    Operation = tostring(properties.changeAttributes.operation)
| order by Time desc
| take 500
"""
    # Resource Health transitions. The change record targets <resource>/providers/Microsoft.ResourceHealth/...,
    # so the resource type is read back out of the id.
    health_history_q = f"""
healthresourcechanges
| where tostring(properties.targetResourceType) =~ 'microsoft.resourcehealth/availabilitystatuses'
| extend Time = todatetime(properties.changeAttributes.timestamp)
| where Time >= todatetime('{{TimeRange:startISO}}')
| extend state = properties.changes['properties.availabilityState']
| where isnotempty(tostring(state.newValue))
| extend id = tostring(split(tolower(tostring(properties.targetResourceId)), '/providers/microsoft.resourcehealth/')[0])
| extend parts = split(id, '/')
| extend type = strcat(tostring(parts[6]), '/', tostring(parts[7])), gatewayType = ''
| where type in~ ({TYPE_LIST})
| where type !~ 'microsoft.compute/virtualmachinescalesets' or tostring(parts[8]) matches regex @'{{BuildAgentPattern}}'
{SERVICE_CASE}
| project Time, id, Service, Previous = tostring(state.previousValue), Health = tostring(state.newValue)
| order by Time desc
| take 500
"""
    avs = "microsoft.avs/privateclouds"
    avs_found = {"parameterName": "OvPrivateClouds", "comparison": "isNotEqualTo", "value": ""}
    avs_clouds_q = Q_AVS + """
| extend provisioning = tostring(properties.provisioningState)
| summarize Clouds = count(), Hosts = sum(toint(properties.managementCluster.clusterSize)),
    Failed = countif(provisioning =~ 'Failed'), Busy = countif(provisioning !in~ ('Succeeded', 'Failed'))
| project Signal = 'Private clouds', Value = Clouds, Detail = strcat(Hosts, ' management cluster hosts'),
    State = case(Failed > 0, 'Unavailable', Busy > 0, 'Degraded', 'Available')
"""
    # Failed writes, deletes and actions on platform resources, plus failed deployments at any scope
    # (a subscription-level deployment has its provider at a different position in the id).
    failed_ops_q = f"""
AzureActivity
| where TimeGenerated {{TimeRange}}
| where CategoryValue =~ 'Administrative' and ActivityStatusValue in~ ('Failure', 'Failed')
| extend parts = split(tolower(_ResourceId), '/')
| extend type = iff(tostring(parts[3]) == 'providers', strcat(tostring(parts[4]), '/', tostring(parts[5])),
    strcat(tostring(parts[6]), '/', tostring(parts[7])))
| where type in~ ({TYPE_LIST}, 'microsoft.resources/deployments')
| extend props = column_ifexists('Properties_d', dynamic(null))
| summarize Failures = count(), LastSeen = max(TimeGenerated),
    Error = take_any(substring(tostring(props.statusMessage), 0, 300))
    by Operation = OperationNameValue, ResourceId = _ResourceId, Caller
| top 100 by LastSeen desc
"""
    # Availability from the same transitions. Resource Graph has no window functions, so each start of an
    # impaired period (Unavailable or Degraded) is joined to every recovery of that resource and the earliest
    # later one is kept; a period with no later recovery is still open and runs to now.
    health_transitions = """
    healthresourcechanges
    | where tostring(properties.targetResourceType) =~ 'microsoft.resourcehealth/availabilitystatuses'
    | extend Time = todatetime(properties.changeAttributes.timestamp)
    | where Time >= todatetime('{TimeRange:startISO}')
    | extend state = properties.changes['properties.availabilityState']
    | extend To = tostring(state.newValue), From = tostring(state.previousValue)
    | where isnotempty(To)
    | extend id = tostring(split(tolower(tostring(properties.targetResourceId)), '/providers/microsoft.resourcehealth/')[0])"""
    availability_q = health_transitions.strip() + f"""
| where To in ('Unavailable', 'Degraded') and From !in ('Unavailable', 'Degraded')
| project id, Start = Time
| join kind=leftouter ({health_transitions}
    | where To !in ('Unavailable', 'Degraded') and From in ('Unavailable', 'Degraded')
    | project id, End = Time
  ) on id
| extend End = iff(isnull(End) or End <= Start, now(), End)
| summarize Recovered = min(End) by id, Start
| extend Minutes = datetime_diff('minute', Recovered, Start)
| summarize Incidents = count(), ImpairedMinutes = sum(Minutes), LongestMinutes = max(Minutes), LastIncident = max(Start) by id
| extend parts = split(id, '/')
| extend type = strcat(tostring(parts[6]), '/', tostring(parts[7])), gatewayType = ''
| where type in~ ({TYPE_LIST})
| where type !~ 'microsoft.compute/virtualmachinescalesets' or tostring(parts[8]) matches regex @'{{BuildAgentPattern}}'
{SERVICE_CASE}
| extend windowMin = datetime_diff('minute', now(), todatetime('{{TimeRange:startISO}}'))
| extend windowMin = iff(windowMin > 20160, 20160, windowMin)
| project id, Service, AvailabilityPct = round(100.0 - 100.0 * ImpairedMinutes / windowMin, 3), Incidents,
    ImpairedMinutes, LongestMinutes, LastIncident
| order by AvailabilityPct asc
"""
    # Issues board: one tile per check, each a count of things wrong, with the tab that has the detail.
    # Every Resource Graph table needs its own query, and a query of its own would mean a narrow one-tile item,
    # so each table is reduced to a single row of counts and the rows are joined on a constant key. Resource
    # Graph allows three joins a query, hence two queries. The joined row is then unpacked into one row per check.
    def issue_rows(checks):
        """checks: list of (label, count column, tab, state when the count is above zero)."""
        packs = ",\n    ".join(f"pack('Check', '{label}', 'Count', {col}, 'Tab', '{tab}', 'Severity', '{state}')"
                               for label, col, tab, state in checks)
        return f"""| extend rows = pack_array(
    {packs})
| mv-expand r = rows
| extend Count = tolong(r.Count)
| project Check = tostring(r.Check), Count, Where = strcat('See ', tostring(r.Tab)),
    State = iff(Count > 0, tostring(r.Severity), 'Available')
| order by Count desc
"""

    def joined(first, *others):
        """Join single-row count queries side by side into one row."""
        query = first.strip() + "\n| extend k = 1\n"
        for other in others:
            body = other.strip().replace("\n", "\n    ")
            query += f"| join kind=leftouter (\n    {body}\n    | extend k = 1\n  ) on k\n"
        return query

    counts_resources = """
resources
| where type in~ ('microsoft.network/privateendpoints', 'microsoft.insights/metricalerts', 'microsoft.insights/scheduledqueryrules',
    'microsoft.insights/activitylogalerts', 'microsoft.insights/actiongroups', 'microsoft.network/firewallpolicies',
    'microsoft.network/virtualnetworks', 'microsoft.network/applicationgateways', 'microsoft.compute/disks',
    'microsoft.network/applicationgatewaywebapplicationfirewallpolicies', 'microsoft.network/frontdoorwebapplicationfirewallpolicies')
| extend endpointState = coalesce(
    tostring(properties.privateLinkServiceConnections[0].properties.privateLinkServiceConnectionState.status),
    tostring(properties.manualPrivateLinkServiceConnections[0].properties.privateLinkServiceConnectionState.status))
| summarize
    Endpoints = countif(type =~ 'microsoft.network/privateendpoints' and endpointState !~ 'Approved'),
    Peerings = countif(type =~ 'microsoft.network/virtualnetworks' and tostring(properties.virtualNetworkPeerings) contains 'Disconnected'),
    Gateways = countif(type =~ 'microsoft.network/applicationgateways' and tostring(properties.operationalState) !~ 'Running'),
    ThreatIntelOff = countif(type =~ 'microsoft.network/firewallpolicies' and tostring(properties.threatIntelMode) =~ 'Off'),
    WafDetection = countif(type endswith 'webapplicationfirewallpolicies' and tostring(properties.policySettings.mode) =~ 'Detection'),
    RulesDisabled = countif(type in~ ('microsoft.insights/metricalerts', 'microsoft.insights/scheduledqueryrules',
        'microsoft.insights/activitylogalerts') and not(tobool(properties.enabled))),
    GroupsDisabled = countif(type =~ 'microsoft.insights/actiongroups' and not(tobool(properties.enabled))),
    Disks = countif(type =~ 'microsoft.compute/disks' and tostring(properties.diskState) =~ 'Unattached' and isempty(managedBy))
"""
    counts_defender = """
securityresources
| where type =~ 'microsoft.security/pricings'
| where not(tobool(properties.deprecated))
| summarize PlansOff = dcountif(subscriptionId, tostring(properties.pricingTier) !~ 'Standard')
"""
    counts_access = """
authorizationresources
| where type =~ 'microsoft.authorization/roleassignments'
| where tolower(tostring(properties.roleDefinitionId)) endswith '8e3af657-a8ff-443c-a75c-2fe8c4bcb635'
| extend scope = tolower(tostring(properties.scope))
| where scope == '/' or scope startswith '/providers/microsoft.management/managementgroups/' or array_length(split(scope, '/')) == 3
| summarize by scope, principalType = tostring(properties.principalType), principalId = tostring(properties.principalId)
| summarize DirectOwners = countif(principalType =~ 'User')
"""
    counts_health = health_transitions.strip() + f"""
| where To in ('Unavailable', 'Degraded')
| extend parts = split(id, '/')
| extend type = strcat(tostring(parts[6]), '/', tostring(parts[7]))
| where type in~ ({TYPE_LIST})
| where type !~ 'microsoft.compute/virtualmachinescalesets' or tostring(parts[8]) matches regex @'{{BuildAgentPattern}}'
| summarize Impaired = dcount(id)
"""
    counts_patch = """
patchassessmentresources
| where type in~ ('microsoft.compute/virtualmachines/patchassessmentresults', 'microsoft.hybridcompute/machines/patchassessmentresults')
| summarize Critical = countif(toint(properties.availablePatchCountByClassification.critical) > 0),
    Reboot = countif(tobool(properties.rebootPending))
"""
    counts_retirement = """
advisorresources
| where type =~ 'microsoft.advisor/recommendations'
| where tostring(properties.extendedProperties.recommendationSubCategory) =~ 'ServiceUpgradeAndRetirement'
| extend retires = todatetime(properties.extendedProperties.retirementDate)
| summarize Soon = dcountif(tostring(properties.extendedProperties.retirementFeatureName), retires < now() + 90d)
"""
    counts_exemptions = """
policyresources
| where type =~ 'microsoft.authorization/policyexemptions'
| extend expires = todatetime(properties.expiresOn)
| summarize Expired = countif(expires < now()), Expiring = countif(expires >= now() and expires < now() + 30d)
"""
    issues_config_q = joined(counts_resources, counts_defender, counts_access) + issue_rows([
        ("Endpoints not approved", "Endpoints", "Shared", "Unavailable"),
        ("Peerings disconnected", "Peerings", "Virtual WAN", "Unavailable"),
        ("App gateways stopped", "Gateways", "App Delivery", "Unavailable"),
        ("Threat intel off", "ThreatIntelOff", "Firewall", "Degraded"),
        ("WAF in detection mode", "WafDetection", "App Delivery", "Degraded"),
        ("Alert rules disabled", "RulesDisabled", "Monitoring & Backup", "Degraded"),
        ("Action groups disabled", "GroupsDisabled", "Monitoring & Backup", "Degraded"),
        ("Unattached disks", "Disks", "Governance", "Degraded"),
        ("Defender plans off", "PlansOff", "Security", "Degraded"),
        ("Owners set on users", "DirectOwners", "Security", "Degraded"),
    ])
    issues_state_q = joined(counts_health, counts_patch, counts_retirement, counts_exemptions) + issue_rows([
        ("Health incidents", "Impaired", "Overview, below", "Degraded"),
        ("Critical patches due", "Critical", "Governance", "Unavailable"),
        ("Reboot pending", "Reboot", "Governance", "Degraded"),
        ("Retiring in 90 days", "Soon", "Governance", "Degraded"),
        ("Exemptions expired", "Expired", "Governance", "Degraded"),
        ("Exemptions expiring", "Expiring", "Governance", "Degraded"),
    ])
    # Log checks. A leg whose table is missing from the workspace is skipped, so its tile is simply absent.
    issues_logs_q = f"""
union isfuzzy=true
    (datatable(Check:string, Count:long, Tab:string, Severity:string)[]),
    (NWConnectionMonitorTestResult | where TimeGenerated {{TimeRange}}
        | summarize arg_max(TimeGenerated, TestResult) by ConnectionMonitorResourceId, TestGroupName, SourceName, DestinationName
        | summarize Count = countif(TestResult == 'Fail')
        | extend Check = 'Connectivity failing', Tab = 'Connectivity', Severity = 'Unavailable'),
    (WVDAgentHealthStatus | where TimeGenerated {{TimeRange}}
        | summarize arg_max(TimeGenerated, Status) by SessionHostName
        | summarize Count = countif(TimeGenerated > ago(30m) and Status in ('Unavailable', 'UpgradeFailed', 'NoHeartbeat'))
        | extend Check = 'AVD hosts unavailable', Tab = 'AVD', Severity = 'Unavailable'),
    (Heartbeat | where TimeGenerated {{TimeRange}}
        | summarize lastSeen = max(TimeGenerated) by Computer
        | summarize Count = countif(lastSeen < ago(15m))
        | extend Check = 'Machines not reporting', Tab = 'Monitoring & Backup', Severity = 'Degraded'),
    (AzureActivity | where TimeGenerated {{TimeRange}}
        | where CategoryValue =~ 'Administrative' and ActivityStatusValue in~ ('Failure', 'Failed')
        | extend parts = split(tolower(_ResourceId), '/')
        | extend type = iff(tostring(parts[3]) == 'providers', strcat(tostring(parts[4]), '/', tostring(parts[5])),
            strcat(tostring(parts[6]), '/', tostring(parts[7])))
        | where type in~ ({TYPE_LIST}, 'microsoft.resources/deployments')
        | summarize Count = count()
        | extend Check = 'Failed operations', Tab = 'Overview, below', Severity = 'Degraded'),
    (SecurityIncident | where TimeGenerated {{TimeRange}}
        | summarize arg_max(TimeGenerated, Status, Severity) by IncidentNumber
        | summarize Count = countif(Status != 'Closed' and Severity == 'High')
        | extend Check = 'High incidents open', Tab = 'Security', Severity = 'Unavailable')
| project Check, Count, Where = strcat('See ', Tab), State = iff(Count > 0, Severity, 'Available')
| order by Count desc
"""
    issue_tiles = big_number_tiles("Check", "State", "Count", "Where")
    sev = {"columnMatch": "Severity", "formatter": 18, "formatOptions": _icons(
        [_t("==", f"Sev{i}", f"Sev{i}") for i in range(5)] + [_t("Default", None, "Blank")])}
    service_tiles = big_number_tiles("Service", "Status", "Total", "Summary")
    return group("tab-overview", [
        text("overview-intro",
             "Status comes from **Azure Resource Health** where available; otherwise from the resource's "
             "configuration state (provisioning, hub routing state, circuit/provider state, DNS limits, workspace "
             "ingestion) — see the *Signal* column. Each service tab adds metric-based health. *Health state changes* "
             "and *Recent changes* further down show what happened earlier in the time range.", "info"),
        text("overview-issues-h", "### Issues"),
        text("overview-issues-note", "One tile per check, drawn from every tab. The number is how many things the check "
             "found wrong; a green tick means none. The line under it names the tab that has the detail. *Defender "
             "plans off* counts subscriptions, *Exemptions expiring* looks 30 days ahead, and *High incidents open* "
             "is Sentinel.", "info"),
        arg("overview-issues-config", "", issues_config_q, vis="tiles", tiles=issue_tiles),
        arg("overview-issues-state", "", issues_state_q, vis="tiles", tiles=issue_tiles),
        la("overview-issues-logs", "", issues_logs_q, vis="tiles", tiles=issue_tiles),
        text("overview-glance-h", "### At a glance"),
        arg("overview-servicehealth-tile", "", service_health_tile_q, vis="tiles", tiles=service_tiles, width=GLANCE_WIDTH),
        *[arg(f"overview-{key}", "", q, vis="tiles", tiles=big_number_tiles("Signal", "State", "Value", "Detail", unit),
              width=GLANCE_WIDTH) for key, unit, q in GOVERNANCE_TILES],
        arg("overview-tiles", "Platform services", summary_q, vis="tiles", tiles=service_tiles,
            no_data="No platform resources found in the selected subscriptions."),
        # The AVS tab's own picker is not evaluated while that tab is hidden, so the Overview has its own.
        params("overview-avs-params", [resource_param("OvPrivateClouds", "AVS private clouds", Q_AVS, hidden_when_locked=True)]),
        text("overview-avs-h", "### Azure VMware Solution at a glance", visible_when=avs_found),
        arg("overview-avs-clouds", "", avs_clouds_q, vis="tiles",
            tiles=big_number_tiles("Signal", "State", "Value", "Detail"), width=AVS_TILE_WIDTH, visible_when=avs_found),
        metrics("overview-avs-cpu", "", avs, "OvPrivateClouds", [m(avs, "EffectiveCpuAverage", AVG)],
                tiles=metric_tiles(80, 90), width=AVS_TILE_WIDTH, visible_when=avs_found),
        metrics("overview-avs-mem", "", avs, "OvPrivateClouds", [m(avs, "UsageAverage", AVG)],
                tiles=metric_tiles(80, 90), width=AVS_TILE_WIDTH, visible_when=avs_found),
        metrics("overview-avs-vsan", "", avs, "OvPrivateClouds", [m(avs, "DiskUsedPercentage", AVG)],
                tiles=metric_tiles(70, 75), width=AVS_TILE_WIDTH, visible_when=avs_found),
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
        arg("overview-health-history", "Health state changes (time range, up to 14 days)", health_history_q,
            formatters=[resource_link(), health_fmt("Previous"), health_fmt()],
            labels={"id": "Resource", "Previous": "From", "Health": "To"},
            no_data="No Resource Health state changes on platform resources in the time range."),
        arg("overview-availability", "Availability over the time range (resources with health incidents, up to 14 days)",
            availability_q, formatters=[resource_link(), high_is_good("AvailabilityPct", 99.9, 99, digits=3)],
            labels={"id": "Resource", "AvailabilityPct": "Available %", "ImpairedMinutes": "Minutes impaired",
                    "LongestMinutes": "Longest incident (min)", "LastIncident": "Last incident"},
            no_data="No platform resource left the Available state in the time range."),
        arg("overview-changes", "Recent changes to platform resources (time range, up to 14 days)", changes_q,
            formatters=[resource_link(), status_fmt("ChangeType", warn=["Delete"])],
            labels={"id": "Resource", "ChangeType": "Change", "Properties": "Properties changed", "ChangedBy": "Changed by"},
            no_data="No changes to platform resources in the time range."),
        la("overview-failed-ops", "Failed operations and deployments on platform resources", failed_ops_q,
           formatters=[resource_link("ResourceId")],
           labels={"ResourceId": "Resource", "LastSeen": "Last seen"},
           no_data="No failed operations in the time range (or the activity log is not sent to this workspace)."),
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
    Secured = iff(isnotempty(tostring(properties.azureFirewall.id)), 'Yes', 'No'),
    ExpressRoute = iff(isnotempty(tostring(properties.expressRouteGateway.id)), 'Yes', 'No'),
    S2SVpn = iff(isnotempty(tostring(properties.vpnGateway.id)), 'Yes', 'No'),
    P2SVpn = iff(isnotempty(tostring(properties.p2SVpnGateway.id)), 'Yes', 'No'),
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
            *[status_fmt(c, good=["Yes"], neutral=["No"]) for c in ("Secured", "ExpressRoute", "S2SVpn", "P2SVpn")],
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
    Zones = strcat_array(zones, ','),
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
    # IDPS and TLS inspection exist only on Premium policies, so other tiers show n/a rather than Off.
    policies_q = """
resources
| where type =~ 'microsoft.network/firewallpolicies'
| extend Tier = tostring(properties.sku.tier)
| project id = tolower(id), Tier,
    ThreatIntel = tostring(properties.threatIntelMode),
    Idps = iff(Tier =~ 'Premium', coalesce(tostring(properties.intrusionDetection.mode), 'Off'), 'n/a'),
    TlsInspection = case(Tier !~ 'Premium', 'n/a',
        isnotempty(tostring(properties.transportSecurity.certificateAuthority.keyVaultSecretId)), 'Yes', 'No'),
    DnsProxy = coalesce(tostring(properties.dnsSettings.enableProxy), 'false'),
    Firewalls = coalesce(array_length(properties.firewalls), 0),
    ParentPolicy = tostring(split(tostring(properties.basePolicy.id), '/')[8]),
    RuleCollectionGroups = coalesce(array_length(properties.ruleCollectionGroups), 0),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/firewallpolicies/rulecollectiongroups'
    | mv-expand rc = properties.ruleCollections limit 400
    | summarize RuleCollections = count(), Rules = sum(array_length(rc.rules))
        by id = tostring(split(tolower(id), '/rulecollectiongroups/')[0])
  ) on id
| project id, Tier, ThreatIntel, Idps, TlsInspection, DnsProxy, Firewalls, ParentPolicy, RuleCollectionGroups,
    RuleCollections = coalesce(RuleCollections, 0), Rules = coalesce(Rules, 0), Provisioning, ResourceGroup
"""
    dns_codes_q = """
AZFWDnsQuery
| where TimeGenerated {TimeRange}
| summarize Queries = count() by bin(TimeGenerated, {TimeRange:grain}), ResponseCode
"""
    dns_failed_q = """
AZFWDnsQuery
| where TimeGenerated {TimeRange}
| where ResponseCode !~ 'NOERROR'
| summarize Queries = count(), Sources = dcount(SourceIp), LastSeen = max(TimeGenerated) by QueryName, QueryType, ResponseCode
| top 50 by Queries desc
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
        text("firewall-policy-h", "### Firewall policy"),
        arg("firewall-policies", "Firewall policies", policies_q, formatters=[
            resource_link(), PROVISIONING,
            status_fmt("ThreatIntel", good=["Deny"], warn=["Alert"], bad=["Off"]),
            status_fmt("Idps", good=["Deny"], warn=["Alert"], bad=["Off"], neutral=["n/a"]),
            status_fmt("TlsInspection", good=["Yes"], neutral=["No", "n/a"]),
            status_fmt("DnsProxy", good=["true"], neutral=["false"]),
            high_is_good("Firewalls", 1, 0),
        ], labels={"id": "Policy", "ThreatIntel": "Threat intel", "Idps": "IDPS", "TlsInspection": "TLS inspection",
                   "DnsProxy": "DNS proxy", "ParentPolicy": "Parent policy", "RuleCollectionGroups": "Rule collection groups",
                   "RuleCollections": "Rule collections"},
            no_data="No firewall policies found."),
        text("firewall-policy-note", "A policy attached to no firewall is flagged. Rule counts are totals across the "
             "policy's own rule collection groups; rules inherited from a parent policy are counted on the parent. "
             "The TLS inspection certificate lives in Key Vault, so its expiry shows under *Expiry & retirement* on "
             "the Governance tab.", "info"),
        text("firewall-logs-hint", "Select a **Log Analytics workspace** at the top to see denied traffic, threat "
             "detections and DNS proxy queries (requires resource-specific firewall logs, e.g. `AZFWNetworkRule`).", "info", visible_when=WORKSPACE_UNSET),
        la("firewall-denied", "Top denied flows", denied_q, width=50,
           no_data="No denied flows (or structured firewall logs are not enabled)."),
        la("firewall-threats", "Threat intel & IDPS detections", threats_q, width=50,
           no_data="No threat intel or IDPS hits."),
        la("firewall-dns-codes", "DNS proxy queries by response code", dns_codes_q, vis="timechart", width=50),
        la("firewall-dns-failed", "Top failing DNS proxy queries", dns_failed_q, width=50,
           no_data="No failing DNS queries (or DNS proxy logs are not enabled)."),
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


def connectivity_tab():
    monitors_q = """
resources
| where type =~ 'microsoft.network/networkwatchers/connectionmonitors'
| project id,
    Endpoints = array_length(properties.endpoints),
    TestGroups = array_length(properties.testGroups),
    TestConfigurations = array_length(properties.testConfigurations),
    Workspace = tostring(split(tostring(properties.outputs[0].workspaceSettings.workspaceResourceId), '/')[8]),
    Provisioning = tostring(properties.provisioningState),
    Location = location
"""
    tests = """
NWConnectionMonitorTestResult
| where TimeGenerated {TimeRange}
| extend Monitor = tostring(split(ConnectionMonitorResourceId, '/')[10])
"""
    # One row per test: the latest result, with loss and latency over the whole time range.
    latest = tests + """| summarize arg_max(TimeGenerated, TestResult), Checks = sum(ChecksTotal), Failed = sum(ChecksFailed),
    AvgRttMs = round(avg(AvgRoundTripTimeMs), 1), MaxRttMs = round(max(MaxRoundTripTimeMs), 1),
    FailedRuns = countif(TestResult == 'Fail')
    by Monitor, TestGroupName, SourceName, DestinationName, DestinationPort, Protocol
"""
    tiles_q = latest + "| summarize Tests = count() by TestResult\n| order by Tests desc"
    results_q = latest + """| project Monitor, TestGroup = TestGroupName, Source = SourceName,
    Destination = iff(isnotempty(DestinationPort), strcat(DestinationName, ':', DestinationPort), DestinationName),
    Protocol, TestResult, LossPct = round(100.0 * Failed / Checks, 2), AvgRttMs, MaxRttMs, FailedRuns,
    LastResult = TimeGenerated
| order by case(TestResult == 'Fail', 0, TestResult == 'Warning', 1, TestResult == 'Indeterminate', 2, 3) asc, LossPct desc
"""
    by_path = "by bin(TimeGenerated, {TimeRange:grain}), Path = strcat(SourceName, ' → ', DestinationName)\n"
    loss_q = tests + "| summarize LossPct = round(100.0 * sum(ChecksFailed) / sum(ChecksTotal), 2) " + by_path
    rtt_q = tests + "| summarize AvgRttMs = avg(AvgRoundTripTimeMs) " + by_path
    result_states = dict(good=["Pass"], warn=["Warning"], bad=["Fail"], neutral=["Indeterminate"])
    flow_log_coverage_q = """
resources
| where type =~ 'microsoft.network/virtualnetworks'
| project id = tolower(id), Subnets = array_length(properties.subnets), ResourceGroup = resourceGroup, Location = location
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/networkwatchers/flowlogs'
    | extend isEnabled = tobool(properties.enabled),
        analytics = tobool(properties.flowAnalyticsConfiguration.networkWatcherFlowAnalyticsConfiguration.enabled)
    | summarize Enabled = countif(isEnabled), WithAnalytics = countif(isEnabled and analytics),
        RetentionDays = max(toint(properties.retentionPolicy.days))
        by id = tolower(tostring(properties.targetResourceId))
  ) on id
| project id,
    FlowLogs = case(coalesce(Enabled, 0) == 0, 'No flow log', coalesce(WithAnalytics, 0) == 0, 'No Traffic Analytics', 'Traffic Analytics'),
    RetentionDays, Subnets, ResourceGroup, Location
| order by case(FlowLogs == 'No flow log', 0, FlowLogs == 'No Traffic Analytics', 1, 2) asc, ResourceGroup asc
"""
    # The one-column datatable keeps the query valid in a workspace with no Traffic Analytics table; every
    # other column is then read with column_ifexists so it does not have to exist.
    flows = """
union isfuzzy=true (datatable(TimeGenerated:datetime)[]), (NTANetAnalytics)
| where TimeGenerated {TimeRange}
| where column_ifexists('SubType', '') == 'FlowLog'
| extend FlowType = tostring(column_ifexists('FlowType', '')), FlowStatus = tostring(column_ifexists('FlowStatus', '')),
    Source = tostring(column_ifexists('SrcIp', '')), Destination = tostring(column_ifexists('DestIp', '')),
    SourceVm = tostring(column_ifexists('SrcVm', '')), DestinationVm = tostring(column_ifexists('DestVm', '')),
    Port = tostring(column_ifexists('DestPort', '')), Protocol = tostring(column_ifexists('L4Protocol', '')),
    Rule = tostring(column_ifexists('AclRule', '')),
    Bytes = tolong(column_ifexists('BytesSrcToDest', 0)) + tolong(column_ifexists('BytesDestToSrc', 0))
"""
    flow_types_q = flows + "| summarize Bytes = sum(Bytes) by bin(TimeGenerated, {TimeRange:grain}), FlowType\n"
    talkers_q = flows + """| where FlowStatus == 'Allowed'
| summarize Bytes = sum(Bytes), Flows = count() by Source, SourceVm, Destination, DestinationVm
| top 30 by Bytes desc
| project Source, SourceVm, Destination, DestinationVm, GB = round(Bytes / 1073741824.0, 2), Flows
"""
    denied_flows_q = flows + """| where FlowStatus == 'Denied'
| summarize Flows = count(), LastSeen = max(TimeGenerated) by Source, SourceVm, Destination, Port, Protocol, Rule
| top 30 by Flows desc
"""
    return group("tab-connectivity", [
        text("conn-intro",
             "End-to-end reachability from **Network Watcher Connection Monitor** tests. The other network tabs show "
             "each component's own metrics, which can all be healthy while a route between on-premises, the hub and "
             "a spoke is broken. Tests have to exist first: create them in Network Watcher and send their results "
             "to the selected workspace.", "info"),
        arg("conn-monitors", "Connection monitors", monitors_q, formatters=[resource_link(), PROVISIONING],
            labels={"id": "Connection monitor", "TestGroups": "Test groups", "TestConfigurations": "Test configurations"},
            no_data="No connection monitors found in the selected subscriptions."),
        text("conn-workspace-hint", "Select the **Log Analytics workspace** that receives Connection Monitor results "
             "to see test status, packet loss and latency.", "info", visible_when=WORKSPACE_UNSET),
        la("conn-result-tiles", "Tests by latest result", tiles_q, vis="tiles", tiles={
            "titleContent": {"columnMatch": "TestResult", "formatter": 1},
            "leftContent": status_fmt("TestResult", **result_states, text=ICON_ONLY),
            "rightContent": {"columnMatch": "Tests", "formatter": 12, "formatOptions": {"palette": "none"}},
            "showBorder": True,
        }, no_data="No Connection Monitor results in the selected workspace."),
        la("conn-results", "Tests (latest result, loss and latency over time range)", results_q, formatters=[
            status_fmt("TestResult", **result_states), low_is_good("LossPct", 1, 5, digits=2),
            low_is_good("FailedRuns", 1, 1),
        ], labels={"TestGroup": "Test group", "TestResult": "Result", "LossPct": "Loss %", "AvgRttMs": "Avg RTT (ms)",
                   "MaxRttMs": "Max RTT (ms)", "FailedRuns": "Failed runs", "LastResult": "Last result"},
           no_data="No Connection Monitor results in the time range."),
        la("conn-loss", "Checks failed % by path", loss_q, vis="timechart", width=50),
        la("conn-rtt", "Average round-trip time (ms) by path", rtt_q, vis="timechart", width=50),
        text("conn-traffic-h", "### Network traffic (VNet flow logs)"),
        arg("conn-flow-coverage", "Virtual networks by flow log coverage", flow_log_coverage_q, formatters=[
            resource_link(),
            status_fmt("FlowLogs", good=["Traffic Analytics"], warn=["No Traffic Analytics"], bad=["No flow log"]),
        ], labels={"id": "Virtual network", "FlowLogs": "Flow logs", "RetentionDays": "Retention (days)"},
            no_data="No virtual networks found."),
        la("conn-flow-types", "Traffic by flow type (bytes)", flow_types_q, vis="timechart"),
        la("conn-talkers", "Top talkers (allowed traffic)", talkers_q, width=50,
           labels={"SourceVm": "Source VM", "DestinationVm": "Destination VM"},
           no_data="No flow records in the time range (or Traffic Analytics does not write to this workspace)."),
        la("conn-denied-flows", "Top denied flows", denied_flows_q, width=50,
           labels={"SourceVm": "Source VM", "LastSeen": "Last seen"},
           no_data="No denied flows in the time range."),
        text("conn-traffic-note", "Coverage counts a flow log that targets the virtual network itself; one that targets "
             "a single subnet or network interface is not counted. The traffic panels read the Traffic Analytics "
             "table for VNet flow logs (`NTANetAnalytics`), not the older NSG flow log table.", "info"),
    ], tab="connectivity")


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
    # An endpoint holds its connection under one of two properties depending on whether it was auto-approved.
    # customDnsConfigs is filled in only when the endpoint has no private DNS zone group, so it stands in for that.
    private_endpoints = """
resources
| where type =~ 'microsoft.network/privateendpoints'
| extend conns = iff(array_length(properties.privateLinkServiceConnections) > 0,
    properties.privateLinkServiceConnections, properties.manualPrivateLinkServiceConnections)
| mv-expand c = conns
| extend Connection = tostring(c.properties.privateLinkServiceConnectionState.status),
    Target = tostring(c.properties.privateLinkServiceId),
    SubResource = tostring(c.properties.groupIds[0]),
    Provisioning = tostring(properties.provisioningState),
    Dns = iff(array_length(properties.customDnsConfigs) > 0, 'No zone group', 'Zone group')
"""
    pe_tiles_q = private_endpoints + """| summarize Total = count(), NotApproved = countif(Connection !~ 'Approved'),
    Failed = countif(Provisioning =~ 'Failed'), NoZoneGroup = countif(Dns == 'No zone group')
| extend rows = pack_array(
    pack('Signal', 'Connection not approved', 'Value', NotApproved, 'State', iff(NotApproved > 0, 'Unavailable', 'Available')),
    pack('Signal', 'Provisioning failed', 'Value', Failed, 'State', iff(Failed > 0, 'Unavailable', 'Available')),
    pack('Signal', 'No private DNS zone group', 'Value', NoZoneGroup, 'State', iff(NoZoneGroup > 0, 'Degraded', 'Available')))
| mv-expand r = rows
| project Signal = tostring(r.Signal), Value = toint(r.Value), State = tostring(r.State),
    Detail = strcat('of ', Total, ' private endpoints')
"""
    pe_issues_q = private_endpoints + """| where Connection !~ 'Approved' or Provisioning !~ 'Succeeded' or Dns == 'No zone group'
| project id, Connection, Dns, Provisioning, Target, SubResource, ResourceGroup = resourceGroup
| order by case(Connection =~ 'Approved', 1, 0) asc, case(Provisioning =~ 'Succeeded', 1, 0) asc
"""
    duplicate_zones_q = """
resources
| where type =~ 'microsoft.network/privatednszones'
| where name startswith 'privatelink.'
| summarize Copies = count(), Subscriptions = dcount(subscriptionId),
    ResourceGroups = strcat_array(make_set(resourceGroup), ', ') by Zone = name
| where Copies > 1
| order by Copies desc
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
        ]),
        metrics("shared-bastion-sessions", "Bastion sessions", bns, "Bastions", [m(bns, "sessions", SUM)]),
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
        text("shared-pe-h", "### Private endpoints"),
        arg("shared-pe-tiles", "", pe_tiles_q, vis="tiles", tiles=big_number_tiles("Signal", "State", "Value", "Detail")),
        arg("shared-pe-issues", "Private endpoints needing attention", pe_issues_q, formatters=[
            resource_link(), resource_link("Target"), PROVISIONING,
            status_fmt("Connection", good=["Approved"], warn=["Pending"], bad=["Rejected", "Disconnected"]),
            status_fmt("Dns", good=["Zone group"], warn=["No zone group"]),
        ], labels={"id": "Private endpoint", "Dns": "DNS", "SubResource": "Sub-resource"},
            no_data="Every private endpoint is approved, provisioned and has a private DNS zone group.", width=65),
        arg("shared-pe-duplicate-zones", "Private Link DNS zones that exist more than once", duplicate_zones_q,
            labels={"ResourceGroups": "Resource groups"},
            no_data="Each privatelink zone exists once.", width=35),
        text("shared-pe-note", "An endpoint with no private DNS zone group has no record registered for it in the "
             "central zones, so its name resolves to the public address unless a record is kept by hand. A "
             "privatelink zone that exists twice splits resolution: a VNet linked to the extra copy cannot see "
             "the records in the central one.", "info"),
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


def appdelivery_tab():
    agw, afd = "microsoft.network/applicationgateways", "microsoft.cdn/profiles"
    gateways_q = Q_APP_GATEWAYS + """
| project id,
    Tier = tostring(properties.sku.tier),
    State = tostring(properties.operationalState),
    Instances = iff(isnotnull(properties.autoscaleConfiguration),
        strcat(tostring(properties.autoscaleConfiguration.minCapacity), ' - ', tostring(properties.autoscaleConfiguration.maxCapacity)),
        tostring(properties.sku.capacity)),
    Zones = strcat_array(zones, ','),
    Listeners = array_length(properties.httpListeners),
    BackendPools = array_length(properties.backendAddressPools),
    WafPolicy = tostring(split(tostring(properties.firewallPolicy.id), '/')[8]),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup, Location = location
"""
    # Front Door Standard and Premium are CDN profiles; classic Front Door is a separate type that is being retired.
    front_doors_q = """
resources
| where (type =~ 'microsoft.cdn/profiles' and tostring(sku.name) contains 'AzureFrontDoor') or type =~ 'microsoft.network/frontdoors'
| project id,
    Tier = iff(type =~ 'microsoft.network/frontdoors', 'Classic (being retired)', tostring(sku.name)),
    State = coalesce(tostring(properties.resourceState), tostring(properties.enabledState)),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup
"""
    waf_policies_q = """
resources
| where type in~ ('microsoft.network/applicationgatewaywebapplicationfirewallpolicies', 'microsoft.network/frontdoorwebapplicationfirewallpolicies')
| extend settings = properties.policySettings
| project id,
    Protects = iff(type =~ 'microsoft.network/frontdoorwebapplicationfirewallpolicies', 'Front Door', 'Application Gateway'),
    Mode = tostring(settings.mode),
    State = coalesce(tostring(settings.state), tostring(settings.enabledState)),
    ManagedRuleSets = array_length(properties.managedRules.managedRuleSets),
    CustomRules = coalesce(array_length(properties.customRules), array_length(properties.customRules.rules), 0),
    AttachedTo = coalesce(array_length(properties.applicationGateways), 0) + coalesce(array_length(properties.httpListeners), 0)
        + coalesce(array_length(properties.pathBasedRules), 0) + coalesce(array_length(properties.securityPolicyLinks), 0)
        + coalesce(array_length(properties.frontendEndpointLinks), 0),
    ResourceGroup = resourceGroup
| order by case(Mode =~ 'Prevention', 1, 0) asc, Protects asc
"""
    # WAF hits from both products. Each leg reads its columns with column_ifexists because the names differ
    # between the resource-specific tables and AzureDiagnostics, and a missing table is skipped.
    waf_hits_q = """
union isfuzzy=true
    (datatable(TimeGenerated:datetime, Product:string, Action:string, Rule:string, Host:string, ClientIp:string)[]),
    (AGWFirewallLogs | where TimeGenerated {TimeRange}
        | project TimeGenerated, Product = 'Application Gateway', Action = tostring(column_ifexists('Action', '')),
            Rule = strcat(tostring(column_ifexists('RuleId', '')), ' ', tostring(column_ifexists('Message', ''))),
            Host = tostring(column_ifexists('Hostname', '')), ClientIp = tostring(column_ifexists('ClientIp', ''))),
    (AzureDiagnostics | where TimeGenerated {TimeRange}
        | where Category in ('ApplicationGatewayFirewallLog', 'FrontDoorWebApplicationFirewallLog', 'FrontdoorWebApplicationFirewallLog')
        | project TimeGenerated, Product = iff(Category == 'ApplicationGatewayFirewallLog', 'Application Gateway', 'Front Door'),
            Action = tostring(column_ifexists('action_s', '')),
            Rule = coalesce(tostring(column_ifexists('ruleName_s', '')),
                strcat(tostring(column_ifexists('ruleId_s', '')), ' ', tostring(column_ifexists('Message', '')))),
            Host = coalesce(tostring(column_ifexists('host_s', '')), tostring(column_ifexists('hostname_s', ''))),
            ClientIp = coalesce(tostring(column_ifexists('clientIP_s', '')), tostring(column_ifexists('clientIp_s', ''))))
| where Action in~ ('Blocked', 'Block', 'Detected', 'Log', 'Matched')
| summarize Hits = count(), Clients = dcount(ClientIp), LastSeen = max(TimeGenerated) by Product, Action, Rule = substring(Rule, 0, 160), Host
| top 50 by Hits desc
"""
    return group("tab-appdelivery", [
        params("appdelivery-params", [
            resource_param("AppGateways", "Application gateways", Q_APP_GATEWAYS),
            resource_param("FrontDoors", "Front Door profiles", Q_FRONT_DOORS),
        ]),
        text("agw-h", "### Application Gateway"),
        arg("agw-inventory", "Application gateways", gateways_q, formatters=[
            resource_link(), PROVISIONING, status_fmt("State", good=["Running"], warn=["Starting", "Stopping"], bad=["Stopped"]),
        ], labels={"id": "Application gateway", "BackendPools": "Backend pools", "WafPolicy": "WAF policy"},
            no_data="No application gateways found."),
        metric_grid("agw-kpis", "Key metrics (over time range)", agw, "AppGateways", [
            ("UnhealthyHostCount", MAX, "Unhealthy backends (max)", ("low", 1, 1)),
            ("HealthyHostCount", MIN, "Healthy backends (min)", None),
            ("FailedRequests", SUM, "Failed requests", None),
            ("TotalRequests", SUM, "Total requests", None),
            ("ApplicationGatewayTotalTime", AVG, "Total time (ms)", ("low", 1000, 3000)),
            ("CapacityUnits", MAX, "Capacity units (max)", None),
        ]),
        metrics("agw-hosts", "Unhealthy backends by pool", agw, "AppGateways",
                [m(agw, "UnhealthyHostCount", MAX, split="BackendSettingsPool")], width=50),
        metrics("agw-status", "Responses by status group", agw, "AppGateways",
                [m(agw, "ResponseStatus", SUM, split="HttpStatusGroup")], width=50),
        metrics("agw-time", "Total time and backend response time (ms)", agw, "AppGateways",
                [m(agw, "ApplicationGatewayTotalTime", AVG), m(agw, "BackendLastByteResponseTime", AVG)], width=50),
        metrics("agw-capacity", "Capacity units and throughput", agw, "AppGateways",
                [m(agw, "CapacityUnits", MAX), m(agw, "Throughput", AVG)], width=50),
        text("afd-h", "### Azure Front Door"),
        arg("afd-inventory", "Front Door profiles", front_doors_q, formatters=[
            resource_link(), PROVISIONING,
            status_fmt("State", good=["Active", "Enabled"], warn=["Creating", "Migrating", "Migrated"], bad=["Disabled", "Deleting"]),
            status_fmt("Tier", warn=["Classic (being retired)"]),
        ], labels={"id": "Profile"}, no_data="No Front Door profiles found."),
        metric_grid("afd-kpis", "Key metrics (over time range)", afd, "FrontDoors", [
            ("OriginHealthPercentage", AVG, "Origin health %", ("high", 99, 90)),
            ("Percentage5XX", AVG, "5xx %", ("low", 1, 5)),
            ("Percentage4XX", AVG, "4xx %", None),
            ("RequestCount", SUM, "Requests", None),
            ("TotalLatency", AVG, "Total latency (ms)", ("low", 500, 2000)),
            ("OriginLatency", AVG, "Origin latency (ms)", None),
        ]),
        metrics("afd-origin-health", "Origin health % by origin", afd, "FrontDoors",
                [m(afd, "OriginHealthPercentage", AVG, split="Origin")], width=50),
        metrics("afd-errors", "4xx and 5xx %", afd, "FrontDoors",
                [m(afd, "Percentage4XX", AVG), m(afd, "Percentage5XX", AVG)], width=50),
        metrics("afd-latency", "Total and origin latency (ms)", afd, "FrontDoors",
                [m(afd, "TotalLatency", AVG), m(afd, "OriginLatency", AVG)], width=50),
        metrics("afd-waf", "WAF requests by action", afd, "FrontDoors",
                [m(afd, "WebApplicationFirewallRequestCount", SUM, split="Action")], width=50),
        text("waf-h", "### Web Application Firewall"),
        arg("waf-policies", "WAF policies", waf_policies_q, formatters=[
            resource_link(),
            status_fmt("Mode", good=["Prevention"], warn=["Detection"]),
            status_fmt("State", good=["Enabled"], bad=["Disabled"]),
            high_is_good("AttachedTo", 1, 0),
        ], labels={"id": "Policy", "ManagedRuleSets": "Managed rule sets", "CustomRules": "Custom rules",
                   "AttachedTo": "Attached to"}, no_data="No WAF policies found."),
        text("waf-logs-hint", "Select a **Log Analytics workspace** at the top to see the WAF rules that are "
             "matching requests.", "info", visible_when=WORKSPACE_UNSET),
        la("waf-hits", "Top WAF rule matches", waf_hits_q,
           formatters=[status_fmt("Action", bad=["Blocked", "Block"], warn=["Detected", "Log", "Matched"])],
           labels={"LastSeen": "Last seen"},
           no_data="No WAF matches in the time range (or WAF logs are not sent to this workspace)."),
        text("waf-note", "A policy in *Detection* mode logs matches but lets the request through. TLS certificates "
             "for both products are held in Key Vault or managed by Azure, so their expiry is not shown here.", "info"),
    ], tab="appdelivery")


def identity_tab():
    vm = "microsoft.compute/virtualmachines"
    domain_services_q = """
resources
| where type =~ 'microsoft.aad/domainservices'
| mv-expand replica = properties.replicaSets
| project id,
    Domain = tostring(properties.domainName),
    Sku = tostring(properties.sku),
    ReplicaLocation = tostring(replica.location),
    ServiceStatus = tostring(replica.serviceStatus),
    HealthAlerts = coalesce(array_length(replica.healthAlerts), 0),
    HealthEvaluated = todatetime(replica.healthLastEvaluated),
    Ldaps = tostring(properties.ldapsSettings.ldaps),
    LdapsCertExpires = todatetime(properties.ldapsSettings.certificateNotAfter),
    Provisioning = tostring(properties.provisioningState)
"""
    dcs_q = Q_DC_VMS + """
| project id = tolower(id),
    Power = tostring(properties.extended.instanceView.powerState.displayStatus),
    Size = tostring(properties.hardwareProfile.vmSize),
    Zone = strcat_array(zones, ','),
    ResourceGroup = resourceGroup, Location = location
| join kind=leftouter (
    healthresources
    | where type =~ 'microsoft.resourcehealth/availabilitystatuses'
    | project id = tostring(split(tolower(id), '/providers/microsoft.resourcehealth/')[0]),
        Health = tostring(properties.availabilityState)
  ) on id
| join kind=leftouter (
    patchassessmentresources
    | where type =~ 'microsoft.compute/virtualmachines/patchassessmentresults'
    | extend c = properties.availablePatchCountByClassification
    | project id = tostring(split(tolower(id), '/patchassessmentresults/')[0]),
        CriticalPatches = coalesce(toint(c.critical), 0), SecurityPatches = coalesce(toint(c.security), 0),
        RebootPending = tostring(properties.rebootPending)
  ) on id
| project id, Health, Power, CriticalPatches, SecurityPatches, RebootPending, Size, Zone, ResourceGroup, Location
| order by id asc
"""
    heartbeat_q = """
Heartbeat
| where TimeGenerated {TimeRange}
| where Computer matches regex @'{DcPattern}'
| summarize LastHeartbeat = max(TimeGenerated) by Computer
| extend Status = iff(LastHeartbeat < ago(15m), 'Silent', 'Reporting')
| order by Status desc, Computer asc
"""
    ad_events_q = """
Event
| where TimeGenerated {TimeRange}
| where Computer matches regex @'{DcPattern}'
| where EventLog in ('Directory Service', 'DFS Replication', 'DNS Server', 'Active Directory Web Services')
| where EventLevelName in ('Error', 'Warning')
| summarize Events = count(), LastSeen = max(TimeGenerated), Message = take_any(substring(RenderedDescription, 0, 250))
    by Computer, EventLog, Level = EventLevelName, Source, EventID
| top 50 by Events desc
"""
    logon_q = """
SecurityEvent
| where TimeGenerated {TimeRange}
| where EventID in (4625, 4740, 4771)
| extend Event = case(EventID == 4740, 'Account locked out', EventID == 4771, 'Kerberos pre-authentication failed', 'Logon failed')
| summarize Events = count() by bin(TimeGenerated, {TimeRange:grain}), Event
"""
    signins = "SigninLogs\n| where TimeGenerated {TimeRange}\n"
    entra_tiles_q = signins + """| summarize SignIns = count(), Users = dcount(UserPrincipalName),
    Failed = countif(ResultType != '0'), FailedUsers = dcountif(UserPrincipalName, ResultType != '0'),
    Blocked = countif(ConditionalAccessStatus =~ 'failure'),
    Risky = countif(RiskLevelDuringSignIn in~ ('medium', 'high')),
    Mfa = countif(AuthenticationRequirement =~ 'multiFactorAuthentication')
| extend rows = pack_array(
    pack('Signal', 'Interactive sign-ins', 'Value', SignIns, 'Detail', strcat(Users, ' users')),
    pack('Signal', 'Not successful', 'Value', Failed,
        'Detail', strcat(round(100.0 * Failed / SignIns, 1), '% of sign-ins · ', FailedUsers, ' users')),
    pack('Signal', 'Blocked by Conditional Access', 'Value', Blocked, 'Detail', 'policy result: failure'),
    pack('Signal', 'Risky sign-ins', 'Value', Risky, 'Detail', 'medium or high risk'),
    pack('Signal', 'Multifactor sign-ins', 'Value', Mfa, 'Detail', strcat(round(100.0 * Mfa / SignIns, 0), '% of sign-ins')))
| mv-expand r = rows
| project Signal = tostring(r.Signal), Value = tolong(r.Value), Detail = tostring(r.Detail)
"""
    signin_results_q = signins + """| summarize SignIns = count()
    by bin(TimeGenerated, {TimeRange:grain}), Result = iff(ResultType == '0', 'Success', 'Not successful')
"""
    signin_failures_q = signins + """| where ResultType != '0'
| summarize SignIns = count(), Users = dcount(UserPrincipalName), LastSeen = max(TimeGenerated)
    by ResultType, Reason = ResultDescription
| top 25 by SignIns desc
"""
    ca_policies_q = signins + """| mv-expand policy = todynamic(tostring(ConditionalAccessPolicies))
| where tostring(policy.result) =~ 'failure'
| summarize Blocked = count(), Users = dcount(UserPrincipalName), LastSeen = max(TimeGenerated)
    by Policy = tostring(policy.displayName)
| top 25 by Blocked desc
"""
    # The empty datatable keeps these two queries valid in a workspace that does not receive the table.
    sp_failures_q = """
union isfuzzy=true
    (datatable(TimeGenerated:datetime, ResultType:string, ResultDescription:string, ServicePrincipalName:string, AppId:string)[]),
    (AADServicePrincipalSignInLogs)
| where TimeGenerated {TimeRange}
| where ResultType != '0'
| summarize Failures = count(), LastSeen = max(TimeGenerated), Error = take_any(substring(ResultDescription, 0, 200))
    by ServicePrincipal = ServicePrincipalName, AppId, ResultType
| extend Cause = case(ResultType == '7000222', 'Client secret expired', ResultType == '7000215', 'Invalid client secret', '')
| project ServicePrincipal, Failures, Cause, ResultType, Error, LastSeen, AppId
| top 25 by Failures desc
"""
    risky_users_q = """
union isfuzzy=true
    (datatable(TimeGenerated:datetime, UserPrincipalName:string, RiskLevel:string, RiskState:string, RiskDetail:string)[]),
    (AADRiskyUsers)
| where TimeGenerated {TimeRange}
| summarize arg_max(TimeGenerated, RiskLevel, RiskState, RiskDetail) by UserPrincipalName
| where RiskState in~ ('atRisk', 'confirmedCompromised')
| project User = UserPrincipalName, RiskLevel, RiskState, RiskDetail, Updated = TimeGenerated
| order by case(RiskLevel =~ 'high', 0, RiskLevel =~ 'medium', 1, 2) asc, Updated desc
"""
    directory_changes_q = """
AuditLogs
| where TimeGenerated {TimeRange}
| where Category in ('RoleManagement', 'Policy')
    or OperationName has_any ('certificates and secrets', 'consent', 'owner')
| extend Actor = coalesce(tostring(InitiatedBy.user.userPrincipalName), tostring(InitiatedBy.app.displayName))
| summarize Changes = count(), Actors = dcount(Actor), (LastSeen, LastActor) = arg_max(TimeGenerated, Actor)
    by Category, Operation = OperationName, Result
| project Category, Operation, Result, Changes, Actors, LastActor, LastSeen
| top 40 by Changes desc
"""
    entra_tiles = {
        "titleContent": {"columnMatch": "Signal", "formatter": 1},
        "rightContent": {"columnMatch": "Value", "formatter": 12, "formatOptions": {"palette": "none"}},
        "secondaryContent": {"columnMatch": "Detail", "formatter": 1},
        "showBorder": True,
    }
    return group("tab-identity", [
        text("identity-entra-h", "### Microsoft Entra ID"),
        text("identity-entra-hint", "Select the **Log Analytics workspace** that receives the Entra ID diagnostic "
             "logs to see sign-ins, Conditional Access results, risky users and directory changes.", "info",
             visible_when=WORKSPACE_UNSET),
        la("identity-entra-tiles", "", entra_tiles_q, vis="tiles", tiles=entra_tiles,
           no_data="No interactive sign-ins in the time range (or Entra ID sign-in logs are not sent to this workspace)."),
        la("identity-signins", "Interactive sign-ins by result", signin_results_q, vis="timechart", width=50),
        la("identity-signin-failures", "Top reasons a sign-in did not succeed", signin_failures_q, width=50,
           labels={"ResultType": "Code", "SignIns": "Sign-ins", "LastSeen": "Last seen"},
           no_data="Every sign-in in the time range succeeded."),
        la("identity-ca-policies", "Conditional Access policies blocking sign-ins", ca_policies_q, width=50,
           labels={"LastSeen": "Last seen"}, no_data="No sign-ins were blocked by Conditional Access."),
        la("identity-sp-failures", "Service principals failing to sign in", sp_failures_q, width=50,
           formatters=[status_fmt("Cause", bad=["Client secret expired", "Invalid client secret"])],
           labels={"ServicePrincipal": "Service principal", "ResultType": "Code", "LastSeen": "Last seen", "AppId": "App ID"},
           no_data="No failed service principal sign-ins (or those logs are not sent to this workspace)."),
        la("identity-risky-users", "Users at risk (risk changed in time range)", risky_users_q, width=50,
           formatters=[status_fmt("RiskLevel", warn=["medium"], bad=["high"], neutral=["low", "none", "hidden"])],
           labels={"RiskLevel": "Risk level", "RiskState": "Risk state", "RiskDetail": "Risk detail"},
           no_data="No users at risk (or risky user logs are not sent to this workspace)."),
        la("identity-directory-changes", "Role, policy, credential and consent changes", directory_changes_q, width=50,
           formatters=[status_fmt("Result", good=["success"], bad=["failure"])],
           labels={"LastActor": "Last changed by", "LastSeen": "Last seen"},
           no_data="No role, policy, credential or consent changes in the time range."),
        text("identity-entra-note", "These panels read the Entra ID diagnostic logs: `SigninLogs`, `AuditLogs`, "
             "`AADServicePrincipalSignInLogs` and `AADRiskyUsers`. A sign-in that is *not successful* includes "
             "interrupted ones, such as a prompt for multifactor authentication, as well as real failures; the "
             "reasons table tells them apart. Non-interactive sign-ins are not counted.", "info", visible_when=WORKSPACE_SET),
        text("identity-intro",
             "Domain controller virtual machines are found by **name** using the *Domain controller name pattern* "
             "parameter at the top. A managed domain in Microsoft Entra Domain Services is listed without it.", "info"),
        text("identity-ds-h", "### Microsoft Entra Domain Services"),
        arg("identity-domain-services", "Managed domains by replica set", domain_services_q, formatters=[
            resource_link(), PROVISIONING,
            status_fmt("ServiceStatus", good=["Running"], warn=["Starting", "Stopping", "Deploying"], bad=["Stopped", "Failed"]),
            low_is_good("HealthAlerts", 1, 1),
        ], labels={"id": "Managed domain", "ReplicaLocation": "Replica set", "ServiceStatus": "Service status",
                   "HealthAlerts": "Health alerts", "HealthEvaluated": "Health evaluated", "Ldaps": "Secure LDAP",
                   "LdapsCertExpires": "Secure LDAP certificate expires"},
            no_data="No Microsoft Entra Domain Services managed domains found."),
        text("identity-dc-h", "### Domain controllers"),
        params("identity-params", [resource_param("DomainControllers", "Domain controllers", Q_DC_VMS)]),
        arg("identity-dcs", "Domain controller virtual machines", dcs_q, formatters=[
            resource_link(), health_fmt(),
            status_fmt("Power", good=["VM running"], bad=["VM deallocated", "VM stopped"], warn=["VM starting", "VM stopping", "VM deallocating"]),
            low_is_good("CriticalPatches", 1, 1), low_is_good("SecurityPatches", 1, 10),
            status_fmt("RebootPending", warn=["true"]),
        ], labels={"id": "Domain controller", "CriticalPatches": "Critical patches", "SecurityPatches": "Security patches",
                   "RebootPending": "Reboot pending"},
            no_data="No virtual machines matched the domain controller name pattern."),
        metric_grid("identity-kpis", "Domain controller metrics (over time range)", vm, "DomainControllers", [
            ("VmAvailabilityMetric", AVG, "VM availability", None),
            ("Percentage CPU", AVG, "Avg CPU %", ("low", 80, 95)),
            ("Available Memory Percentage", AVG, "Avg free memory %", ("high", 20, 10)),
            ("OS Disk IOPS Consumed Percentage", AVG, "OS disk IOPS used %", ("low", 80, 95)),
        ]),
        metrics("identity-cpu", "CPU %", vm, "DomainControllers", [m(vm, "Percentage CPU", AVG)], width=50),
        metrics("identity-mem", "Available memory %", vm, "DomainControllers",
                [m(vm, "Available Memory Percentage", AVG)], width=50),
        text("identity-logs-hint", "Select a **Log Analytics workspace** at the top to see domain controller "
             "heartbeats, directory service errors and failed logons.", "info", visible_when=WORKSPACE_UNSET),
        la("identity-heartbeat", "Domain controller heartbeats", heartbeat_q, width=30,
           formatters=[status_fmt("Status", good=["Reporting"], bad=["Silent"])],
           no_data="No heartbeats from machines matching the domain controller name pattern."),
        la("identity-ad-events", "Directory, replication and DNS errors and warnings", ad_events_q, width=70,
           formatters=[status_fmt("Level", warn=["Warning"], bad=["Error"])],
           no_data="No errors or warnings (or these event logs are not collected from the domain controllers)."),
        la("identity-logons", "Failed logons and account lockouts", logon_q, vis="timechart"),
    ], tab="identity")


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
    MaxSessions = iff(tostring(properties.hostPoolType) =~ 'Personal', int(null), toint(properties.maxSessionLimit)),
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
    # A connection attempt is one CorrelationId: it logs Started, then Connected if the user reached a host.
    success_q = """
WVDConnections
| where TimeGenerated {TimeRange}
| summarize Started = minif(TimeGenerated, State == 'Started'), Connected = countif(State == 'Connected') > 0 by CorrelationId
| where isnotnull(Started)
| summarize Attempts = count(), Succeeded = countif(Connected) by bin(Started, {TimeRange:grain})
| project Started, SuccessPct = round(100.0 * Succeeded / Attempts, 1)
"""
    # Sign-in time for new sessions: from the connection starting to the shell being ready, less the time the
    # user spent at a credential prompt. Reconnects to an existing session never reach ShellReady.
    signin_q = """
WVDConnections
| where TimeGenerated {TimeRange}
| where State == 'Started'
| project Started = TimeGenerated, CorrelationId
| join kind=inner (
    WVDCheckpoints
    | where TimeGenerated {TimeRange}
    | where Name =~ 'ShellReady' or Name =~ 'RdpShellAppExecuted'
        or (Name =~ 'LaunchExecutable' and tostring(Parameters.connectionStage) == 'RdpShellAppExecuted')
    | summarize Ready = min(TimeGenerated) by CorrelationId
  ) on CorrelationId
| join kind=leftouter (
    WVDCheckpoints
    | where TimeGenerated {TimeRange}
    | where Name in~ ('OnCredentialsAcquisitionCompleted', 'SSOTokenRetrieval')
    | summarize PromptMs = sum(tolong(Parameters.DurationMS)) by CorrelationId
  ) on CorrelationId
| extend Seconds = (Ready - Started) / 1s - coalesce(PromptMs, 0) / 1000.0
| where Seconds > 0
| summarize MedianSec = percentile(Seconds, 50), P95Sec = percentile(Seconds, 95) by bin(Started, {TimeRange:grain})
"""
    logon_stages_q = """
WVDCheckpoints
| where TimeGenerated {TimeRange}
| where Name == 'LogonDelay'
| extend stages = bag_remove_keys(Parameters, dynamic(['LogonType', 'WinLogonPid']))
| mv-expand bagexpansion=array stages
| extend Stage = tostring(stages[0]), Seconds = toreal(stages[1]) / 1000
| where Stage startswith 'WinLogon_Logon_'
| summarize Seconds = sum(Seconds) by Stage = substring(Stage, strlen('WinLogon_Logon_')), CorrelationId
| summarize MedianSec = round(percentile(Seconds, 50), 1), P95Sec = round(percentile(Seconds, 95), 1), Logons = count() by Stage
| order by P95Sec desc
"""
    pool_load_q = AVD_LATEST_HOSTS + """| where Status != 'Offline'
| extend hostSessions = toint(column_ifexists('ActiveSessions', 0)) + toint(column_ifexists('InactiveSessions', 0)),
    AllowsNew = tobool(column_ifexists('AllowNewSessions', true))
| summarize Hosts = count(), Available = countif(Status == 'Available'), InDrainMode = countif(not(AllowsNew)),
    Sessions = sum(hostSessions), BusiestHost = max(hostSessions) by HostPool
| extend SessionsPerHost = round(1.0 * Sessions / Hosts, 1)
| order by BusiestHost desc
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
        la("avd-success", "Connection success rate %", success_q, vis="timechart", width=50),
        la("avd-signin", "Time to sign in, new sessions (seconds)", signin_q, vis="timechart", width=50),
        la("avd-logon-stages", "Logon time by stage (seconds)", logon_stages_q, formatters=[
            low_is_good("P95Sec", 15, 30, digits=1),
        ], labels={"MedianSec": "Median", "P95Sec": "P95"}, width=50,
           no_data="No logon stage data in the time range."),
        la("avd-pool-load", "Sessions by host pool (hosts reporting now)", pool_load_q,
           labels={"HostPool": "Host pool", "InDrainMode": "In drain mode", "BusiestHost": "Sessions on busiest host",
                   "SessionsPerHost": "Sessions per host"}, width=50,
           no_data="No session hosts are reporting."),
        text("avd-load-note", "Compare *Sessions on busiest host* with the pool's *MaxSessions* in the host pools "
             "table at the top: a host at its limit takes no more users. The slowest logon stages are usually "
             "profile load (FSLogix), group policy and logon scripts.", "info", visible_when=WORKSPACE_SET),
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
        text("storage-files-note", "Azure Files capacity is reported hourly, so the two charts below need a time "
             "range of at least a few hours. A share whose used capacity is close to its quota stops FSLogix "
             "profiles from growing.", "info"),
        metrics("storage-files-used", "Azure Files used capacity by share", ns, "StorageAccounts",
                [m(fns, "FileCapacity", AVG, split="FileShare")], width=50),
        metrics("storage-files-quota", "Azure Files share quota by share", ns, "StorageAccounts",
                [m(fns, "FileShareCapacityQuota", AVG, split="FileShare")], width=50),
        arg("storage-inventory", "Storage accounts", inventory_q, formatters=[
            resource_link(),
            status_fmt("Primary", good=["available"], bad=["unavailable"]),
            status_fmt("Secondary", good=["available"], bad=["unavailable"]),
            status_fmt("PublicNetwork", good=["Disabled"], warn=["Enabled"]),
        ], labels={"id": "Storage account"}),
    ], tab="storage")


def capacity_tab():
    compute_quota_q = """
quotaresources
| where type =~ 'microsoft.compute/locations/usages'
| mv-expand q = properties.value limit 400
| extend Quota = tostring(q.name.localizedValue), Used = tolong(q.currentValue), Limit = tolong(q['limit'])
| where Used > 0 and Limit > 0
| extend UsedPct = round(100.0 * Used / Limit, 1)
""" + SUBSCRIPTION_NAMES + """
| project Subscription = coalesce(Subscription, subscriptionId), Region = location, Quota, Used, Limit, UsedPct
| order by UsedPct desc
"""
    # Usable = subnet size minus the 5 addresses Azure reserves. IPv6 prefixes are left out.
    subnets_q = """
resources
| where type =~ 'microsoft.network/virtualnetworks'
| mv-expand subnet = properties.subnets limit 400
| extend Prefix = coalesce(tostring(subnet.properties.addressPrefix), tostring(subnet.properties.addressPrefixes[0]))
| where isnotempty(Prefix) and Prefix !contains ':'
| extend Usable = tolong(pow(2, 32 - toint(split(Prefix, '/')[1]))) - 5,
    Used = coalesce(array_length(subnet.properties.ipConfigurations), 0)
| where Usable > 0
| project id, Subnet = tostring(subnet.name), Prefix, Used, Usable, UsedPct = round(100.0 * Used / Usable, 1),
    Delegation = tostring(subnet.properties.delegations[0].properties.serviceName),
    ResourceGroup = resourceGroup
| order by UsedPct desc
"""
    quota_sub = {
        "id": gid("param-QuotaSubscription"),
        "version": "KqlParameterItem/1.0",
        "name": "QuotaSubscription",
        "label": "Subscription",
        "type": 6,
        "isRequired": True,
        "query": "summarize by subscriptionId\n| project value = strcat('/subscriptions/', subscriptionId), label = subscriptionId",
        "crossComponentResources": ["{Subscription}"],
        "typeSettings": {"additionalResourceOptions": ["value::1"], "showDefault": False},
        "defaultValue": "value::1",
        "queryType": 1,
        "resourceType": "microsoft.resourcegraph/resources",
    }
    quota_region = {
        "id": gid("param-QuotaRegion"),
        "version": "KqlParameterItem/1.0",
        "name": "QuotaRegion",
        "label": "Region",
        "type": 2,
        "isRequired": True,
        "query": "resources\n| where type in~ ('microsoft.network/virtualhubs', 'microsoft.network/virtualnetworks')\n"
                 "| summarize Resources = count() by location\n| order by Resources desc\n"
                 "| project value = location, label = location",
        "crossComponentResources": ["{QuotaSubscription}"],
        "typeSettings": {"additionalResourceOptions": ["value::1"], "showDefault": False},
        "defaultValue": "value::1",
        "queryType": 1,
        "resourceType": "microsoft.resourcegraph/resources",
    }
    return group("tab-capacity", [
        text("cap-intro",
             "Headroom against limits that stop a deployment or a scale-out when they are reached. Capacity of the "
             "services themselves is on their own tabs: hub routing units (Virtual WAN), SNAT ports (Firewall), "
             "circuit utilisation (ExpressRoute), Private DNS zone limits (Shared), vSAN (AVS) and Azure Files "
             "share quota (Storage).", "info"),
        text("cap-compute-h", "### Compute quotas"),
        arg("cap-compute-quota", "vCPU and compute quotas in use, by subscription and region", compute_quota_q,
            formatters=[low_is_good("UsedPct", 70, 90, digits=1)], labels={"UsedPct": "Used %"},
            no_data="No compute quota is in use in the selected subscriptions."),
        text("cap-network-h", "### Network quotas"),
        text("cap-network-note", "Network usage is not in Resource Graph, so this reads it from Azure Resource "
             "Manager for one subscription and region at a time.", "info"),
        params("cap-network-params", [quota_sub, quota_region]),
        arm("cap-network-quota", "Network quotas (public IPs, VNets, route tables, private endpoints...)",
            "{QuotaSubscription}/providers/Microsoft.Network/locations/{QuotaRegion}/usages", "2023-09-01",
            [("Quota", "$.name.localizedValue", None), ("Used", "$.currentValue", "long"), ("Limit", "$.limit", "long")],
            sort_desc="Used", no_data="No network usage returned for this subscription and region."),
        text("cap-cost-h", "### Cost"),
        text("cap-cost-note", "Month-to-date spend for the subscription selected under *Network quotas*, read from "
             "Cost Management. It covers everything in that subscription, so it is platform cost only when the "
             "subscription holds only platform resources.", "info"),
        arm("cap-cost-services", "Cost by service, month to date",
            "{QuotaSubscription}/providers/Microsoft.CostManagement/query", "2023-11-01",
            [("Service", "$[1]", None), ("Cost", "$[0]", None), ("Currency", "$[2]", None)],
            table="$.properties.rows", sort_desc="Cost", width=50,
            body={"type": "ActualCost", "timeframe": "MonthToDate", "dataset": {
                "granularity": "None",
                "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                "grouping": [{"type": "Dimension", "name": "ServiceName"}]}},
            formatters=[{"columnMatch": "Cost", "formatter": 0,
                         "numberFormat": {"unit": 0, "options": {"style": "decimal", "maximumFractionDigits": 2}}}],
            no_data="Cost Management returned no cost for this subscription this month."),
        arm("cap-budgets", "Budgets", "{QuotaSubscription}/providers/Microsoft.Consumption/budgets", "2023-05-01",
            [("Budget", "$.name", None), ("Amount", "$.properties.amount", None),
             ("Spent", "$.properties.currentSpend.amount", None), ("Forecast", "$.properties.forecastSpend.amount", None),
             ("Currency", "$.properties.currentSpend.unit", None), ("Period", "$.properties.timeGrain", None)],
            width=50, no_data="No budgets are defined on this subscription."),
        text("cap-subnets-h", "### Subnet address space"),
        text("cap-subnets-note", "*Used* counts the IP configurations attached to each subnet (NICs, private "
             "endpoints, load balancer front ends). Application Gateway instances and delegated services such as "
             "SQL Managed Instance take addresses that are not counted, and Virtual WAN hubs do not expose their "
             "address usage at all.", "info"),
        arg("cap-subnets", "Subnets by address utilisation", subnets_q,
            formatters=[resource_link(), low_is_good("UsedPct", 70, 90, digits=1)],
            labels={"id": "Virtual network", "UsedPct": "Used %"}, no_data="No virtual network subnets found."),
    ], tab="capacity")


def security_tab():
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
    sev_fmt = status_fmt("Severity", warn=["Medium"], bad=["High"], neutral=["Low", "Informational"])
    # Built-in roles that can grant access: Owner, User Access Administrator and Role Based Access Control
    # Administrator. Resource Graph returns an inherited assignment once per subscription, so they are
    # de-duplicated on scope, role and principal first.
    privileged = """
authorizationresources
| where type =~ 'microsoft.authorization/roleassignments'
| extend roleId = tolower(tostring(split(tostring(properties.roleDefinitionId), '/')[-1]))
| where roleId in ('8e3af657-a8ff-443c-a75c-2fe8c4bcb635', '18d7d88d-d35e-4fb5-a5c3-7773c20a72d9', 'f58310d9-a9f6-439a-9e8d-f62e7b41a168')
| extend Role = case(roleId startswith '8e3af657', 'Owner', roleId startswith '18d7d88d', 'User Access Administrator',
    'RBAC Administrator'),
    scope = tolower(tostring(properties.scope))
| extend parts = split(scope, '/')
| extend ScopeLevel = case(scope == '/', 'Tenant root',
    scope startswith '/providers/microsoft.management/managementgroups/', 'Management group',
    array_length(parts) == 3, 'Subscription', array_length(parts) == 5, 'Resource group', 'Resource')
| summarize by scope, ScopeLevel, Role, principalType = tostring(properties.principalType), principalId = tostring(properties.principalId)
"""
    privileged_tiles_q = privileged + """| extend high = ScopeLevel in ('Tenant root', 'Management group', 'Subscription')
| summarize Owners = countif(high and Role == 'Owner'), DirectUsers = countif(high and principalType =~ 'User'),
    Root = countif(ScopeLevel == 'Tenant root'), Lower = countif(not(high))
| extend rows = pack_array(
    pack('Signal', 'Owner assignments', 'Value', Owners, 'Detail', 'at subscription scope or above', 'State', 'Unknown'),
    pack('Signal', 'Assigned directly to users', 'Value', DirectUsers, 'Detail', 'not through a group',
        'State', iff(DirectUsers > 0, 'Degraded', 'Available')),
    pack('Signal', 'At tenant root', 'Value', Root, 'Detail', 'apply to every subscription',
        'State', iff(Root > 0, 'Degraded', 'Available')),
    pack('Signal', 'Below subscription scope', 'Value', Lower, 'Detail', 'resource groups and resources', 'State', 'Unknown'))
| mv-expand r = rows
| project Signal = tostring(r.Signal), Value = toint(r.Value), Detail = tostring(r.Detail), State = tostring(r.State)
"""
    privileged_q = privileged + """| where ScopeLevel in ('Tenant root', 'Management group', 'Subscription')
| summarize Users = countif(principalType =~ 'User'), Groups = countif(principalType =~ 'Group'),
    ServicePrincipals = countif(principalType !in~ ('User', 'Group')) by scope, ScopeLevel, Role
| extend subscriptionId = iff(ScopeLevel == 'Subscription', tostring(split(scope, '/')[2]), '')
""" + SUBSCRIPTION_NAMES + """
| project ScopeLevel,
    Scope = case(ScopeLevel == 'Subscription', coalesce(Subscription, subscriptionId),
        ScopeLevel == 'Management group', tostring(split(scope, '/')[4]), '/'),
    Role, Users, Groups, ServicePrincipals
| order by case(ScopeLevel == 'Tenant root', 0, ScopeLevel == 'Management group', 1, 2) asc, Scope asc, Role asc
"""
    defender_plans = """
securityresources
| where type =~ 'microsoft.security/pricings'
| where not(tobool(properties.deprecated))
| extend isOn = tostring(properties.pricingTier) =~ 'Standard'
"""
    plan_coverage_q = defender_plans + "| summarize PlansOn = countif(isOn), PlansOff = countif(not(isOn)) by subscriptionId" + SUBSCRIPTION_NAMES + """
| project Subscription = coalesce(Subscription, subscriptionId), PlansOn, PlansOff,
    CoveragePct = round(100.0 * PlansOn / (PlansOn + PlansOff), 0)
| order by CoveragePct asc
"""
    plans_off_q = defender_plans + "| where not(isOn)" + SUBSCRIPTION_NAMES + """
| project Subscription = coalesce(Subscription, subscriptionId), Plan = name
| order by Subscription asc, Plan asc
"""
    sentinel_workspaces_q = """
resources
| where type =~ 'microsoft.operationsmanagement/solutions'
| where name startswith 'SecurityInsights('
| project id = tolower(tostring(properties.workspaceResourceId)),
    Provisioning = tostring(properties.provisioningState), ResourceGroup = resourceGroup, Location = location
"""
    # SecurityIncident gets a new row on every change, so the latest row per incident is its current state.
    # The empty datatable keeps the queries valid in a workspace that is not a Sentinel workspace.
    incidents = """
let incidents = union isfuzzy=true
    (datatable(TimeGenerated:datetime, IncidentNumber:int, Title:string, Severity:string, Status:string, Owner:dynamic,
        CreatedTime:datetime, ClosedTime:datetime, Classification:string, ProviderName:string, IncidentUrl:string)[]),
    (SecurityIncident)
| where TimeGenerated {TimeRange}
| summarize arg_max(TimeGenerated, *) by IncidentNumber;
"""
    open_by_severity_q = incidents + """incidents
| where Status != 'Closed'
| summarize Incidents = count() by Severity
| order by case(Severity == 'High', 0, Severity == 'Medium', 1, Severity == 'Low', 2, 3) asc
"""
    open_incidents_q = incidents + """incidents
| where Status != 'Closed'
| extend Owner = tostring(Owner.assignedTo)
| project Incident = IncidentNumber, Title, Severity, Status,
    Owner = iff(isempty(Owner), 'Unassigned', Owner), Created = CreatedTime,
    AgeHours = datetime_diff('hour', now(), CreatedTime), Provider = ProviderName, IncidentUrl
| order by case(Severity == 'High', 0, Severity == 'Medium', 1, Severity == 'Low', 2, 3) asc, Created asc
"""
    incident_flow_q = incidents + """union
    (incidents | summarize Incidents = count() by Day = bin(CreatedTime, 1d), Series = 'Created'),
    (incidents | where Status == 'Closed' | summarize Incidents = count() by Day = bin(ClosedTime, 1d), Series = 'Closed')
| where Day >= todatetime('{TimeRange:startISO}')
"""
    incident_closure_q = incidents + """incidents
| where Status == 'Closed'
| extend Hours = datetime_diff('minute', ClosedTime, CreatedTime) / 60.0
| summarize Closed = count(), MedianHoursToClose = round(percentile(Hours, 50), 1), P95HoursToClose = round(percentile(Hours, 95), 1),
    TruePositive = countif(Classification == 'TruePositive'), BenignPositive = countif(Classification == 'BenignPositive'),
    FalsePositive = countif(Classification == 'FalsePositive') by Severity
| order by case(Severity == 'High', 0, Severity == 'Medium', 1, Severity == 'Low', 2, 3) asc
"""
    sentinel_health_q = """
union isfuzzy=true
    (datatable(TimeGenerated:datetime, SentinelResourceName:string, SentinelResourceType:string, Status:string, Description:string)[]),
    (SentinelHealth)
| where TimeGenerated {TimeRange}
| where Status !~ 'Success'
| summarize Failures = count(), LastSeen = max(TimeGenerated), Detail = take_any(substring(Description, 0, 250))
    by Type = SentinelResourceType, Resource = SentinelResourceName, Status
| top 50 by Failures desc
"""
    severity_states = dict(bad=["High"], warn=["Medium"], neutral=["Low", "Informational"])
    return group("tab-security", [
        text("sec-defender-h", "### Microsoft Defender for Cloud"),
        arg("sec-score", "Secure score by subscription", score_q,
            formatters=[high_is_good("ScorePct", 80, 50, digits=0)], labels={"ScorePct": "Score %"}, width=40),
        arg("sec-controls", "Security controls with unhealthy resources", controls_q, width=60),
        arg("sec-alerts", "Active security alerts", alerts_q, formatters=[sev_fmt], no_data="No active security alerts."),
        arg("sec-recs", "Unhealthy recommendations (high & medium)", recs_q, formatters=[sev_fmt]),
        arg("sec-plan-coverage", "Defender plans by subscription", plan_coverage_q,
            formatters=[high_is_good("CoveragePct", 100, 50, digits=0)],
            labels={"PlansOn": "Plans on", "PlansOff": "Plans off", "CoveragePct": "Plans on %"}, width=40),
        arg("sec-plans-off", "Defender plans switched off", plans_off_q, group_by="Subscription",
            no_data="Every Defender plan is on in every selected subscription.", width=60),
        text("sec-privileged-h", "### Privileged access"),
        arg("sec-privileged-tiles", "", privileged_tiles_q, vis="tiles",
            tiles=big_number_tiles("Signal", "State", "Value", "Detail")),
        arg("sec-privileged", "Owner and access administrator assignments at subscription scope or above", privileged_q,
            formatters=[low_is_good("Users", 1, 5)],
            labels={"ScopeLevel": "Scope level", "Users": "Users (direct)", "ServicePrincipals": "Service principals"},
            no_data="No Owner or access administrator assignments at subscription scope or above."),
        text("sec-privileged-note", "Counts role assignments that are active now, for Owner, User Access Administrator "
             "and Role Based Access Control Administrator. Eligible assignments in Privileged Identity Management "
             "are not role assignments until activated, so they are not counted. Resource Graph holds principal "
             "IDs only: it cannot name the principals or tell whether one has been deleted.", "info"),
        text("sec-sentinel-h", "### Microsoft Sentinel"),
        arg("sec-sentinel-workspaces", "Workspaces with Sentinel enabled", sentinel_workspaces_q,
            formatters=[resource_link(), PROVISIONING], labels={"id": "Workspace"},
            no_data="No workspace with the Sentinel solution found in the selected subscriptions."),
        text("sec-sentinel-hint", "Select the **Sentinel workspace** as the Log Analytics workspace at the top to see "
             "incidents and Sentinel health.", "info", visible_when=WORKSPACE_UNSET),
        la("sec-sentinel-open-tiles", "Open incidents by severity", open_by_severity_q, vis="tiles", tiles={
            "titleContent": {"columnMatch": "Severity", "formatter": 1},
            "leftContent": status_fmt("Severity", **severity_states, text=ICON_ONLY),
            "rightContent": {"columnMatch": "Incidents", "formatter": 12, "formatOptions": {"palette": "none"}},
            "showBorder": True,
        }, no_data="No open incidents that changed in the time range."),
        la("sec-sentinel-open", "Open incidents", open_incidents_q, formatters=[
            status_fmt("Severity", **severity_states), status_fmt("Owner", warn=["Unassigned"]),
            {"columnMatch": "IncidentUrl", "formatter": 7, "formatOptions": {"linkTarget": "Url", "linkLabel": "Open"}},
        ], labels={"AgeHours": "Age (hours)", "IncidentUrl": "Link"},
           no_data="No open incidents that changed in the time range."),
        la("sec-sentinel-flow", "Incidents created and closed per day", incident_flow_q, vis="barchart", width=50),
        la("sec-sentinel-closure", "Closed incidents: time to close and classification", incident_closure_q, width=50,
           labels={"MedianHoursToClose": "Median hours to close", "P95HoursToClose": "P95 hours to close",
                   "TruePositive": "True positive", "BenignPositive": "Benign positive", "FalsePositive": "False positive"},
           no_data="No incidents were closed in the time range."),
        la("sec-sentinel-health", "Data connectors, analytics rules and automation that are failing", sentinel_health_q,
           formatters=[status_fmt("Status", warn=["Partial success", "Warning"], bad=["Failure"])],
           labels={"LastSeen": "Last seen"},
           no_data="No failures recorded (or Sentinel health monitoring is not turned on for this workspace)."),
        text("sec-sentinel-note", "Incidents are read from the selected workspace for the time range, so an incident "
             "that has not changed within it is not listed: use a longer range to see old open incidents.", "info",
             visible_when=WORKSPACE_SET),
    ], tab="security")


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
| extend refId = tostring(properties.policyDefinitionReferenceId)
| summarize Resources = dcount(tostring(properties.resourceId)) by assignmentId, definitionId, refId
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
| extend Assignment = coalesce(Assignment, tostring(split(assignmentId, '/')[-1])),
    Policy = coalesce(Policy,
        iff(isnotempty(refId) and not(refId matches regex '^[0-9a-fA-F-]{36}$'), refId, ''),
        tostring(split(definitionId, '/')[-1]))
| summarize Resources = max(Resources), Assignments = make_set(Assignment) by Policy
| project Policy, Resources, Assignments = strcat_array(Assignments, ', ')
| top 100 by Resources desc
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
    retirements_q = """
advisorresources
| where type =~ 'microsoft.advisor/recommendations'
| where tostring(properties.extendedProperties.recommendationSubCategory) =~ 'ServiceUpgradeAndRetirement'
| extend RetirementDate = todatetime(properties.extendedProperties.retirementDate)
| summarize Resources = dcount(tolower(tostring(properties.resourceMetadata.resourceId)))
    by Retiring = coalesce(tostring(properties.extendedProperties.retirementFeatureName), tostring(properties.shortDescription.problem)),
    Action = tostring(properties.shortDescription.solution), RetirementDate, Impact = tostring(properties.impact)
| project Retiring, RetirementDate, DaysLeft = datetime_diff('day', RetirementDate, now()), Resources, Impact, Action
| order by RetirementDate asc
"""
    scheduled_q = """
servicehealthresources
| where type =~ 'microsoft.resourcehealth/events'
| where tostring(properties.Status) =~ 'Active'
| extend EventType = tostring(properties.EventType), Title = tostring(properties.Title)
| where EventType =~ 'PlannedMaintenance' or tostring(properties.EventSubType) =~ 'Retirement' or Title contains 'retir'
| extend Kind = iff(EventType =~ 'PlannedMaintenance', 'Planned maintenance', 'Retirement'),
    Starts = todatetime(tolong(properties.ImpactStartTime)), Ends = todatetime(tolong(properties.ImpactMitigationTime))
| summarize Subscriptions = dcount(subscriptionId) by Kind, Title, TrackingId = tostring(properties.TrackingId), Starts, Ends
| order by Starts asc
"""
    # A host pool without a valid token is normal; it only matters when session hosts are about to be added.
    avd_tokens_q = """
resources
| where type =~ 'microsoft.desktopvirtualization/hostpools'
| extend Expires = todatetime(properties.registrationInfo.expirationTime)
| project id, Token = case(isnull(Expires), 'None', Expires < now(), 'Expired', Expires < now() + 7d, 'Expiring', 'Valid'),
    Expires, ResourceGroup = resourceGroup, Location = location
| order by Expires asc
"""
    kv_expiry_q = """
union isfuzzy=true
    (AzureDiagnostics | where TimeGenerated {TimeRange} | where ResourceProvider =~ 'MICROSOFT.KEYVAULT'
        | project TimeGenerated, OperationName, Vault = tolower(Resource), Object = column_ifexists('id_s', '')),
    (AZKVAuditLogs | where TimeGenerated {TimeRange}
        | project TimeGenerated, OperationName, Vault = tolower(tostring(split(_ResourceId, '/')[8])), Object = column_ifexists('Id', ''))
| where OperationName contains 'NearExpiry' or OperationName contains 'Expired'
| extend Kind = case(OperationName startswith 'Certificate', 'Certificate', OperationName startswith 'Secret', 'Secret',
        OperationName startswith 'Key', 'Key', 'Other'),
    State = iff(OperationName contains 'NearExpiry', 'Near expiry', 'Expired')
| summarize LastSeen = max(TimeGenerated) by Vault, Kind, Object, State
| order by State asc, LastSeen desc
"""
    # Every VM and Arc machine, with its latest Update Manager assessment if it has one.
    patch_base = """
resources
| where type in~ ('microsoft.compute/virtualmachines', 'microsoft.hybridcompute/machines')
| project id = tolower(id),
    OS = coalesce(tostring(properties.storageProfile.osDisk.osType), tostring(properties.osType)),
    PatchMode = coalesce(tostring(properties.osProfile.windowsConfiguration.patchSettings.patchMode),
        tostring(properties.osProfile.linuxConfiguration.patchSettings.patchMode)),
    ResourceGroup = resourceGroup
| join kind=leftouter (
    patchassessmentresources
    | where type in~ ('microsoft.compute/virtualmachines/patchassessmentresults', 'microsoft.hybridcompute/machines/patchassessmentresults')
    | extend c = properties.availablePatchCountByClassification
    | project id = tostring(split(tolower(id), '/patchassessmentresults/')[0]),
        Assessment = tostring(properties.status),
        Assessed = todatetime(properties.lastModifiedDateTime),
        RebootPending = tostring(properties.rebootPending),
        Critical = coalesce(toint(c.critical), 0), Security = coalesce(toint(c.security), 0),
        Other = coalesce(toint(c.updateRollup), 0) + coalesce(toint(c.featurePack), 0) + coalesce(toint(c.servicePack), 0)
            + coalesce(toint(c.definition), 0) + coalesce(toint(c.tools), 0) + coalesce(toint(c.updates), 0)
            + coalesce(toint(c.other), 0)
  ) on id
| project-away id1
| extend Assessment = case(isempty(Assessment), 'Not assessed', Assessed < ago(7d), 'Stale', Assessment)
"""
    patch_tiles_q = patch_base + """| summarize Machines = count(), Pending = countif(Critical > 0 or Security > 0),
    Reboot = countif(RebootPending =~ 'true'), Unknown = countif(Assessment in ('Not assessed', 'Stale'))
| extend rows = pack_array(
    pack('Signal', 'Critical or security patches pending', 'Value', Pending, 'State', iff(Pending > 0, 'Degraded', 'Available')),
    pack('Signal', 'Reboot pending', 'Value', Reboot, 'State', iff(Reboot > 0, 'Degraded', 'Available')),
    pack('Signal', 'Not assessed in the last 7 days', 'Value', Unknown, 'State', iff(Unknown > 0, 'Unknown', 'Available')))
| mv-expand r = rows
| project Signal = tostring(r.Signal), Value = toint(r.Value), State = tostring(r.State),
    Detail = strcat('of ', Machines, ' machines')
"""
    patch_q = patch_base + """| project id, OS, Assessment, Assessed, Critical, Security, Other, RebootPending, PatchMode, ResourceGroup
| order by Critical desc, Security desc, case(Assessment == 'Succeeded', 1, 0) asc
"""
    exemptions_q = """
policyresources
| where type =~ 'microsoft.authorization/policyexemptions'
| extend Expires = todatetime(properties.expiresOn),
    scope = tostring(split(tolower(id), '/providers/microsoft.authorization/policyexemptions/')[0])
| project Exemption = coalesce(tostring(properties.displayName), name),
    Status = case(isnull(Expires), 'No expiry', Expires < now(), 'Expired', Expires < now() + 30d, 'Expiring', 'Active'),
    Expires,
    Category = tostring(properties.exemptionCategory),
    Assignment = tostring(split(tostring(properties.policyAssignmentId), '/')[-1]),
    Scope = scope
| order by case(Status == 'Expired', 0, Status == 'Expiring', 1, Status == 'No expiry', 2, 3) asc, Expires asc
"""
    # A subscription whose only ancestor is the tenant root group was never placed in the landing zone hierarchy.
    placement_q = """
resourcecontainers
| where type =~ 'microsoft.resources/subscriptions'
| extend chain = properties.managementGroupAncestorsChain
| project Subscription = name,
    Placement = iff(array_length(chain) <= 1, 'Under tenant root', 'In hierarchy'),
    ManagementGroup = tostring(chain[0].displayName),
    Depth = array_length(chain),
    State = tostring(properties.state)
| order by case(Placement == 'Under tenant root', 0, 1) asc, ManagementGroup asc, Subscription asc
"""
    # A lock on the resource, its resource group or its subscription all protect it, so each resource is
    # matched at those three scopes, as for alert coverage.
    locks_q = f"""
resources
| where type in~ ({TYPE_LIST})
| where type !~ 'microsoft.compute/virtualmachinescalesets' or name matches regex @'{{BuildAgentPattern}}'
| where type !~ 'microsoft.cdn/profiles' or tostring(sku.name) contains 'AzureFrontDoor'
| extend gatewayType = tostring(properties.gatewayType)
{SERVICE_CASE}
| extend rid = tolower(id), sub = tolower(strcat('/subscriptions/', subscriptionId))
| extend scopeKey = pack_array(rid, strcat(sub, '/resourcegroups/', tolower(resourceGroup)), sub)
| mv-expand scopeKey
| extend scopeKey = tostring(scopeKey)
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.authorization/locks'
    | project scopeKey = tostring(split(tolower(id), '/providers/microsoft.authorization/locks/')[0]), lockId = tolower(id)
  ) on scopeKey
| summarize Locks = dcountif(lockId, isnotempty(lockId)) by rid, Service
| summarize Resources = count(), Locked = countif(Locks > 0) by Service
| project Service, Resources, Locked, NotLocked = Resources - Locked, LockedPct = round(100.0 * Locked / Resources, 0)
| order by LockedPct asc, Service asc
"""
    orphans_q = """
resources
| where type in~ ('microsoft.compute/disks', 'microsoft.network/publicipaddresses', 'microsoft.network/networkinterfaces')
| extend Kind = case(
    type =~ 'microsoft.compute/disks' and tostring(properties.diskState) =~ 'Unattached' and isempty(managedBy), 'Unattached disk',
    type =~ 'microsoft.network/publicipaddresses' and isempty(tostring(properties.ipConfiguration.id))
        and isempty(tostring(properties.natGateway.id)), 'Unused public IP',
    type =~ 'microsoft.network/networkinterfaces' and isempty(tostring(properties.virtualMachine.id))
        and isempty(tostring(properties.privateEndpoint.id)) and isempty(tostring(properties.privateLinkService.id)),
        'Unattached network interface',
    '')
| where isnotempty(Kind)
| project id, Kind,
    Detail = case(type =~ 'microsoft.compute/disks', strcat(tostring(properties.diskSizeGB), ' GB ', tostring(sku.name)),
        type =~ 'microsoft.network/publicipaddresses', strcat(tostring(sku.name), ' ', tostring(properties.publicIPAllocationMethod)), ''),
    ResourceGroup = resourceGroup, Location = location
| order by Kind asc, ResourceGroup asc
"""
    empty_rgs_q = """
resourcecontainers
| where type =~ 'microsoft.resources/subscriptions/resourcegroups'
| project id, subscriptionId, resourceGroup, Location = location
| join kind=leftouter (
    resources
    | summarize Resources = count() by subscriptionId, resourceGroup
  ) on subscriptionId, resourceGroup
| where isnull(Resources)
""" + SUBSCRIPTION_NAMES + """
| project id, Subscription = coalesce(Subscription, subscriptionId), Location
| order by Subscription asc
"""
    return group("tab-governance", [
        text("gov-deadlines-h", "### Expiry & retirement"),
        arg("gov-retirements", "Service retirements affecting your resources (Azure Advisor)", retirements_q, formatters=[
            high_is_good("DaysLeft", 180, 60), status_fmt("Impact", warn=["Medium"], bad=["High"]),
        ], labels={"RetirementDate": "Retirement date", "DaysLeft": "Days left"},
            no_data="Advisor reports no service retirements for the selected subscriptions."),
        arg("gov-scheduled", "Planned maintenance and retirement notices (Azure Service Health)", scheduled_q,
            formatters=[status_fmt("Kind", warn=["Planned maintenance", "Retirement"])],
            labels={"TrackingId": "Tracking ID"}, no_data="No active planned maintenance or retirement notices.", width=60),
        arg("gov-avd-tokens", "AVD host pool registration tokens", avd_tokens_q, formatters=[
            resource_link(), status_fmt("Token", good=["Valid"], warn=["Expiring"], neutral=["Expired", "None"]),
        ], labels={"id": "Host pool"}, no_data="No AVD host pools found.", width=40),
        text("gov-kv-expiry-hint", "Select a **Log Analytics workspace** at the top to see Key Vault certificates, "
             "secrets and keys that are near expiry or expired.", "info", visible_when=WORKSPACE_UNSET),
        la("gov-kv-expiry", "Key Vault certificates, secrets and keys near expiry or expired", kv_expiry_q,
           formatters=[status_fmt("State", warn=["Near expiry"], bad=["Expired"])], labels={"LastSeen": "Reported"},
           no_data="No expiry events in the time range. Key Vault reports near-expiry once, about 30 days ahead, "
                   "so use a 30-day time range; vaults must send audit logs to this workspace."),
        arg("gov-exemptions", "Policy exemptions", exemptions_q, formatters=[
            status_fmt("Status", good=["Active"], warn=["Expiring", "No expiry"], bad=["Expired"]),
        ], no_data="No policy exemptions in the selected subscriptions."),
        text("gov-exemptions-note", "An expired exemption no longer applies, so the resources it covered count as "
             "non-compliant again. One with no expiry hides them from the compliance figure for good. *Waiver* means "
             "the non-compliance is accepted; *Mitigated* means the intent is met another way.", "info"),
        text("gov-policy-h", "### Azure Policy"),
        arg("gov-compliance", "Compliance by subscription", compliance_q,
            formatters=[high_is_good("CompliancePct", 90, 70, digits=1)], labels={"CompliancePct": "Compliant %"}, width=40),
        arg("gov-noncompliant", "Top non-compliant policies", noncompliant_q, width=60,
            no_data="No non-compliant resources."),
        text("gov-hygiene-h", "### Landing zone hygiene"),
        arg("gov-placement", "Subscriptions by management group", placement_q, formatters=[
            status_fmt("Placement", good=["In hierarchy"], warn=["Under tenant root"]),
            status_fmt("State", good=["Enabled"], warn=["Warned", "PastDue"], bad=["Disabled", "Deleted"]),
        ], labels={"ManagementGroup": "Management group"}, width=50),
        arg("gov-locks", "Platform resources protected by a lock, by service", locks_q,
            formatters=[high_is_good("LockedPct", 100, 50, digits=0)],
            labels={"NotLocked": "Not locked", "LockedPct": "Locked %"}, width=50),
        arg("gov-orphans", "Orphaned resources", orphans_q, group_by="Kind", formatters=[resource_link()],
            labels={"id": "Resource"}, no_data="No unattached disks, unused public IPs or unattached network interfaces.",
            width=60),
        arg("gov-empty-rgs", "Empty resource groups", empty_rgs_q, formatters=[resource_link()],
            labels={"id": "Resource group"}, no_data="No empty resource groups.", width=40),
        text("gov-hygiene-note", "A lock at the resource, its resource group or its subscription counts. A resource "
             "group is *empty* when Resource Graph sees no resources in it; a few resource types are not indexed, "
             "so check before deleting one.", "info"),
        text("gov-patch-h", "### Patch compliance (Azure Update Manager)"),
        text("gov-patch-note", "Covers virtual machines and Arc-enabled servers in the selected subscriptions: AVD "
             "session hosts, domain controllers and build agents on Flexible scale sets. Update Manager does not "
             "assess Uniform scale set instances. Machines show as *Not assessed* until periodic assessment is "
             "turned on.", "info"),
        arg("gov-patch-tiles", "", patch_tiles_q, vis="tiles", tiles=big_number_tiles("Signal", "State", "Value", "Detail")),
        arg("gov-patch", "Pending patches by machine", patch_q, formatters=[
            resource_link(), low_is_good("Critical", 1, 1), low_is_good("Security", 1, 10),
            status_fmt("Assessment", good=["Succeeded"], warn=["Stale", "CompletedWithWarnings"], bad=["Failed"],
                       neutral=["Not assessed", "InProgress"]),
            status_fmt("RebootPending", warn=["true"]),
        ], labels={"id": "Machine", "RebootPending": "Reboot pending", "PatchMode": "Patch mode"},
            no_data="No virtual machines or Arc-enabled servers found."),
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
    alert_rule_types = "'microsoft.insights/metricalerts', 'microsoft.insights/scheduledqueryrules'"
    # Each platform resource is matched against rule scopes at three levels: itself, its resource group and its
    # subscription. A rule scoped above the resource only counts when it targets the resource's type.
    coverage_q = f"""
resources
| where type in~ ({TYPE_LIST})
| where type !~ 'microsoft.compute/virtualmachinescalesets' or name matches regex @'{{BuildAgentPattern}}'
| where type !~ 'microsoft.cdn/profiles' or tostring(sku.name) contains 'AzureFrontDoor'
| extend gatewayType = tostring(properties.gatewayType)
{SERVICE_CASE}
| extend rid = tolower(id), rtype = tolower(type), sub = tolower(strcat('/subscriptions/', subscriptionId))
| extend scopeKey = pack_array(rid, strcat(sub, '/resourcegroups/', tolower(resourceGroup)), sub)
| mv-expand scopeKey
| extend scopeKey = tostring(scopeKey)
| join kind=leftouter (
    resources
    | where type in~ ({alert_rule_types})
    | where tobool(properties.enabled)
    | mv-expand scope = properties.scopes
    | project scopeKey = tolower(tostring(scope)), ruleId = tolower(id),
        targetType = tolower(tostring(properties.targetResourceType))
  ) on scopeKey
| summarize DirectRules = dcountif(ruleId, isnotempty(ruleId) and scopeKey == rid),
    InheritedRules = dcountif(ruleId, isnotempty(ruleId) and scopeKey != rid and targetType == rtype)
    by id = rid, Service, ResourceGroup = resourceGroup
| extend Coverage = case(DirectRules > 0, 'Direct', InheritedRules > 0, 'Inherited', 'None')
| project id, Service, Coverage, DirectRules, InheritedRules, ResourceGroup
| order by case(Coverage == 'None', 0, Coverage == 'Inherited', 1, 2) asc, Service asc
"""
    silent_rules_q = f"""
resources
| where type in~ ({alert_rule_types}, 'microsoft.insights/activitylogalerts')
| extend Enabled = tobool(properties.enabled),
    ActionGroups = coalesce(array_length(properties.actions.actionGroups), array_length(properties.actions),
        array_length(properties.action.aznsAction.actionGroup), 0)
| where not(Enabled) or ActionGroups == 0
| project id,
    Kind = case(type =~ 'microsoft.insights/metricalerts', 'Metric',
        type =~ 'microsoft.insights/scheduledqueryrules', 'Log search', 'Activity log'),
    Problem = case(not(Enabled) and ActionGroups == 0, 'Disabled, no action group', not(Enabled), 'Disabled', 'No action group'),
    Severity = iff(isnull(properties.severity), '', strcat('Sev', tostring(properties.severity))),
    Scopes = array_length(properties.scopes),
    ResourceGroup = resourceGroup
| order by Problem asc, Kind asc
"""
    # Platform types that have diagnostic logs or metrics to send. Diagnostic settings are not in Resource Graph,
    # so coverage is judged from what actually arrived: the inventory comes from Resource Graph through arg(""),
    # joined to the last record each resource wrote to any table.
    logging_types = ", ".join(f"'{t}'" for t in [
        "microsoft.network/azurefirewalls", "microsoft.network/expressroutecircuits", "microsoft.network/vpngateways",
        "microsoft.network/p2svpngateways", "microsoft.network/virtualnetworkgateways", "microsoft.network/bastionhosts",
        "microsoft.keyvault/vaults", "microsoft.avs/privateclouds", "microsoft.desktopvirtualization/hostpools",
        "microsoft.storage/storageaccounts", "microsoft.recoveryservices/vaults",
    ])
    log_sources_q = f"""
arg("").Resources
| where type in~ ({logging_types})
| where type !~ 'microsoft.storage/storageaccounts' or name matches regex @'{{StoragePattern}}' or resourceGroup matches regex @'{{StoragePattern}}'
| project ResourceId = tolower(id), Type = type, ResourceGroup = resourceGroup
| join kind=leftouter (
    union withsource=SourceTable *
    | where TimeGenerated {{TimeRange}}
    | where _ResourceId has_any ('microsoft.network', 'microsoft.keyvault', 'microsoft.avs', 'microsoft.desktopvirtualization', 'microsoft.storage', 'microsoft.recoveryservices')
    | extend ResourceId = strcat_array(array_slice(split(tolower(_ResourceId), '/'), 0, 8), '/')
    | summarize LastRecord = max(TimeGenerated), Tables = strcat_array(make_set(SourceTable, 8), ', ') by ResourceId
  ) on ResourceId
| extend Status = case(isnull(LastRecord), 'No logs', LastRecord < ago(1d), 'Stale', 'Logging')
| project ResourceId, Status, LastRecord, Tables, Type, ResourceGroup
| order by case(Status == 'No logs', 0, Status == 'Stale', 1, 2) asc, Type asc
"""
    ingestion_delay_q = """
union withsource=SourceTable *
| where TimeGenerated {TimeRange} and TimeGenerated > ago(1d)
| extend DelayMin = (ingestion_time() - TimeGenerated) / 1m
| summarize Records = count(), MedianDelayMin = round(percentile(DelayMin, 50), 1),
    P95DelayMin = round(percentile(DelayMin, 95), 1), LastRecord = max(TimeGenerated) by SourceTable
| top 30 by P95DelayMin desc
"""
    dcr_associations = """
    insightsresources
    | where type =~ 'microsoft.insights/datacollectionruleassociations'
    | extend ruleId = tolower(tostring(properties.dataCollectionRuleId))
    | where isnotempty(ruleId)"""
    # A machine needs both the agent and at least one data collection rule before it sends anything; the
    # heartbeat table above can only list machines that already do.
    agents_q = """
resources
| where type in~ ('microsoft.compute/virtualmachines', 'microsoft.hybridcompute/machines', 'microsoft.compute/virtualmachinescalesets')
| extend Kind = case(type =~ 'microsoft.compute/virtualmachines', 'VM', type =~ 'microsoft.hybridcompute/machines', 'Arc server', 'Scale set'),
    modelAgent = tostring(properties.virtualMachineProfile.extensionProfile.extensions) contains 'AzureMonitor'
| project id = tolower(id), Kind, modelAgent,
    OS = coalesce(tostring(properties.storageProfile.osDisk.osType), tostring(properties.osType),
        tostring(properties.virtualMachineProfile.storageProfile.osDisk.osType)),
    ResourceGroup = resourceGroup
| join kind=leftouter (
    resources
    | where type in~ ('microsoft.compute/virtualmachines/extensions', 'microsoft.hybridcompute/machines/extensions')
    | where tostring(properties.type) in~ ('AzureMonitorWindowsAgent', 'AzureMonitorLinuxAgent')
    | project id = tostring(split(tolower(id), '/extensions/')[0]),
        agentState = tostring(properties.provisioningState), AgentVersion = tostring(properties.typeHandlerVersion)
  ) on id
| join kind=leftouter (""" + dcr_associations + """
    | extend id = tostring(split(tolower(id), '/providers/microsoft.insights/')[0])
    | summarize Rules = dcount(ruleId), RuleNames = strcat_array(make_set(tostring(split(ruleId, '/')[8])), ', ') by id
  ) on id
| extend Rules = coalesce(Rules, 0),
    Agent = case(Kind == 'Scale set', iff(modelAgent, 'In scale set model', 'Not installed'),
        isempty(agentState), 'Not installed', agentState)
| extend Status = case(Agent == 'Not installed', 'No agent', Agent =~ 'Failed', 'Agent failed',
    Rules == 0, 'No data collection rule', 'OK')
| project id, Status, Kind, OS, Agent, AgentVersion, Rules, RuleNames, ResourceGroup
| order by case(Status == 'OK', 1, 0) asc, Status asc, Kind asc
"""
    dcrs_q = """
resources
| where type =~ 'microsoft.insights/datacollectionrules'
| project id = tolower(id), Kind = kind,
    DataFlows = array_length(properties.dataFlows),
    Workspace = tostring(split(tostring(properties.destinations.logAnalytics[0].workspaceResourceId), '/')[8]),
    Workspaces = array_length(properties.destinations.logAnalytics),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup
| join kind=leftouter (""" + dcr_associations + """
    | summarize Associations = count() by id = ruleId
  ) on id
| project id, Kind, Associations = coalesce(Associations, 0), DataFlows, Workspace, Workspaces, Provisioning, ResourceGroup
| order by Associations asc
"""
    # Alerts on platform resources fired in the time range. The alerts table keeps 30 days.
    alert_history = f"""
alertsmanagementresources
| where type =~ 'microsoft.alertsmanagement/alerts'
| extend e = properties.essentials
| extend Fired = todatetime(e.startDateTime)
| where Fired >= todatetime('{{TimeRange:startISO}}')
| where tolower(tostring(e.targetResourceType)) in~ ({TYPE_LIST})
"""
    alerts_per_day_q = alert_history + "| summarize Alerts = count() by bin(Fired, 1d), Severity = tostring(e.severity)\n| order by Fired asc"
    noisy_rules_q = alert_history + """| extend Resolved = todatetime(e.monitorConditionResolvedDateTime), isOpen = tostring(e.monitorCondition) =~ 'Fired'
| summarize Alerts = count(), OpenNow = countif(isOpen), Resources = dcount(tolower(tostring(e.targetResource))),
    AvgMinutesOpen = round(avgif(datetime_diff('minute', Resolved, Fired), isnotnull(Resolved)), 0),
    LastFired = max(Fired)
    by Rule = name, Severity = tostring(e.severity)
| top 50 by Alerts desc
"""
    # Action groups hang off rules in a different shape per rule type: metric alerts hold objects in
    # properties.actions, the other two hold ids or objects in properties.actions.actionGroups.
    action_groups_q = f"""
resources
| where type =~ 'microsoft.insights/actiongroups'
| extend p = properties
| extend Email = coalesce(array_length(p.emailReceivers), 0),
    SmsVoicePush = coalesce(array_length(p.smsReceivers), 0) + coalesce(array_length(p.voiceReceivers), 0)
        + coalesce(array_length(p.azureAppPushReceivers), 0),
    ArmRole = coalesce(array_length(p.armRoleReceivers), 0),
    Webhook = coalesce(array_length(p.webhookReceivers), 0),
    Automation = coalesce(array_length(p.logicAppReceivers), 0) + coalesce(array_length(p.azureFunctionReceivers), 0)
        + coalesce(array_length(p.automationRunbookReceivers), 0) + coalesce(array_length(p.eventHubReceivers), 0)
        + coalesce(array_length(p.itsmReceivers), 0)
| extend Receivers = Email + SmsVoicePush + ArmRole + Webhook + Automation
| project id = tolower(id),
    Status = case(not(tobool(p.enabled)), 'Disabled', Receivers == 0, 'No receivers', 'OK'),
    Email, SmsVoicePush, ArmRole, Webhook, Automation, ResourceGroup = resourceGroup
| join kind=leftouter (
    resources
    | where type in~ ({alert_rule_types}, 'microsoft.insights/activitylogalerts')
    | extend ruleId = tolower(id),
        groups = iff(type =~ 'microsoft.insights/metricalerts', properties.actions, properties.actions.actionGroups)
    | mv-expand g = groups
    | extend id = tolower(coalesce(tostring(g.actionGroupId), tostring(g)))
    | summarize AlertRules = dcount(ruleId) by id
  ) on id
| project id, Status, AlertRules = coalesce(AlertRules, 0), Email, SmsVoicePush, ArmRole, Webhook, Automation, ResourceGroup
| order by case(Status == 'OK', 1, 0) asc, AlertRules desc
"""
    health_alerts_q = """
resourcecontainers
| where type =~ 'microsoft.resources/subscriptions'
| project subscriptionId, Subscription = name
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.insights/activitylogalerts'
    | where tobool(properties.enabled)
    | extend condition = tolower(tostring(properties.condition))
    | mv-expand scope = properties.scopes
    | extend subscriptionId = tostring(split(tolower(tostring(scope)), '/')[2])
    | summarize ServiceHealth = countif(condition contains 'servicehealth'),
        ResourceHealth = countif(condition contains 'resourcehealth') by subscriptionId
  ) on subscriptionId
| extend ServiceHealth = coalesce(ServiceHealth, 0), ResourceHealth = coalesce(ResourceHealth, 0)
| project Subscription,
    Status = case(ServiceHealth > 0 and ResourceHealth > 0, 'Both', ServiceHealth > 0, 'No Resource Health alert',
        ResourceHealth > 0, 'No Service Health alert', 'Neither'),
    ServiceHealth, ResourceHealth
| order by case(Status == 'Both', 1, 0) asc, Subscription asc
"""
    # Protected items only list what is enrolled, so a machine that was never added to a vault is found by
    # starting from the machines instead.
    vm_protection_q = """
resources
| where type =~ 'microsoft.compute/virtualmachines'
| project id = tolower(id),
    OS = tostring(properties.storageProfile.osDisk.osType),
    Power = tostring(properties.extended.instanceView.powerState.displayStatus),
    ResourceGroup = resourceGroup, Location = location
| join kind=leftouter (
    recoveryservicesresources
    | where type =~ 'microsoft.recoveryservices/vaults/backupfabrics/protectioncontainers/protecteditems'
    | where tostring(properties.backupManagementType) =~ 'AzureIaasVM'
    | project vmId = tolower(coalesce(tostring(properties.sourceResourceId), tostring(properties.virtualMachineId))),
        vault = tostring(split(id, '/')[8]), lastBackup = todatetime(properties.lastBackupTime)
    | where isnotempty(vmId)
    | summarize Vault = max(vault), LastBackup = max(lastBackup) by id = vmId
  ) on id
| project id, Protection = iff(isempty(Vault), 'Not protected', 'Protected'), Vault, LastBackup, OS, Power, ResourceGroup, Location
| order by case(Protection == 'Not protected', 0, 1) asc, ResourceGroup asc
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
        text("mgmt-agents-h", "### Agents and data collection"),
        arg("mgmt-agents", "Azure Monitor Agent and data collection rules by machine", agents_q, formatters=[
            resource_link(),
            status_fmt("Status", good=["OK"], warn=["No data collection rule"], bad=["No agent", "Agent failed"]),
        ], labels={"id": "Machine", "AgentVersion": "Agent version", "Rules": "Data collection rules",
                   "RuleNames": "Rule names"},
            no_data="No virtual machines, scale sets or Arc-enabled servers found.", width=60),
        arg("mgmt-dcrs", "Data collection rules", dcrs_q, formatters=[resource_link(), PROVISIONING],
            labels={"id": "Rule", "DataFlows": "Data flows", "Workspace": "First workspace"},
            no_data="No data collection rules found.", width=40),
        text("mgmt-agents-note", "Scale sets show whether the agent is in the scale set model; their instances are "
             "not listed individually. A rule with no associations collects nothing, which is expected only for "
             "workspace transformation and direct-ingestion rules.", "info"),
        text("mgmt-sources-h", "### Log sources"),
        text("mgmt-sources-note",
             "Shows whether each platform resource is actually writing to the selected workspace. *No logs* means "
             "nothing arrived in the time range: the diagnostic setting is missing, points at another workspace, or "
             "the resource stopped sending. *Stale* means nothing in the last day. The inventory covers every "
             "subscription you can read (up to 1,000 resources), not only the ones selected at the top, and both "
             "queries scan every table, so they are slow on long time ranges.", "info", visible_when=WORKSPACE_SET),
        la("mgmt-log-sources", "Platform resources by last record in the workspace", log_sources_q, formatters=[
            resource_link("ResourceId"), status_fmt("Status", good=["Logging"], warn=["Stale"], bad=["No logs"]),
        ], labels={"ResourceId": "Resource", "LastRecord": "Last record"}, width=60),
        la("mgmt-ingestion-delay", "Ingestion delay by table (last 24 hours at most)", ingestion_delay_q, formatters=[
            low_is_good("P95DelayMin", 15, 60, digits=1),
        ], labels={"SourceTable": "Table", "MedianDelayMin": "Median delay (min)", "P95DelayMin": "P95 delay (min)",
                   "LastRecord": "Last record"}, width=40),
        text("mgmt-alerting-h", "### Alerting coverage"),
        text("mgmt-alerting-note",
             "*Fired alerts* on the Overview only shows rules that exist. This shows where nothing would fire. "
             "A resource is covered **directly** by an enabled metric or log search rule scoped to it, or by "
             "**inheritance** from a metric rule scoped to its resource group or subscription that targets its type. "
             "Log search rules scoped to a workspace and activity log (Resource Health, Service Health) alerts scoped "
             "to a subscription can't be tied to one resource, so they aren't counted; *Notification path* below shows "
             "which subscriptions have them. A rule with no action group may still notify through an alert "
             "processing rule.", "info"),
        arg("mgmt-alert-coverage", "Platform resources by alert rule coverage", coverage_q, formatters=[
            resource_link(), status_fmt("Coverage", good=["Direct", "Inherited"], warn=["None"]),
        ], labels={"id": "Resource", "DirectRules": "Direct rules", "InheritedRules": "Inherited rules"},
            no_data="No platform resources found in the selected subscriptions.", width=55),
        arg("mgmt-alert-silent", "Alert rules that are disabled or have no action group", silent_rules_q,
            formatters=[resource_link(), status_fmt("Problem", warn=["Disabled", "No action group", "Disabled, no action group"])],
            labels={"id": "Alert rule"},
            no_data="Every alert rule is enabled and has an action group.", width=45),
        arg("mgmt-alerts-per-day", "Alerts fired per day by severity (time range, up to 30 days)", alerts_per_day_q,
            vis="barchart", no_data="No alerts fired on platform resources in the time range.", width=40),
        arg("mgmt-alert-noise", "Alert rules that fire most", noisy_rules_q, formatters=[
            low_is_good("OpenNow", 1, 1),
        ], labels={"OpenNow": "Open now", "AvgMinutesOpen": "Avg minutes open", "LastFired": "Last fired"},
            no_data="No alerts fired on platform resources in the time range.", width=60),
        text("mgmt-notify-h", "### Notification path"),
        arg("mgmt-action-groups", "Action groups", action_groups_q, formatters=[
            resource_link(), status_fmt("Status", good=["OK"], warn=["No receivers"], bad=["Disabled"]),
        ], labels={"id": "Action group", "AlertRules": "Alert rules using it", "SmsVoicePush": "SMS / voice / push",
                   "ArmRole": "ARM role", "Automation": "Automation (Logic App, Function, runbook, Event Hub, ITSM)"},
            no_data="No action groups found.", width=60),
        arg("mgmt-health-alerts", "Service Health and Resource Health alerts by subscription", health_alerts_q,
            formatters=[status_fmt("Status", good=["Both"], warn=["No Resource Health alert", "No Service Health alert"],
                                   bad=["Neither"])],
            labels={"ServiceHealth": "Service Health alerts", "ResourceHealth": "Resource Health alerts"}, width=40),
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
        arg("mgmt-vm-protection", "Virtual machines by backup protection", vm_protection_q, formatters=[
            resource_link(), status_fmt("Protection", good=["Protected"], bad=["Not protected"]),
        ], labels={"id": "Virtual machine", "LastBackup": "Last backup"},
            no_data="No virtual machines found."),
        text("mgmt-vm-protection-note", "Pooled AVD session hosts and scale set build agents are normally rebuilt "
             "from an image, so *Not protected* is expected for them.", "info"),
        arg("mgmt-asr", "Site Recovery replicated items", asr_q,
            formatters=[status_fmt("Health", good=["Normal"], warn=["Warning"], bad=["Critical"])],
            no_data="No Site Recovery replicated items."),
    ], tab="management")


def throughput_tab():
    fw = "microsoft.network/azurefirewalls"
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
            resource_param("TpFirewalls", "Firewalls", Q_FIREWALLS, hidden_when_locked=True),
            resource_param("TpCircuits", "Circuits", Q_CIRCUITS, hidden_when_locked=True),
            resource_param("TpErGateways", "ER gateways", Q_ER_GATEWAYS, hidden_when_locked=True),
            resource_param("TpVpnGateways", "VPN gateways", Q_VPN_GATEWAYS, hidden_when_locked=True),
            resource_param("TpP2SGateways", "P2S gateways", Q_P2S_GATEWAYS, hidden_when_locked=True),
            resource_param("TpStorage", "Storage accounts", Q_STORAGE, hidden_when_locked=True),
        ]),
        metrics("tp-fw-data", "Azure Firewall data processed", fw, "TpFirewalls", [m(fw, "DataProcessed", SUM)], width=50),
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
            "id": gid("param-DcPattern"),
            "version": "KqlParameterItem/1.0",
            "name": "DcPattern",
            "label": "Domain controller name pattern",
            "type": 1,
            "isRequired": True,
            "value": "(?i)(dc|adds)",
            "description": "Regex matched against virtual machine and computer names on the Identity tab.",
        },
        {
            "id": gid("param-StoragePattern"),
            "version": "KqlParameterItem/1.0",
            "name": "StoragePattern",
            "label": "Storage account pattern",
            "type": 1,
            "isRequired": True,
            "value": "(?i)(fslogix|profile|avd|wvd)",
            "description": "Regex matched against storage account and resource group names on the Storage and "
                           "Throughput tabs. Metric charts handle at most 200 accounts; use '.' for all.",
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
                 "ExpressRoute, VPN, end-to-end connectivity tests), application delivery, shared services, identity, Azure VMware Solution, Azure Virtual Desktop, storage, "
                 "build agents, governance, security, monitoring and backup."),
            global_params(),
            tabs(),
            overview_tab(),
            vwan_tab(),
            firewall_tab(),
            expressroute_tab(),
            vpn_tab(),
            connectivity_tab(),
            appdelivery_tab(),
            shared_tab(),
            identity_tab(),
            buildagents_tab(),
            avs_tab(),
            avd_tab(),
            storage_tab(),
            governance_tab(),
            security_tab(),
            management_tab(),
            capacity_tab(),
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
