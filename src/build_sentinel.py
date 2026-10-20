"""Generates the Microsoft Sentinel operations workbook.

Run:  python src/build_sentinel.py
Out:  workbook/sentinel.workbook.json

For the platform team that runs Sentinel, not for the analysts who work its incidents: is Sentinel collecting what
it should, are its detections and automation running, is the incident queue being worked, what does it cost, and
is Purview data arriving? Reads the Sentinel workspace (usage, health and audit, incidents, alerts), Resource Graph
(workspace settings, playbooks) and Azure Resource Manager (analytics rules, automation rules, data connectors,
table plans). Built from the helpers in build_workbook.py so the workbooks look alike.

Detection and automation health need Sentinel's *Auditing and health monitoring* turned on (tables SentinelHealth
and SentinelAudit).
"""

import pathlib

from build_workbook import (DAY_MS, ONE_TILE, SUM, arg, arm, big_number_tiles, choice_param, gid, group, la, m,
                            metrics, notebook, params, resource_link, resource_param, status_fmt, subscription_param,
                            text, time_param, write_workbook)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "sentinel.workbook.json"

P = "snt"
SI = "{Workspace}/providers/Microsoft.SecurityInsights"
SI_API = "2024-03-01"

TABS = [
    ("overview", "Overview"),
    ("data", "Data collection"),
    ("detections", "Detections"),
    ("incidents", "Incidents"),
    ("automation", "Automation"),
    ("cost", "Cost and retention"),
    ("purview", "Purview"),
]

SEVERITY_ORDER = "case(Severity == 'High', 0, Severity == 'Medium', 1, Severity == 'Low', 2, 3)"
SEVERITY = status_fmt("Severity", warn=["Medium"], bad=["High"], neutral=["Low", "Informational"])
HEALTH_STATUS = status_fmt("Status", good=["Success"], warn=["Partial success", "Warning"], bad=["Failure"])


def fixed_window(item, days):
    """Run a log query over the last `days` days whatever the time range picker says: a baseline, or incidents
    that may not have changed within the picked range."""
    item["content"].pop("timeContextFromParameter", None)
    item["content"]["timeContext"] = {"durationMs": days * DAY_MS}
    return item


# ---------------------------------------------------------------------------
# Shared log fragments
# ---------------------------------------------------------------------------

# Every table's last record and volume from the Usage table, which is cheap to read and covers every table. The
# last 24 hours are compared with the daily average of the 7 days before. Run over a fixed 8 days.
FRESHNESS = """
Usage
| where TimeGenerated > ago(8d)
| summarize LastSeen = max(TimeGenerated),
    GBLast24h = round(sumif(Quantity, TimeGenerated > ago(1d)) / 1000.0, 2),
    GBDailyAvg = round(sumif(Quantity, TimeGenerated <= ago(1d)) / 1000.0 / 7.0, 2),
    Billable = take_any(IsBillable)
    by Table = DataType
| extend HoursSinceData = datetime_diff('hour', now(), LastSeen)
| extend Status = case(HoursSinceData >= {SilentHours}, 'Silent',
    GBDailyAvg >= 0.01 and GBLast24h < 0.5 * GBDailyAvg, 'Dropped',
    GBDailyAvg >= 0.01 and GBLast24h > 2.0 * GBDailyAvg, 'Spiked', 'Normal')"""

# The latest health record per Sentinel resource (data connector, analytics rule, automation rule, playbook).
HEALTH = """
union isfuzzy=true
    (datatable(TimeGenerated:datetime, SentinelResourceId:string, SentinelResourceName:string, SentinelResourceType:string,
        Status:string, Description:string, OperationName:string)[]),
    (SentinelHealth)
| where TimeGenerated {TimeRange}"""

# SecurityIncident gets a new row on every change, so the latest row per incident is its current state. Run over a
# fixed 90 days, so an open incident nobody has touched in the picked time range still counts.
INCIDENTS = """
let incidents = union isfuzzy=true
    (datatable(TimeGenerated:datetime, IncidentNumber:int, Title:string, Severity:string, Status:string, Owner:dynamic,
        CreatedTime:datetime, FirstModifiedTime:datetime, ClosedTime:datetime, Classification:string,
        ClassificationReason:string, ProviderName:string, IncidentUrl:string, RelatedAnalyticRuleIds:dynamic,
        AdditionalData:dynamic)[]),
    (SecurityIncident)
| where TimeGenerated > ago(90d)
| summarize arg_max(TimeGenerated, *) by IncidentNumber
| extend Assignee = tostring(Owner.assignedTo), Product = tostring(AdditionalData.alertProductNames[0]);
"""

ALERTS = """
union isfuzzy=true
    (datatable(TimeGenerated:datetime, AlertName:string, AlertSeverity:string, ProductName:string, ProviderName:string,
        ExtendedProperties:string, SystemAlertId:string)[]),
    (SecurityAlert)
| where TimeGenerated {TimeRange}"""

# Analytics rule id and name from an alert raised by a Sentinel rule.
ALERT_RULES = ALERTS + """
| extend ep = todynamic(ExtendedProperties)
| extend RuleId = tolower(tostring(split(tostring(todynamic(tostring(ep['Analytic Rule Ids']))[0]), '/')[-1])),
    Rule = tostring(ep['Analytic Rule Name'])
| where isnotempty(RuleId)"""

