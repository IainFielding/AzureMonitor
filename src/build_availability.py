"""Generates the monthly platform availability report.

Run:  python src/build_availability.py
Out:  workbook/availability-report.workbook.json

A one-page summary of a calendar month for a service review: the availability of each platform service against a
target, the Resource Health incidents behind it, the Azure Service Health incidents and maintenance that touched
the estate, and the trend over the last six months. Laid out with no tabs so the whole report prints.

Resource Graph keeps only 14 days of health changes, so the report reads Resource Health from the activity log
(AzureActivity, category ResourceHealth) in Log Analytics, which keeps as long as the workspace does. The list of
platform resources comes from Resource Graph through arg(""). Built from the helpers in build_workbook.py so the
workbooks look alike.
"""

import json
import pathlib

from build_workbook import (ONE_TILE, SERVICE_CASE, WORKSPACE_UNSET, big_number_tiles, choice_param, free_text_param,
                            gid, high_is_good, la, notebook, params, resource_link, status_fmt, subscription_param,
                            text, workspace_param, write_workbook)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "availability-report.workbook.json"

P = "avl"

# The platform types from the health workbook, without build agent scale sets: they are capacity, not a service
# anyone outside the team is promised.
REPORT_TYPES = ", ".join(f"'{t}'" for t in [
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
    "microsoft.operationalinsights/workspaces",
    "microsoft.recoveryservices/vaults",
    "microsoft.cdn/profiles",
    "microsoft.network/frontdoors",
    "microsoft.apimanagement/service",
    "microsoft.cognitiveservices/accounts",
    "microsoft.machinelearningservices/workspaces",
])

MONTH_NAMES = json.dumps(["January", "February", "March", "April", "May", "June", "July", "August", "September",
                          "October", "November", "December"]).replace('"', "'")

# The month picker: this month and the twelve before it, last month selected.
MONTH_QUERY = f"""range i from 0 to 12 step 1
| extend m = startofmonth(now(), -i)
| project value = format_datetime(m, 'yyyy-MM-dd'),
    label = strcat(dynamic({MONTH_NAMES})[getmonth(m) - 1], ' ', getyear(m), iff(i == 0, ' (so far)', '')),
    selected = i == 1"""

# ---------------------------------------------------------------------------
# Impaired periods
# ---------------------------------------------------------------------------

# Every query starts from this. Each Resource Health event in the activity log records the resource's new state,
# which holds until its next event, so a resource is impaired from an Unavailable (or, if chosen, Degraded) event
# to the next event that is not. The window runs from the start of the trend (five months before the report month)
# to the end of the report month, or now; events from 60 days before it give each resource its state when the
# window opens. A period that crosses into a new month is split at the boundary, so each month carries its own part.
# Only platform resources that still exist are counted, because the inventory comes from Resource Graph.
# Every join with the inventory carries hint.remote=local: otherwise Log Analytics may send the join to Resource
# Graph, which cannot run it. The inventory is not materialized: a materialized Resource Graph result comes back
# empty the second time it is read.
BASE = f"""
let monthStart = todatetime('{{Month}}');
let reportEnd = min_of(datetime_add('month', 1, monthStart), now());
let trendStart = datetime_add('month', -5, monthStart);
let downStates = iff('{{CountDegraded}}' == 'yes', dynamic(['Unavailable', 'Degraded']), dynamic(['Unavailable']));
let includeUser = '{{UserInitiated}}' == 'include';
let inventory = arg("").Resources
| where type in~ ({REPORT_TYPES})
| where type !~ 'microsoft.storage/storageaccounts' or name matches regex @'{{StoragePattern}}' or resourceGroup matches regex @'{{StoragePattern}}'
| where type !~ 'microsoft.cdn/profiles' or tostring(sku.name) contains 'AzureFrontDoor'
| where type !~ 'microsoft.cognitiveservices/accounts' or kind in~ ('AIServices', 'OpenAI')
| where type !~ 'microsoft.machinelearningservices/workspaces' or kind in~ ('Hub', 'Project')
| extend gatewayType = tostring(properties.gatewayType)
{SERVICE_CASE}
| project id = tolower(id), Service, Resource = name, ResourceGroup = resourceGroup;
let periods = materialize(AzureActivity
| where TimeGenerated between (datetime_add('day', -60, trendStart) .. reportEnd)
| where CategoryValue =~ 'ResourceHealth'
| extend props = column_ifexists('Properties_d', dynamic(null))
| project TimeGenerated, id = tolower(_ResourceId), Health = tostring(props.currentHealthStatus),
    Cause = tostring(props.cause), Title = tostring(props['title'])
| where isnotempty(Health)
| join kind=inner hint.remote=local inventory on id
| extend Down = Health in (downStates) and (includeUser or Cause !~ 'UserInitiated')
| sort by id asc, TimeGenerated asc
| extend Until = iff(next(id) == id, next(TimeGenerated), reportEnd),
    NewIncident = not(prev(id) == id and prev(Down))
| where Down
| extend S = max_of(TimeGenerated, trendStart), E = min_of(Until, reportEnd)
| where E > S
| mv-expand k = range(0, datetime_diff('month', E, S), 1) to typeof(int)
| extend M = datetime_add('month', k, startofmonth(S))
| extend S2 = max_of(S, M), E2 = min_of(E, datetime_add('month', 1, M))
| where E2 > S2
| extend Incident = NewIncident or S2 > S, Minutes = (E2 - S2) / 1m
| project id, Service, Resource, ResourceGroup, M, S = S2, E = E2, Minutes, Incident, Health, Cause, Title);
"""