# ---------------------------------------------------------------------------
# Overview tiles
# ---------------------------------------------------------------------------

LA_TILES = [
    ("silent", 8, FRESHNESS + """
| summarize Silent = countif(Status == 'Silent'), Dropped = countif(Status == 'Dropped'), Total = count()
| project Signal = 'Tables gone silent', Value = Silent,
    Detail = strcat(Dropped, ' dropped by half · of ', Total, ' tables'),
    State = case(Silent > 0, 'Unavailable', Dropped > 0, 'Degraded', 'Available')
"""),
    ("health", None, HEALTH + """
| summarize arg_max(TimeGenerated, Status) by SentinelResourceId, SentinelResourceType
| summarize Failing = countif(Status !~ 'Success'), Total = count()
| project Signal = 'Connectors, rules and automation failing', Value = Failing,
    Detail = iff(Total == 0, 'no health records: turn on health monitoring', strcat('of ', Total, ' reporting health')),
    State = case(Total == 0, 'Unknown', Failing > 0, 'Unavailable', 'Available')
"""),
    ("high", 90, INCIDENTS + """incidents
| where Status != 'Closed' and Severity == 'High'
| summarize Open = count(), Unassigned = countif(isempty(Assignee))
| project Signal = 'Open high-severity incidents', Value = Open, Detail = strcat(Unassigned, ' unassigned'),
    State = case(Unassigned > 0, 'Unavailable', Open > 0, 'Degraded', 'Available')
"""),
    ("untriaged", 90, INCIDENTS + """incidents
| where Status == 'New' and Severity in ('High', 'Medium') and CreatedTime < ago({TriageHours}h)
| summarize Late = count(), High = countif(Severity == 'High')
| project Signal = 'Not triaged within {TriageHours} h', Value = Late, Detail = strcat(High, ' high · medium and high, still New'),
    State = case(High > 0, 'Unavailable', Late > 0, 'Degraded', 'Available')
"""),
]

ACTIVITY_COVERAGE = """
arg("").ResourceContainers
| where type =~ 'microsoft.resources/subscriptions'
| project SubscriptionId = tolower(subscriptionId), Subscription = name, State = tostring(properties.state)
| join kind=leftouter (
    union isfuzzy=true (datatable(TimeGenerated:datetime, SubscriptionId:string)[]), (AzureActivity)
    | where TimeGenerated {TimeRange}
    | summarize Records = count(), LastRecord = max(TimeGenerated) by SubscriptionId = tolower(SubscriptionId)
  ) on SubscriptionId
| extend Status = case(isnull(LastRecord), 'Not sending', LastRecord < ago(1d), 'Stale', 'Sending')"""

ACTIVITY_TILE = ACTIVITY_COVERAGE + """
| where State =~ 'Enabled'
| summarize Missing = countif(Status != 'Sending'), Total = count()
| project Signal = 'Subscriptions not sending activity log', Value = Missing, Detail = strcat('of ', Total, ' enabled subscriptions'),
    State = iff(Missing > 0, 'Degraded', 'Available')
"""

WORKSPACE_TILE = """
resources
| where id =~ '{Workspace}'
| extend Cap = todouble(properties.workspaceCapping.dailyQuotaGb), Retention = toint(properties.retentionInDays)
| project Signal = 'Retention (days)', Value = Retention,
    Detail = iff(Cap > 0, strcat('daily cap ', Cap, ' GB: security data stops when hit'), 'no daily cap'),
    State = case(Cap > 0, 'Unavailable', Retention < 90, 'Degraded', 'Available')
"""

TILE_NOTE = """\
A table is *silent* when nothing has arrived for **{SilentHours} hours** and *dropped* when the last 24 hours
brought in less than half its daily average of the 7 days before. An incident is *not triaged* when it is still
**New** after **{TriageHours} hours**. Incidents are counted over the last 90 days whatever the time range.
A daily cap on a Sentinel workspace stops security data arriving when it is reached, and Sentinel includes 90 days
of retention, so less than that is usually a mistake."""

# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

FRESHNESS_Q = FRESHNESS + """
| project Table, Status, LastSeen, HoursSinceData, GBLast24h, GBDailyAvg, Billable
| order by case(Status == 'Silent', 0, Status == 'Dropped', 1, Status == 'Spiked', 2, 3) asc, GBDailyAvg desc
"""

INGESTION_Q = """
Usage
| where TimeGenerated {TimeRange}
| summarize GB = sum(Quantity) / 1000.0 by DataType
| top 10 by GB desc
| join kind=inner (
    Usage
    | where TimeGenerated {TimeRange}
    | summarize GB = sum(Quantity) / 1000.0 by bin(TimeGenerated, {TimeRange:grain}), DataType
  ) on DataType
| project TimeGenerated, DataType, GB = GB1
"""

CONNECTOR_HEALTH_Q = HEALTH + """
| where SentinelResourceType =~ 'Data connector'
| summarize arg_max(TimeGenerated, Status, Description), Failures = countif(Status !~ 'Success')
    by Connector = SentinelResourceName, Kind = tostring(column_ifexists('SentinelResourceKind', ''))
| project Connector, Kind, Status, Failures, LastReport = TimeGenerated, Detail = substring(Description, 0, 300)
| order by case(Status =~ 'Failure', 0, Status !~ 'Success', 1, 2) asc, Failures desc
"""

ACTIVITY_COVERAGE_Q = ACTIVITY_COVERAGE + """
| project Subscription, SubscriptionId, State, Status, Records, LastRecord
| order by case(State !~ 'Enabled', 3, Status == 'Not sending', 0, Status == 'Stale', 1, 2) asc, Subscription asc
"""

# ---------------------------------------------------------------------------
# Detections
# ---------------------------------------------------------------------------

RULE_HEALTH_Q = HEALTH + """
| where SentinelResourceType =~ 'Analytics Rule'
| extend IssueTime = iff(Status !~ 'Success', TimeGenerated, datetime(null)), Issue = substring(Description, 0, 300)
| summarize Runs = count(), Failures = countif(Status !~ 'Success'), (LastIssueTime, LastIssue) = arg_max(IssueTime, Issue),
    (LastRun, LastStatus) = arg_max(TimeGenerated, Status)
    by Rule = SentinelResourceName, Kind = tostring(column_ifexists('SentinelResourceKind', ''))
| where Failures > 0
| project Rule, Kind, Status = LastStatus, Failures, Runs, LastIssueTime, LastIssue, LastRun
| order by case(Status =~ 'Failure', 0, 1) asc, Failures desc
"""

NOISY_RULES_Q = ALERT_RULES + """
| summarize Alerts = count(), Severity = take_any(AlertSeverity), LastAlert = max(TimeGenerated) by Rule
| top 25 by Alerts desc
"""

# Rules whose closed incidents are mostly false or benign positives: candidates for tuning.
TUNING_Q = INCIDENTS + """incidents
| where Status == 'Closed' and ClosedTime >= todatetime('{TimeRange:startISO}')
| mv-expand RuleId = RelatedAnalyticRuleIds to typeof(string)
| extend RuleId = tolower(tostring(split(RuleId, '/')[-1]))
| where isnotempty(RuleId)
| summarize Closed = count(), TruePositive = countif(Classification == 'TruePositive'),
    BenignPositive = countif(Classification == 'BenignPositive'), FalsePositive = countif(Classification == 'FalsePositive'),
    Undetermined = countif(Classification == 'Undetermined' or isempty(Classification)), AnyTitle = take_any(Title)
    by RuleId
| join kind=leftouter (
""" + ALERT_RULES.replace("\n", "\n    ").replace("{TimeRange}", "> ago(90d)") + """
    | summarize Rule = take_any(Rule) by RuleId
  ) on RuleId
| extend Rule = coalesce(Rule, AnyTitle), NotTruePct = round(100.0 * (Closed - TruePositive) / Closed, 0)
| where Closed >= 3
| project Rule, Closed, NotTruePct, FalsePositive, BenignPositive, Undetermined, TruePositive
| order by NotTruePct desc, Closed desc
"""

# Rules that ran in the time range but raised no alert. Often fine (nothing to detect), but worth a look for a rule
# that matches on a table that has gone silent or a column that was renamed.
QUIET_RULES_Q = HEALTH + """
| where SentinelResourceType =~ 'Analytics Rule' and Status =~ 'Success'
| summarize Runs = count(), LastRun = max(TimeGenerated)
    by RuleId = tolower(tostring(split(SentinelResourceId, '/')[-1])), Rule = SentinelResourceName
| join kind=leftanti (
""" + ALERT_RULES.replace("\n", "\n    ") + """
    | distinct RuleId
  ) on RuleId
| project Rule, Runs, LastRun
| order by Rule asc
"""

AUDIT_Q = """
union isfuzzy=true
    (datatable(TimeGenerated:datetime, OperationName:string, SentinelResourceName:string, SentinelResourceType:string,
        Status:string, ExtendedProperties:dynamic)[]),
    (SentinelAudit)
| where TimeGenerated {TimeRange}
| project TimeGenerated, Type = SentinelResourceType, Resource = SentinelResourceName, Operation = OperationName, Status,
    Caller = tostring(ExtendedProperties.CallerName), CallerIp = tostring(ExtendedProperties.CallerIpAddress)
| order by TimeGenerated desc
| take 500
"""

# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

BACKLOG_Q = INCIDENTS + """incidents
| where Status != 'Closed'
| extend AgeDays = datetime_diff('day', now(), CreatedTime)
| summarize Open = count(), Unassigned = countif(isempty(Assignee)), New = countif(Status == 'New'),
    UnderADay = countif(AgeDays < 1), OneToSevenDays = countif(AgeDays between (1 .. 6)),
    SevenToThirtyDays = countif(AgeDays between (7 .. 29)), OverThirtyDays = countif(AgeDays >= 30)
    by Severity
| order by """ + SEVERITY_ORDER + """ asc
"""

UNTRIAGED_Q = INCIDENTS + """incidents
| where Status == 'New' and CreatedTime < ago({TriageHours}h)
| project Incident = IncidentNumber, Title, Severity, Owner = iff(isempty(Assignee), 'Unassigned', Assignee),
    Created = CreatedTime, AgeHours = datetime_diff('hour', now(), CreatedTime), Product, IncidentUrl
| order by """ + SEVERITY_ORDER + """ asc, Created asc
"""