# Minutes in each month and service when at least one of its resources was impaired. Overlapping periods are
# counted once: each period adds one at its start and takes one away at its end, and the service is impaired
# wherever the running total is above zero.
SERVICE_DOWN = """let serviceDown = materialize(periods
| mv-expand p = pack_array(pack('T', S, 'd', 1), pack('T', E, 'd', -1))
| project Service, M, T = todatetime(p.T), d = toint(p.d)
| sort by Service asc, M asc, T asc, d asc
| extend Running = row_cumsum(d, Service != prev(Service) or M != prev(M))
| extend NextT = iff(next(Service) == Service and next(M) == M, next(T), T)
| summarize DownMinutes = sum(iff(Running > 0, (NextT - T) / 1m, 0.0)) by Service, M);
"""

# One row per service for the report month.
BY_SERVICE = BASE + SERVICE_DOWN + """let windowMin = (reportEnd - monthStart) / 1m;
inventory
| summarize Resources = count() by Service
| join kind=leftouter hint.remote=local (serviceDown | where M == monthStart) on Service
| join kind=leftouter hint.remote=local (
    periods
    | where M == monthStart
    | summarize Incidents = countif(Incident), ResourcesAffected = dcount(id), ResourceMinutes = sum(Minutes),
        LongestMinutes = max(Minutes)
        by Service
  ) on Service
| extend DownMinutes = coalesce(DownMinutes, 0.0), Incidents = coalesce(Incidents, 0), ResourceMinutes = coalesce(ResourceMinutes, 0.0)
| extend AvailabilityPct = round(100.0 * (1 - DownMinutes / windowMin), 3),
    AverageResourcePct = round(100.0 * (1 - ResourceMinutes / (Resources * windowMin)), 3)
| extend Target = iff(AvailabilityPct >= {Target}, 'Met', 'Missed')
"""

BY_SERVICE_Q = BY_SERVICE + """| project Service, AvailabilityPct, Target, Resources, ResourcesAffected = coalesce(ResourcesAffected, 0), Incidents,
    DownMinutes = round(DownMinutes, 0), LongestMinutes = round(coalesce(LongestMinutes, 0.0), 0), AverageResourcePct
| order by AvailabilityPct asc, Service asc
"""