RESPONSE_Q = INCIDENTS + """incidents
| where CreatedTime >= todatetime('{TimeRange:startISO}')
| extend TriageMin = datetime_diff('minute', FirstModifiedTime, CreatedTime),
    CloseHours = iff(Status == 'Closed', datetime_diff('minute', ClosedTime, CreatedTime) / 60.0, real(null))
| summarize Created = count(), Closed = countif(Status == 'Closed'),
    MedianMinutesToTriage = round(percentile(TriageMin, 50), 0), P90MinutesToTriage = round(percentile(TriageMin, 90), 0),
    MedianHoursToClose = round(percentile(CloseHours, 50), 1), P90HoursToClose = round(percentile(CloseHours, 90), 1)
    by Severity
| order by """ + SEVERITY_ORDER + """ asc
"""

OWNERS_Q = INCIDENTS + """incidents
| extend Owner = iff(isempty(Assignee), 'Unassigned', Assignee)
| summarize Open = countif(Status != 'Closed'), OpenHigh = countif(Status != 'Closed' and Severity == 'High'),
    ClosedInRange = countif(Status == 'Closed' and ClosedTime >= todatetime('{TimeRange:startISO}')),
    MedianHoursToClose = round(percentile(iff(Status == 'Closed' and ClosedTime >= todatetime('{TimeRange:startISO}'),
        datetime_diff('minute', ClosedTime, CreatedTime) / 60.0, real(null)), 50), 1)
    by Owner
| where Open > 0 or ClosedInRange > 0
| order by Open desc
"""

SOURCES_Q = INCIDENTS + """incidents
| where Status == 'Closed' and ClosedTime >= todatetime('{TimeRange:startISO}')
| summarize Closed = count(), TruePositive = countif(Classification == 'TruePositive'),
    BenignPositive = countif(Classification == 'BenignPositive'), FalsePositive = countif(Classification == 'FalsePositive'),
    Undetermined = countif(Classification == 'Undetermined' or isempty(Classification))
    by Source = coalesce(Product, ProviderName)
| extend TruePositivePct = round(100.0 * TruePositive / Closed, 0)
| order by Closed desc
"""

CREATED_Q = INCIDENTS + """incidents
| where CreatedTime >= todatetime('{TimeRange:startISO}')
| summarize Incidents = count() by Day = bin(CreatedTime, 1d), Severity
"""

# ---------------------------------------------------------------------------
# Automation
# ---------------------------------------------------------------------------

AUTOMATION_HEALTH_Q = HEALTH + """
| where SentinelResourceType in~ ('Automation rule', 'Playbook')
| extend IssueTime = iff(Status !~ 'Success', TimeGenerated, datetime(null)), Issue = substring(Description, 0, 300)
| summarize Runs = count(), Failures = countif(Status !~ 'Success'), (LastIssueTime, LastIssue) = arg_max(IssueTime, Issue),
    LastRun = max(TimeGenerated)
    by Type = SentinelResourceType, Resource = SentinelResourceName
| order by Failures desc, Runs desc
"""

Q_PLAYBOOKS = """resources
| where type =~ 'microsoft.logic/workflows'
| where tostring(properties.parameters) has 'azuresentinel' or tostring(properties.definition.triggers) has 'azuresentinel'"""

PLAYBOOKS_Q = Q_PLAYBOOKS + """
| project id, State = tostring(properties.state), Identity = tostring(identity.type),
    Trigger = tostring(bag_keys(properties.definition.triggers)[0]),
    Changed = todatetime(properties.changedTime), ResourceGroup = resourceGroup
| order by State asc, id asc
"""

# ---------------------------------------------------------------------------
# Cost and retention
# ---------------------------------------------------------------------------

WORKSPACE_Q = """
resources
| where id =~ '{Workspace}'
| project id, Tier = tostring(properties.sku.name), CommitmentGBPerDay = toint(properties.sku.capacityReservationLevel),
    RetentionDays = toint(properties.retentionInDays), DailyCapGB = todouble(properties.workspaceCapping.dailyQuotaGb),
    Ingestion = tostring(properties.workspaceCapping.dataIngestionStatus),
    PublicIngestion = tostring(properties.publicNetworkAccessForIngestion),
    PublicQuery = tostring(properties.publicNetworkAccessForQuery),
    ResourcePermissions = tostring(properties.features.enableLogAccessUsingOnlyResourcePermissions),
    Location = location
"""

BILLABLE_DAILY_Q = """
Usage
| where TimeGenerated {TimeRange}
| summarize GB = sum(Quantity) / 1000.0 by Day = bin(TimeGenerated, 1d), Kind = iff(IsBillable, 'Billable', 'Free')
"""

BILLABLE_TABLES_Q = """
Usage
| where TimeGenerated {TimeRange}
| where IsBillable
| summarize GB = round(sum(Quantity) / 1000.0, 2), Days = dcount(bin(TimeGenerated, 1d)) by Table = DataType, Solution
| extend GBPerDay = round(GB / Days, 2)
| project Table, Solution, GB, GBPerDay
| order by GB desc
"""

DAILY_AVG_Q = """
Usage
| where TimeGenerated {TimeRange}
| where IsBillable
| summarize GB = sum(Quantity) / 1000.0 by Day = bin(TimeGenerated, 1d)
| summarize AvgGBPerDay = round(avg(GB), 1), PeakGBPerDay = round(max(GB), 1), LowestGBPerDay = round(min(GB), 1), Days = count()
"""

# ---------------------------------------------------------------------------
# Purview
# ---------------------------------------------------------------------------

PURVIEW_TABLES = "'MicrosoftPurviewInformationProtection', 'PurviewDataSensitivityLogs', 'OfficeActivity', 'AlertInfo', 'AlertEvidence', 'SecurityAlert'"

PURVIEW_FRESHNESS_Q = FRESHNESS + f"""
| where Table in ({PURVIEW_TABLES})
| project Table, Status, LastSeen, HoursSinceData, GBLast24h, GBDailyAvg
| order by Table asc
"""

PURVIEW_ALERTS = ALERTS + """
| where ProductName has_any ('Data Loss Prevention', 'Insider Risk', 'Purview', 'Information Protection', 'Communication Compliance')"""

PURVIEW_TREND_Q = PURVIEW_ALERTS + """
| summarize Alerts = count() by bin(TimeGenerated, {TimeRange:grain}), ProductName
"""

PURVIEW_TOP_Q = PURVIEW_ALERTS + """
| summarize Alerts = count(), LastSeen = max(TimeGenerated) by Product = ProductName, Alert = AlertName, Severity = AlertSeverity
| top 50 by Alerts desc
"""

MIP = """
union isfuzzy=true (datatable(TimeGenerated:datetime)[]), (MicrosoftPurviewInformationProtection)
| where TimeGenerated {TimeRange}
| extend Operation = tostring(column_ifexists('Operation', '')), Workload = tostring(column_ifexists('Workload', '')),
    User = tostring(column_ifexists('UserId', ''))"""

MIP_OPERATIONS_Q = MIP + """
| summarize Events = count(), Users = dcount(User) by Workload, Operation
| top 40 by Events desc
"""

MIP_REMOVALS_Q = MIP + """
| where Operation has_any ('Removed', 'Downgrade')
| summarize Events = count(), LastSeen = max(TimeGenerated) by User, Operation, Workload
| top 50 by Events desc
"""

# ---------------------------------------------------------------------------
# Parameters and tabs
# ---------------------------------------------------------------------------


def global_params():
    workspace = {
        "id": gid(f"{P}-param-Workspace"), "version": "KqlParameterItem/1.0", "name": "Workspace",
        "label": "Sentinel workspace", "type": 5, "isRequired": True, "multiSelect": False,
        "query": "resources\n| where type =~ 'microsoft.operationsmanagement/solutions'\n"
                 "| where name startswith 'SecurityInsights('\n| project id = tostring(properties.workspaceResourceId)",
        "crossComponentResources": ["{Subscription}"],
        "typeSettings": {"resourceTypeFilter": {"microsoft.operationalinsights/workspaces": True},
                         "additionalResourceOptions": ["value::1"], "showDefault": False},
        "defaultValue": "value::1", "queryType": 1, "resourceType": "microsoft.resourcegraph/resources",
        "description": "Workspaces with Microsoft Sentinel turned on.",
    }
    return params(f"{P}-params", [
        subscription_param(P),
        time_param(P, 7 * DAY_MS, [d * DAY_MS for d in (1, 3, 7, 14, 30, 90)],
                   "Applies to health, alerts, closed incidents and cost. Open incidents and table baselines use "
                   "fixed windows."),
        workspace,
        choice_param(P, "SilentHours", "Table is silent after",
                     [("6", "6 hours"), ("12", "12 hours"), ("24", "24 hours"), ("48", "48 hours")], "24",
                     "A table that has sent nothing for this long is flagged. Some tables are naturally quiet (alerts, "
                     "rarely used connectors), so read the list rather than the count."),
        choice_param(P, "TriageHours", "Triage due within",
                     [("1", "1 hour"), ("4", "4 hours"), ("8", "8 hours"), ("24", "24 hours")], "4",
                     "A medium or high incident still New after this long counts as not triaged."),
        {"id": gid(f"{P}-param-selectedTab"), "version": "KqlParameterItem/1.0", "name": "selectedTab", "type": 1,
         "value": "overview", "isHiddenWhenLocked": True},
    ])


def tabs():
    return {"type": 11, "content": {"version": "LinkItem/1.0", "style": "tabs", "links": [
        {"id": gid(f"{P}-tab-" + key), "cellValue": "selectedTab", "linkTarget": "parameter",
         "linkLabel": label, "subTarget": key, "style": "link"} for key, label in TABS
    ]}, "name": f"{P}-tabs"}


TILES = big_number_tiles("Signal", "State", "Value", "Detail")
FRESH_STATUS = status_fmt("Status", good=["Normal"], warn=["Dropped", "Spiked"], bad=["Silent"])
INCIDENT_LINK = {"columnMatch": "IncidentUrl", "formatter": 7, "formatOptions": {"linkTarget": "Url", "linkLabel": "Open"}}
CLASSIFICATION_LABELS = {"TruePositive": "True positive", "BenignPositive": "Benign positive",
                         "FalsePositive": "False positive"}