TILES_Q = BY_SERVICE + """| summarize arg_min(AvailabilityPct, Service), Services = count(), Met = countif(Target == 'Met'),
    Incidents = sum(Incidents), Affected = sum(coalesce(ResourcesAffected, 0)), Resources = sum(Resources)
| extend Lowest = AvailabilityPct, LowestService = Service
| extend rows = pack_array(
    pack('Signal', 'Services meeting {Target}%', 'Value', strcat(Met, ' of ', Services),
        'Detail', iff(Met == Services, 'every service met the target', strcat(Services - Met, ' missed')),
        'State', iff(Met == Services, 'Available', 'Unavailable')),
    pack('Signal', 'Lowest service availability', 'Value', strcat(Lowest, '%'), 'Detail', LowestService,
        'State', iff(Lowest >= {Target}, 'Available', 'Unavailable')),
    pack('Signal', 'Resource Health incidents', 'Value', tostring(Incidents),
        'Detail', strcat(Affected, ' of ', Resources, ' resources affected'),
        'State', iff(Incidents > 0, 'Degraded', 'Available')))
| mv-expand r = rows
| project Signal = tostring(r.Signal), Value = tostring(r.Value), Detail = tostring(r.Detail), State = tostring(r.State)
"""

TREND_Q = BASE + SERVICE_DOWN + """let months = range k from 0 to 5 step 1
| project M = datetime_add('month', -k, monthStart), Label = format_datetime(datetime_add('month', -k, monthStart), 'yyyy-MM');
inventory
| distinct Service
| extend j = 1
| join kind=inner hint.remote=local (months | extend j = 1) on j
| join kind=leftouter hint.remote=local serviceDown on Service, M
| extend windowMin = (min_of(datetime_add('month', 1, M), now()) - M) / 1m
| extend Pct = round(100.0 * (1 - coalesce(DownMinutes, 0.0) / windowMin), 3)
| project Service, Label, Pct
| evaluate pivot(Label, take_any(Pct), Service)
| order by Service asc
"""

DAILY_Q = BASE + """periods
| where M == monthStart
| mv-expand d = range(0, datetime_diff('day', E, S), 1) to typeof(int)
| extend Day = datetime_add('day', d, startofday(S))
| extend Minutes = (min_of(E, datetime_add('day', 1, Day)) - max_of(S, Day)) / 1m
| where Minutes > 0
| summarize ImpairedMinutes = round(sum(Minutes), 0) by Day, Service
| order by Day asc
"""

INCIDENTS_Q = BASE + """periods
| where M == monthStart
| sort by id asc, S asc
| extend IncidentNo = row_cumsum(toint(Incident))
| summarize Start = min(S), End = max(E), Minutes = round(sum(Minutes), 0), States = strcat_array(make_set(Health), ', '),
    Cause = take_any(Cause), Title = take_any(Title)
    by id, Service, IncidentNo
| extend Ongoing = iff(End >= reportEnd, iff(reportEnd < now(), 'Into next month', 'Still impaired'), '')
| project id, Service, Start, End, Minutes, Ongoing, States, Cause, Title
| order by Minutes desc
| take 200
"""

# Azure Service Health events posted to the subscriptions' activity logs, one row per tracking id across every
# subscription and update.
SERVICE_HEALTH = """
let monthStart = todatetime('{Month}');
let reportEnd = min_of(datetime_add('month', 1, monthStart), now());
AzureActivity
| where TimeGenerated between (monthStart .. reportEnd)
| where CategoryValue =~ 'ServiceHealth'
| extend props = column_ifexists('Properties_d', dynamic(null))
| extend TrackingId = tostring(props.trackingId), Kind = tostring(props.incidentType),
    Title = coalesce(tostring(props.defaultLanguageTitle), tostring(props['title'])),
    AzureService = tostring(props.service), Region = tostring(props.region), Stage = tostring(props.stage),
    ImpactStart = todatetime(tostring(props.impactStartTime)), Mitigated = todatetime(tostring(props.impactMitigationTime))
| where isnotempty(TrackingId)
| summarize arg_max(TimeGenerated, Title, Stage), Services = make_set(AzureService, 10),
    Regions = make_set_if(Region, isnotempty(Region), 20), Started = min(ImpactStart), Mitigated = max(Mitigated),
    Subscriptions = dcount(SubscriptionId), Updates = count(),
    Review = countif(Stage has_any ('RCA', 'PIR') or Title has_any ('PIR', 'Post Incident Review'))
    by TrackingId, Kind
| extend Hours = round((coalesce(Mitigated, reportEnd) - Started) / 1h, 1)
"""