def overview_tab():
    tiles = []
    for key, days, q in LA_TILES:
        item = la(f"{P}-tile-{key}", "", q, vis="tiles", tiles=TILES, fixed_px=ONE_TILE)
        tiles.append(fixed_window(item, days) if days else item)
    return group(f"{P}-tab-overview", [
        *tiles,
        la(f"{P}-tile-activity", "", ACTIVITY_TILE, vis="tiles", tiles=TILES, fixed_px=ONE_TILE),
        arg(f"{P}-tile-workspace", "", WORKSPACE_TILE, vis="tiles", tiles=TILES, fixed_px=ONE_TILE),
        text(f"{P}-tile-note", TILE_NOTE, "info"),
        la(f"{P}-ingestion", "Ingestion by table, top 10 (GB)", INGESTION_Q, vis="timechart", width=50),
        fixed_window(la(f"{P}-created", "Incidents created per day by severity", CREATED_Q, vis="barchart", width=50),
                     90),
        la(f"{P}-failing", "Connectors, rules and automation failing (latest state)", HEALTH + """
| summarize arg_max(TimeGenerated, Status, Description) by Type = SentinelResourceType, Resource = SentinelResourceName
| where Status !~ 'Success'
| project Type, Resource, Status, Since = TimeGenerated, Detail = substring(Description, 0, 300)
| order by Type asc, Resource asc
""", formatters=[HEALTH_STATUS],
           no_data="Nothing is failing (or health monitoring is not turned on: Sentinel → Settings → Auditing and "
                   "health monitoring)."),
    ], tab="overview")


def data_tab():
    return group(f"{P}-tab-data", [
        fixed_window(la(f"{P}-freshness", "Tables: last record and volume (last 24 hours against the 7 days before)",
                        FRESHNESS_Q, formatters=[FRESH_STATUS],
                        labels={"LastSeen": "Last data", "HoursSinceData": "Hours since data",
                                "GBLast24h": "GB last 24 h", "GBDailyAvg": "GB per day (7-day average)"}), 8),
        text(f"{P}-freshness-note", "Read from the `Usage` table, which records every table's volume each hour. A "
             "table that sent nothing for the whole 8 days is not listed: check the data connector itself.", "info"),
        la(f"{P}-connector-health", "Data connector health", CONNECTOR_HEALTH_Q, formatters=[HEALTH_STATUS],
           labels={"LastReport": "Last report"},
           no_data="No data connector health records. Only some connectors report health, and only once health "
                   "monitoring is turned on."),
        arm(f"{P}-connectors", "Data connectors configured", f"{SI}/dataConnectors", SI_API,
            [("Connector", "$.name", None), ("Kind", "$.kind", None)], width=40,
            no_data="No data connectors returned. Connectors installed from the Content hub as solutions may not "
                    "be listed here."),
        la(f"{P}-activity-coverage", "Subscriptions sending the activity log to this workspace", ACTIVITY_COVERAGE_Q,
           width=60, formatters=[status_fmt("Status", good=["Sending"], warn=["Stale"], bad=["Not sending"]),
                                 status_fmt("State", good=["Enabled"], neutral=["Disabled", "Warned"])],
           labels={"LastRecord": "Last record"}),
        la(f"{P}-ingestion-tables", "Ingestion by table over time, top 10 (GB)", INGESTION_Q, vis="timechart"),
    ], tab="data")


def detections_tab():
    rule_cols = [("Rule", "$.properties.displayName", None), ("Kind", "$.kind", None),
                 ("Enabled", "$.properties.enabled", None), ("Severity", "$.properties.severity", None),
                 ("Frequency", "$.properties.queryFrequency", None),
                 ("Last modified", "$.properties.lastModifiedUtc", "datetime"),
                 ("Template version", "$.properties.templateVersion", None)]
    return group(f"{P}-tab-detections", [
        la(f"{P}-rule-health", "Analytics rules with failed runs", RULE_HEALTH_Q, formatters=[HEALTH_STATUS],
           labels={"LastIssueTime": "Last failure", "LastIssue": "Last failure detail", "LastRun": "Last run"},
           no_data="No analytics rule failures (or health monitoring is not turned on)."),
        text(f"{P}-rule-health-note", "Sentinel turns off a scheduled rule that keeps failing (for example because a "
             "table or column it reads no longer exists). Such a rule shows here before it is turned off, and as "
             "*Enabled: false* below after.", "info"),
        arm(f"{P}-rules", "Analytics rules", f"{SI}/alertRules", SI_API, rule_cols,
            formatters=[status_fmt("Enabled", good=["true", "True"], warn=["false", "False"]), SEVERITY],
            no_data="No analytics rules."),
        fixed_window(la(f"{P}-tuning", "Rules to tune: closed incidents that were not true positives", TUNING_Q,
           width=50, formatters=[{"columnMatch": "NotTruePct", "formatter": 18, "formatOptions": {
               "thresholdsOptions": "icons", "thresholdsGrid": [
                   {"operator": ">=", "thresholdValue": "80", "representation": "4", "text": "{0}{1}"},
                   {"operator": ">=", "thresholdValue": "50", "representation": "2", "text": "{0}{1}"},
                   {"operator": "Default", "thresholdValue": None, "representation": "success", "text": "{0}{1}"}]}}],
           labels={**CLASSIFICATION_LABELS, "NotTruePct": "Not true positive %"},
           no_data="No rule had three or more incidents closed in the time range."), 90),
        la(f"{P}-noisy", "Noisiest rules (alerts in the time range)", NOISY_RULES_Q, width=50,
           formatters=[SEVERITY], labels={"LastAlert": "Last alert"}, no_data="No alerts from analytics rules."),
        la(f"{P}-quiet", "Rules that ran but raised no alert (time range)", QUIET_RULES_Q,
           labels={"LastRun": "Last run"},
           no_data="Every rule that ran raised at least one alert (or health monitoring is not turned on)."),
        text(f"{P}-quiet-note", "A quiet rule is often fine. It is worth a look when the table it reads has gone "
             "silent (Data collection tab), or after the source changed its schema.", "info"),
        la(f"{P}-audit", "Changes to rules, connectors and settings (SentinelAudit)", AUDIT_Q,
           labels={"CallerIp": "Caller IP"},
           no_data="No changes recorded (or auditing is not turned on: Sentinel → Settings → Auditing and health "
                   "monitoring)."),
    ], tab="detections")


def incidents_tab():
    return group(f"{P}-tab-incidents", [
        fixed_window(la(f"{P}-backlog", "Open incidents by severity and age", BACKLOG_Q, formatters=[SEVERITY],
                        labels={"UnderADay": "Under a day", "OneToSevenDays": "1–7 days",
                                "SevenToThirtyDays": "7–30 days", "OverThirtyDays": "Over 30 days"},
                        no_data="No open incidents."), 90),
        fixed_window(la(f"{P}-untriaged", "Still New after {TriageHours} hours", UNTRIAGED_Q,
                        formatters=[SEVERITY, status_fmt("Owner", warn=["Unassigned"]), INCIDENT_LINK],
                        labels={"AgeHours": "Age (hours)", "IncidentUrl": "Link"},
                        no_data="Every incident has been picked up within {TriageHours} hours."), 90),
        fixed_window(la(f"{P}-response", "Time to triage and close, incidents created in the time range", RESPONSE_Q,
                        formatters=[SEVERITY],
                        labels={"MedianMinutesToTriage": "Median minutes to triage",
                                "P90MinutesToTriage": "P90 minutes to triage",
                                "MedianHoursToClose": "Median hours to close", "P90HoursToClose": "P90 hours to close"}),
                     90),
        text(f"{P}-response-note", "*Triage* is the time from creation to the first change anyone made (assigning, "
             "changing status, commenting). Incidents closed by an automation rule count as triaged at once.", "info"),
        fixed_window(la(f"{P}-owners", "Workload by owner", OWNERS_Q, width=50,
                        labels={"OpenHigh": "Open high", "ClosedInRange": "Closed in time range",
                                "MedianHoursToClose": "Median hours to close"}), 90),
        fixed_window(la(f"{P}-sources", "Closed incidents by source and classification", SOURCES_Q, width=50,
                        labels={**CLASSIFICATION_LABELS, "TruePositivePct": "True positive %"},
                        no_data="No incidents closed in the time range."), 90),
    ], tab="incidents")


def automation_tab():
    playbooks = resource_param("Playbooks", "Playbooks", Q_PLAYBOOKS, first=10)
    playbooks["id"] = gid(f"{P}-param-Playbooks")
    return group(f"{P}-tab-automation", [
        arm(f"{P}-automation-rules", "Automation rules", f"{SI}/automationRules", SI_API, [
            ("Rule", "$.properties.displayName", None), ("Order", "$.properties.order", None),
            ("Enabled", "$.properties.triggeringLogic.isEnabled", None),
            ("Triggers on", "$.properties.triggeringLogic.triggersOn", None),
            ("When", "$.properties.triggeringLogic.triggersWhen", None),
            ("Expires", "$.properties.triggeringLogic.expirationTimeUtc", "datetime"),
            ("Last modified", "$.properties.lastModifiedTimeUtc", "datetime")],
            formatters=[status_fmt("Enabled", good=["true", "True"], warn=["false", "False"])],
            no_data="No automation rules."),
        la(f"{P}-automation-health", "Automation rule and playbook runs", AUTOMATION_HEALTH_Q,
           formatters=[{"columnMatch": "Failures", "formatter": 18, "formatOptions": {
               "thresholdsOptions": "icons", "thresholdsGrid": [
                   {"operator": ">", "thresholdValue": "0", "representation": "4", "text": "{0}{1}"},
                   {"operator": "Default", "thresholdValue": None, "representation": "success", "text": "{0}{1}"}]}}],
           labels={"LastIssueTime": "Last failure", "LastIssue": "Last failure detail", "LastRun": "Last run"},
           no_data="No automation runs recorded (or health monitoring is not turned on)."),
        arg(f"{P}-playbooks", "Playbooks (Logic Apps that use the Sentinel connector)", PLAYBOOKS_Q,
            formatters=[resource_link(), status_fmt("State", good=["Enabled"], warn=["Disabled"])],
            labels={"id": "Playbook", "Identity": "Managed identity"},
            no_data="No Logic Apps using the Sentinel connector in the selected subscriptions."),
        params(f"{P}-playbook-params", [playbooks]),
        metrics(f"{P}-playbook-runs", "Playbook runs failed", "microsoft.logic/workflows", "Playbooks",
                [m("microsoft.logic/workflows", "RunsFailed", SUM)], width=50),
        metrics(f"{P}-playbook-throttled", "Playbook actions throttled", "microsoft.logic/workflows", "Playbooks",
                [m("microsoft.logic/workflows", "ActionThrottledEvents", SUM)], width=50),
        text(f"{P}-playbook-note", "A playbook that uses an API connection rather than a managed identity stops "
             "working when the account that authorised the connection leaves or changes its password.", "info"),
    ], tab="automation")