SH_INCIDENTS_Q = SERVICE_HEALTH + """| where Kind in~ ('Incident', 'Security')
| project Started, Mitigated, Hours, Title, Services = strcat_array(Services, ', '), Regions = strcat_array(Regions, ', '),
    Subscriptions, Review = iff(Review > 0, 'Published', ''), Stage, TrackingId
| order by Started asc
"""

SH_MAINTENANCE_Q = SERVICE_HEALTH + """| where Kind =~ 'Maintenance'
| project Started, Mitigated, Hours, Title, Services = strcat_array(Services, ', '), Regions = strcat_array(Regions, ', '),
    Subscriptions, TrackingId
| order by Started asc
"""

SH_TILES_Q = SERVICE_HEALTH + """| summarize Incidents = countif(Kind in~ ('Incident', 'Security')),
    Hours = sumif(Hours, Kind in~ ('Incident', 'Security')), Maintenance = countif(Kind =~ 'Maintenance'),
    Advisories = countif(Kind !in~ ('Incident', 'Security', 'Maintenance'))
| extend rows = pack_array(
    pack('Signal', 'Azure Service Health incidents', 'Value', tostring(Incidents),
        'Detail', strcat(round(Hours, 1), ' hours of impact in total'), 'State', iff(Incidents > 0, 'Degraded', 'Available')),
    pack('Signal', 'Planned maintenance', 'Value', tostring(Maintenance), 'Detail', strcat(Advisories, ' advisories'),
        'State', 'Available'))
| mv-expand r = rows
| project Signal = tostring(r.Signal), Value = tostring(r.Value), Detail = tostring(r.Detail), State = tostring(r.State)
"""

METHOD_NOTE = """\
**How availability is worked out.** *Available %* is the share of the month during which **no** resource of the
service was impaired according to Azure Resource Health, so one firewall out of four going down counts against
Azure Firewall for as long as it was down. *Average resource %* spreads the same downtime across every resource of
the service, which is kinder to services with many resources (storage accounts, private DNS zones). Impaired means
*Unavailable*, plus *Degraded* when **Count as down** says so; *Unknown* is not counted as down. Periods Resource
Health marks as user-initiated (a gateway someone stopped, a planned resize) are left out unless **User-initiated**
says to count them. For the current month the window runs to now.

Resources deleted since the month ended are left out, because the list of platform resources comes from Resource
Graph. Resource Health is Microsoft's view of each resource; it does not see problems in your own configuration
(a wrong route, a firewall rule), so pair this report with the incidents your team handled."""


# ---------------------------------------------------------------------------
# Parameters and layout
# ---------------------------------------------------------------------------


def global_params():
    return params(f"{P}-params", [
        subscription_param(P),
        workspace_param(P, "The central workspace that receives every subscription's activity log.",
                        required=True, multi=False),
        {"id": gid(f"{P}-param-Month"), "version": "KqlParameterItem/1.0", "name": "Month", "label": "Month",
         "type": 2, "isRequired": True, "query": MONTH_QUERY, "crossComponentResources": ["{Workspace}"],
         "typeSettings": {"showDefault": False}, "queryType": 0,
         "resourceType": "microsoft.operationalinsights/workspaces",
         "description": "The calendar month to report on."},
        choice_param(P, "Target", "Target", [("99.5", "99.5%"), ("99.9", "99.9%"), ("99.95", "99.95%"),
                                             ("99.99", "99.99%")], "99.9",
                     "The availability each service is measured against."),
        choice_param(P, "CountDegraded", "Count as down", [("no", "Unavailable"), ("yes", "Unavailable or degraded")],
                     "no", "Whether a Degraded state counts against availability as well as Unavailable."),
        choice_param(P, "UserInitiated", "User-initiated", [("exclude", "Leave out"), ("include", "Count as down")],
                     "exclude", "Whether periods Resource Health marks as caused by your own action count as down."),
        {"id": gid(f"{P}-param-StoragePattern"), "version": "KqlParameterItem/1.0", "name": "StoragePattern",
         "label": "Storage account pattern", "type": 1, "isRequired": True, "value": "(?i)(fslogix|profile|avd|wvd)",
         "description": "Regex matched against storage account and resource group names: the storage accounts the "
                        "platform runs. Use '.' for all.", "isHiddenWhenLocked": True},
        free_text_param(P, "Commentary", "Commentary",
                        "Optional. A few lines for the review (what went wrong, what was done about it). Shown at the "
                        "top of the report."),
    ])