def cost_tab():
    return group(f"{P}-tab-cost", [
        arg(f"{P}-workspace", "Workspace pricing and access", WORKSPACE_Q,
            formatters=[resource_link(),
                        status_fmt("Ingestion", good=["RespectQuota"], warn=["ApproachingQuota"],
                                   bad=["OverQuota", "ForceOff", "SubscriptionSuspended"])],
            labels={"id": "Workspace", "CommitmentGBPerDay": "Commitment tier (GB/day)", "RetentionDays": "Retention (days)",
                    "DailyCapGB": "Daily cap (GB, -1 = none)", "PublicIngestion": "Public ingestion",
                    "PublicQuery": "Public query", "ResourcePermissions": "Resource-context access only"}),
        la(f"{P}-daily-avg", "Billable ingestion per day (time range)", DAILY_AVG_Q, width=40,
           labels={"AvgGBPerDay": "Average GB/day", "PeakGBPerDay": "Peak GB/day", "LowestGBPerDay": "Lowest GB/day"}),
        text(f"{P}-tier-note", "Compare the average with the commitment tier above. Ingestion well under the tier is "
             "paid for anyway; ingestion steadily over the next tier up is cheaper on that tier. Sentinel and Log "
             "Analytics share one commitment tier under simplified pricing.", "info"),
        la(f"{P}-billable-daily", "Billable and free ingestion per day (GB)", BILLABLE_DAILY_Q, vis="barchart"),
        la(f"{P}-billable-tables", "Billable ingestion by table", BILLABLE_TABLES_Q, width=50,
           labels={"GBPerDay": "GB per day"}),
        arm(f"{P}-tables", "Table plans and retention", "{Workspace}/tables", "2022-10-01", [
            ("Table", "$.name", None), ("Plan", "$.properties.plan", None),
            ("Retention (days)", "$.properties.retentionInDays", None),
            ("Total retention (days)", "$.properties.totalRetentionInDays", None),
            ("Archive (days)", "$.properties.archiveRetentionInDays", None)],
            width=50, formatters=[status_fmt("Plan", good=["Analytics"], neutral=["Basic", "Auxiliary"])]),
        text(f"{P}-plans-note", "Analytics rules can only read tables on the *Analytics* plan. High-volume data you "
             "keep for investigation rather than detection (firewall flows, verbose diagnostics) is cheaper on "
             "*Basic* or *Auxiliary*. The **Log Analytics: cost and noise** workbook shows which tables are queried "
             "and by whom.", "info"),
    ], tab="cost")


def purview_tab():
    return group(f"{P}-tab-purview", [
        text(f"{P}-purview-note", "Purview reaches Sentinel in several ways: DLP and Insider Risk alerts through the "
             "Defender XDR connector (as `SecurityAlert`, with alert detail in `AlertInfo` and `AlertEvidence`), "
             "sensitivity label activity through the *Microsoft Purview Information Protection* connector "
             "(`MicrosoftPurviewInformationProtection`), data map classifications through the *Microsoft Purview* "
             "connector (`PurviewDataSensitivityLogs`) and Microsoft 365 audit through *Office 365* "
             "(`OfficeActivity`). A table that is missing below is not connected.", "info"),
        fixed_window(la(f"{P}-purview-freshness", "Purview-related tables", PURVIEW_FRESHNESS_Q,
                        formatters=[FRESH_STATUS],
                        labels={"LastSeen": "Last data", "HoursSinceData": "Hours since data",
                                "GBLast24h": "GB last 24 h", "GBDailyAvg": "GB per day (7-day average)"},
                        no_data="None of the Purview-related tables has received data in the last 8 days."), 8),
        la(f"{P}-purview-trend", "DLP, Insider Risk and Information Protection alerts", PURVIEW_TREND_Q,
           vis="timechart", width=50, no_data="No Purview alerts in the time range."),
        la(f"{P}-purview-top", "Most frequent Purview alerts", PURVIEW_TOP_Q, width=50, formatters=[SEVERITY],
           labels={"LastSeen": "Last seen"}, no_data="No Purview alerts in the time range."),
        la(f"{P}-mip-operations", "Sensitivity label activity by workload", MIP_OPERATIONS_Q, width=50,
           no_data="No Information Protection events (or the connector is not configured)."),
        la(f"{P}-mip-removals", "Labels removed or downgraded, by user", MIP_REMOVALS_Q, width=50,
           labels={"LastSeen": "Last seen"}, no_data="No labels removed or downgraded in the time range."),
    ], tab="purview")


def workbook():
    return notebook([
        text(f"{P}-header", "# Microsoft Sentinel operations\n"
             "For the team that runs Sentinel: is it collecting what it should, are detections and automation "
             "running, is the incident queue being worked, what does it cost, and is Purview data arriving?"),
        global_params(),
        tabs(),
        overview_tab(),
        data_tab(),
        detections_tab(),
        incidents_tab(),
        automation_tab(),
        cost_tab(),
        purview_tab(),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