TILES = big_number_tiles("Signal", "State", "Value", "Detail")
LOCAL = {"time": False}


def workbook():
    return notebook([
        text(f"{P}-header", "# Platform availability: {Month:label}\n"
             "The availability of each shared platform service against a **{Target}%** target, the incidents behind "
             "it, and the Azure-wide incidents and maintenance that touched the estate."),
        global_params(),
        text(f"{P}-la-hint", "Select the **Log Analytics workspace** that receives the subscriptions' activity logs.",
             "warning", visible_when=WORKSPACE_UNSET),
        text(f"{P}-commentary", "### Commentary\n{Commentary}",
             visible_when={"parameterName": "Commentary", "comparison": "isNotEqualTo", "value": ""}),
        la(f"{P}-tiles", "", TILES_Q, vis="tiles", tiles=TILES, fixed_px=3 * ONE_TILE - 40, **LOCAL),
        la(f"{P}-sh-tiles", "", SH_TILES_Q, vis="tiles", tiles=TILES, fixed_px=2 * ONE_TILE - 30, **LOCAL),
        text(f"{P}-services-h", "## Availability by service"),
        la(f"{P}-services", "", BY_SERVICE_Q, formatters=[
            high_is_good("AvailabilityPct", 99.95, 99.9, digits=3), status_fmt("Target", good=["Met"], bad=["Missed"]),
            high_is_good("AverageResourcePct", 99.95, 99.9, digits=3),
        ], labels={"AvailabilityPct": "Available %", "ResourcesAffected": "Resources affected",
                   "DownMinutes": "Minutes impaired", "LongestMinutes": "Longest (minutes)",
                   "AverageResourcePct": "Average resource %"},
            no_data="No platform resources found.", **LOCAL),
        la(f"{P}-daily", "Minutes impaired per day, by service", DAILY_Q, vis="barchart",
           no_data="No platform resource was impaired this month.", **LOCAL),
        text(f"{P}-trend-h", "## Six-month trend"),
        la(f"{P}-trend", "Available % by month", TREND_Q,
           formatters=[high_is_good(r"^\d{4}-\d{2}$", 99.95, 99.9, digits=3)],
           no_data="No platform resources found.", **LOCAL),
        text(f"{P}-incidents-h", "## Resource Health incidents"),
        la(f"{P}-incidents", "", INCIDENTS_Q, formatters=[resource_link()],
           labels={"id": "Resource", "Minutes": "Minutes impaired", "States": "State"},
           no_data="No platform resource was impaired this month.", **LOCAL),
        text(f"{P}-sh-h", "## Azure Service Health"),
        la(f"{P}-sh-incidents", "Incidents affecting the subscriptions", SH_INCIDENTS_Q,
           formatters=[status_fmt("Review", good=["Published"])],
           labels={"Hours": "Hours of impact", "Review": "Incident review", "TrackingId": "Tracking ID"},
           no_data="No Azure Service Health incidents were posted to these subscriptions this month.", **LOCAL),
        la(f"{P}-sh-maintenance", "Planned maintenance", SH_MAINTENANCE_Q,
           labels={"Hours": "Hours", "TrackingId": "Tracking ID"},
           no_data="No planned maintenance was posted to these subscriptions this month.", **LOCAL),
        text(f"{P}-method", METHOD_NOTE, "info"),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
