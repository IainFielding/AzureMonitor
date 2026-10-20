"""Generates the change investigation workbook.

Run:  python src/build_changes.py
Out:  workbook/changes.workbook.json

Answers "what changed?" for a resource group, a resource or the whole estate over a time window: every resource
change with each property before and after, who made it and with what tool, alongside the health transitions,
alerts, Service Health events, role assignments and policy assignments over the same window. Resource Graph keeps
14 days of changes; with a workspace selected the activity log adds failed operations, deployments, role
assignment removals and anything older. Built from the helpers in build_workbook.py so the workbooks look alike.
"""

import pathlib

from build_workbook import (DAY_MS, WORKSPACE_UNSET, arg, big_number_tiles, choice_param, export_row,
                            free_text_param, gid, group, health_fmt, la, notebook, params, resource_link, status_fmt,
                            subscription_param, text, time_param, workspace_param, write_workbook)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "changes.workbook.json"

P = "chg"
HOUR_MS = 3600000

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

# The scope boxes, as `where` clauses on a row's lower-case resource id (`id`) and resource group. Each box is
# optional; the resource box matches any part of the id, so a name, a type or a resource group path all work.
RG_FILTER = "| where array_length(dynamic([{ResourceGroups}])) == 0 or set_has_element(dynamic([{ResourceGroups}]), ResourceGroup)"
RESOURCE_FILTER = r"| where isempty(trim(@'\s+', @'{Resource}')) or id contains tolower(trim(@'\s+', @'{Resource}'))"
CALLER_FILTER = r"| where isempty(trim(@'\s+', @'{ChangedBy}')) or COLUMN contains trim(@'\s+', @'{ChangedBy}')"
SCOPE = RG_FILTER + "\n" + RESOURCE_FILTER

# Resource changes and resource group / subscription changes, in one shape. A change is a user change when any of
# its properties is (system changes are the platform's own bookkeeping: etags, provisioning state, timestamps).
# Creates and deletes have no property list, so they always count.
CHANGES = r"""
resourcechanges
| union (resourcecontainerchanges)
| extend Time = todatetime(properties.changeAttributes.timestamp)
| where Time >= todatetime('{TimeRange:startISO}')
| extend id = tolower(tostring(properties.targetResourceId)), Changes = properties.changes,
    ChangeType = tostring(properties.changeType), ChangedBy = tostring(properties.changeAttributes.changedBy),
    ByType = tostring(properties.changeAttributes.changedByType), Client = tostring(properties.changeAttributes.clientType),
    Operation = tostring(properties.changeAttributes.operation)
| extend ResourceGroup = tostring(split(id, '/')[4]),
    Type = iff(array_length(split(id, '/')) > 8, strcat(tostring(split(id, '/')[6]), '/', tostring(split(id, '/')[7])),
        iff(array_length(split(id, '/')) > 4, 'resource group', 'subscription')),
    UserChange = ChangeType != 'Update' or tostring(Changes) contains '"changeCategory":"User"'
SCOPE
CALLER
| where '{Kinds}' == 'all' or UserChange""".replace("SCOPE", SCOPE).replace("CALLER", CALLER_FILTER.replace("COLUMN", "ChangedBy"))

# ---------------------------------------------------------------------------
# Resource Graph panels
# ---------------------------------------------------------------------------

TILES_Q = CHANGES + """
| summarize Changes = count(), Resources = dcount(id), Created = countif(ChangeType == 'Create'),
    Deleted = countif(ChangeType == 'Delete'), People = dcount(ChangedBy)
| extend rows = pack_array(
    pack('Signal', 'Changes', 'Value', Changes, 'Detail', strcat('to ', Resources, ' resources')),
    pack('Signal', 'Created', 'Value', Created, 'Detail', 'resources'),
    pack('Signal', 'Deleted', 'Value', Deleted, 'Detail', 'resources'),
    pack('Signal', 'Changed by', 'Value', People, 'Detail', 'people and identities'))
| mv-expand r = rows
| project Signal = tostring(r.Signal), Value = toint(r.Value), Detail = tostring(r.Detail),
    State = case(tostring(r.Signal) == 'Deleted' and toint(r.Value) > 0, 'Degraded', 'Unknown')
"""

TIMELINE_Q = CHANGES + """
| summarize Changes = count() by bin(Time, {TimeRange:grain}), ChangeType
"""

WHO_Q = CHANGES + """
| summarize Changes = count(), Resources = dcount(id), Created = countif(ChangeType == 'Create'),
    Deleted = countif(ChangeType == 'Delete'), Tools = strcat_array(make_set(Client, 5), ', '),
    First = min(Time), Last = max(Time) by ChangedBy, ByType
| order by Changes desc
| take 100
"""

MOST_CHANGED_Q = CHANGES + """
| summarize Changes = count(), People = strcat_array(make_set(ChangedBy, 5), ', '), Last = max(Time),
    Kinds = strcat_array(make_set(ChangeType), ', ') by id, Type
| order by Changes desc
| take 100
"""

# One row per changed property, with its value before and after. A create or delete has no property list and
# shows as a single row for the whole resource.
DETAIL_Q = CHANGES + """
| mv-expand c = iff(array_length(bag_keys(Changes)) > 0, Changes, pack('(whole resource)', pack('changeCategory', 'User')))
| extend Property = tostring(bag_keys(c)[0])
| extend v = c[Property]
| extend Category = tostring(v.changeCategory)
| where '{Kinds}' == 'all' or Category != 'System'
| project Time, id, ChangeType, Property, Before = tostring(v.previousValue), After = tostring(v.newValue),
    ChangedBy, Client, Operation, Category
| order by Time desc
| take 1000
"""

# Resource Health transitions in the same scope. The change record targets
# <resource>/providers/Microsoft.ResourceHealth/..., so the resource is read back out of the id.
HEALTH_Q = """
healthresourcechanges
| where tostring(properties.targetResourceType) =~ 'microsoft.resourcehealth/availabilitystatuses'
| extend Time = todatetime(properties.changeAttributes.timestamp)
| where Time >= todatetime('{TimeRange:startISO}')
| extend state = properties.changes['properties.availabilityState']
| where isnotempty(tostring(state.newValue))
| extend id = tostring(split(tolower(tostring(properties.targetResourceId)), '/providers/microsoft.resourcehealth/')[0])
| extend ResourceGroup = tostring(split(id, '/')[4])
SCOPE
| project Time, id, Previous = tostring(state.previousValue), Health = tostring(state.newValue)
| order by Time desc
| take 500
""".replace("SCOPE", SCOPE)

ALERTS_Q = """
alertsmanagementresources
| where type =~ 'microsoft.alertsmanagement/alerts'
| extend e = properties.essentials
| extend Fired = todatetime(e.startDateTime)
| where Fired >= todatetime('{TimeRange:startISO}')
| extend id = tolower(tostring(e.targetResource)), ResourceGroup = tolower(tostring(e.targetResourceGroup))
SCOPE
| project Fired, Severity = tostring(e.severity), Alert = name, id, Condition = tostring(e.monitorCondition),
    State = tostring(e.alertState), Signal = tostring(e.signalType), Resolved = todatetime(e.monitorConditionResolvedDateTime),
    Rule = tostring(e.alertRule)
| order by Fired desc
| take 500
""".replace("SCOPE", SCOPE)

# Service Health events in effect during the window. These are per subscription, so the scope boxes do not apply.
SERVICE_HEALTH_Q = """
servicehealthresources
| where type =~ 'microsoft.resourcehealth/events'
| extend ImpactStart = todatetime(tolong(properties.ImpactStartTime)), LastUpdate = todatetime(tolong(properties.LastUpdateTime)),
    ImpactEnd = todatetime(tolong(properties.ImpactMitigationTime))
| where LastUpdate >= todatetime('{TimeRange:startISO}') or ImpactStart >= todatetime('{TimeRange:startISO}')
| project Title = tostring(properties.Title), EventType = tostring(properties.EventType), Status = tostring(properties.Status),
    Level = tostring(properties.Level), ImpactStart, ImpactEnd, LastUpdate, TrackingId = tostring(properties.TrackingId),
    SubscriptionId = subscriptionId
| summarize Subscriptions = dcount(SubscriptionId), ImpactStart = min(ImpactStart), ImpactEnd = max(ImpactEnd),
    LastUpdate = max(LastUpdate) by Title, EventType, Status, Level, TrackingId
| order by ImpactStart desc
"""

# Role assignments created or updated in the window. Removals leave nothing in Resource Graph: they are in the
# activity log below.
ROLES_Q = r"""
authorizationresources
| where type =~ 'microsoft.authorization/roleassignments'
| extend Created = todatetime(properties.createdOn), Updated = todatetime(properties.updatedOn)
| where Created >= todatetime('{TimeRange:startISO}') or Updated >= todatetime('{TimeRange:startISO}')
| extend id = tolower(tostring(properties.scope)), roleId = tolower(tostring(split(tostring(properties.roleDefinitionId), '/')[-1]))
| extend ResourceGroup = tostring(split(id, '/')[4])
SCOPE
| join kind=leftouter (
    authorizationresources
    | where type =~ 'microsoft.authorization/roledefinitions'
    | project roleId = tolower(name), Role = tostring(properties.roleName)
  ) on roleId
| project Created, Updated, Role, Scope = id, PrincipalType = tostring(properties.principalType),
    PrincipalId = tostring(properties.principalId), CreatedBy = tostring(properties.createdBy)
| order by Created desc
""".replace("SCOPE", SCOPE)

POLICY_Q = """
policyresources
| where type in~ ('microsoft.authorization/policyassignments', 'microsoft.authorization/policyexemptions')
| extend Created = todatetime(properties.metadata.createdOn), Updated = todatetime(properties.metadata.updatedOn)
| where Created >= todatetime('{TimeRange:startISO}') or Updated >= todatetime('{TimeRange:startISO}')
| project Updated = coalesce(Updated, Created), Created, Kind = iff(type endswith 'exemptions', 'Exemption', 'Assignment'),
    Name = coalesce(tostring(properties.displayName), name), Scope = tostring(split(tolower(id), '/providers/microsoft.authorization/')[0]),
    Enforcement = tostring(properties.enforcementMode), By = coalesce(tostring(properties.metadata.updatedBy), tostring(properties.metadata.createdBy))
| order by Updated desc
"""

# ---------------------------------------------------------------------------
# Activity log panels (Log Analytics)
# ---------------------------------------------------------------------------

# Each operation logs Started, Accepted and Succeeded or Failed under one correlation id; keep the last status.
# Reads are not logged, so what is left is writes, deletes and actions.
ACTIVITY = r"""
AzureActivity
| where TimeGenerated {TimeRange}
| extend id = tolower(_ResourceId), ResourceGroup = tolower(ResourceGroup)
SCOPE
CALLER
""".replace("SCOPE", SCOPE).replace("CALLER", CALLER_FILTER.replace("COLUMN", "Caller"))

OPERATIONS = ACTIVITY + """| where CategoryValue =~ 'Administrative'
| summarize arg_max(TimeGenerated, ActivityStatusValue, Properties_d), Started = min(TimeGenerated)
    by CorrelationId, OperationNameValue, id, Caller
| extend Status = ActivityStatusValue, Error = substring(tostring(Properties_d.statusMessage), 0, 400)
"""

ACTIVITY_TIMELINE_Q = ACTIVITY + """| summarize Events = count() by bin(TimeGenerated, {TimeRange:grain}), CategoryValue
"""

OPERATIONS_Q = OPERATIONS + """| where '{Kinds}' == 'all' or not(OperationNameValue has_any ('listKeys', 'MICROSOFT.RESOURCEHEALTH', 'getAccessToken'))
| project Time = TimeGenerated, Status, Operation = OperationNameValue, id, Caller, Error, CorrelationId
| order by Time desc
| take 500
"""

FAILED_Q = OPERATIONS + """| where Status in~ ('Failure', 'Failed')
| summarize Failures = count(), LastSeen = max(TimeGenerated), Error = take_any(Error) by Operation = OperationNameValue, id, Caller
| order by LastSeen desc
| take 200
"""

DEPLOYMENTS_Q = OPERATIONS + """| where OperationNameValue =~ 'MICROSOFT.RESOURCES/DEPLOYMENTS/WRITE'
| project Started, Finished = TimeGenerated, Minutes = round((TimeGenerated - Started) / 1m, 1), Status,
    Deployment = tostring(split(id, '/')[-1]), Scope = tostring(split(id, '/providers/microsoft.resources/deployments/')[0]),
    Caller, Error, CorrelationId
| order by Started desc
| take 200
"""

# Role assignment writes and deletes. The request body names the principal and role; the common built-in roles
# are named, the rest show their id.
RBAC_Q = ACTIVITY + r"""| where OperationNameValue in~ ('MICROSOFT.AUTHORIZATION/ROLEASSIGNMENTS/WRITE', 'MICROSOFT.AUTHORIZATION/ROLEASSIGNMENTS/DELETE')
| summarize arg_max(TimeGenerated, ActivityStatusValue, Properties_d) by CorrelationId, OperationNameValue, id, Caller
| extend body = strcat(tostring(Properties_d.requestbody), tostring(Properties_d.responseBody))
| extend roleId = extract(@'roleDefinitions/([0-9a-fA-F-]{36})', 1, body), Principal = extract(@'"principalId\\?"\s*:\s*\\?"([0-9a-fA-F-]{36})', 1, body)
| project Time = TimeGenerated, Change = iff(OperationNameValue endswith 'DELETE', 'Removed', 'Added'), Status = ActivityStatusValue,
    Role = case(roleId =~ '8e3af657-a8ff-443c-a75c-2fe8c4bcb635', 'Owner', roleId =~ 'b24988ac-6180-42a0-ab88-20f7382dd24c', 'Contributor',
        roleId =~ 'acdd72a7-3385-48ef-bd42-f6fba25ec5c3', 'Reader', roleId =~ '18d7d88d-d35e-4fb5-a5c3-7773c20a72d9', 'User Access Administrator',
        roleId =~ 'f58310d9-a9f6-439a-9e8d-f62e7b41a168', 'Role Based Access Control Administrator', roleId),
    Principal, Scope = tostring(split(id, '/providers/microsoft.authorization/roleassignments/')[0]), Caller
| order by Time desc
| take 200
"""

ACTIVITY_STATUS = status_fmt("Status", good=["Success", "Succeeded"], warn=["Accept", "Accepted", "Start", "Started"],
                             bad=["Failure", "Failed"])

HOW_TO = """\
Narrow it down with any of the boxes (all optional): resource groups, part of a resource name or id, and who
made the change (a user's sign-in name, or a service principal's application id). *Show* hides the platform's
own changes (etags, provisioning state, timestamps) unless set to *All changes*.

Resource Graph keeps **14 days** of changes. Select a workspace that receives the subscriptions' activity log
(`AzureActivity`) for anything older, and for failed operations, deployments and role assignment removals, which
Resource Graph does not record. *Changed by* in Resource Graph is the sign-in name or the application id; the
activity log's *Caller* is the same."""

DETAIL_NOTE = """\
Select a row in *Most changed resources* or paste part of a resource id into *Resource* to see just that
resource. *Client* is the tool the change came from: Azure Portal, Azure CLI, Azure PowerShell, ARM template
deployments (*Arm Template*), Terraform (*Terraform* or *Go SDK*) or another SDK; *Operation* is the Resource Manager
operation behind it. A change made by policy (*Microsoft.Authorization/policies/...* or a managed identity of a
policy assignment) is a remediation or a modify effect."""

# ---------------------------------------------------------------------------
# Workbook
# ---------------------------------------------------------------------------

RG_PICK_Q = """
resourcecontainers
| where type =~ 'microsoft.resources/subscriptions/resourcegroups'
| summarize by name = tolower(name)
| order by name asc
| project value = name, label = name
"""


def parameters():
    return params(f"{P}-params", [
        subscription_param(P),
        time_param(P, DAY_MS, (HOUR_MS, 4 * HOUR_MS, 12 * HOUR_MS, DAY_MS, 3 * DAY_MS, 7 * DAY_MS, 14 * DAY_MS, 30 * DAY_MS),
                   "Resource Graph keeps 14 days of changes. Longer ranges need the activity log in a workspace."),
        {
            "id": gid(f"{P}-param-ResourceGroups"), "version": "KqlParameterItem/1.0", "name": "ResourceGroups",
            "label": "Resource groups", "type": 2, "isRequired": False, "multiSelect": True, "quote": "'",
            "delimiter": ",", "query": RG_PICK_Q.strip(), "crossComponentResources": ["{Subscription}"], "value": [],
            "typeSettings": {"additionalResourceOptions": [], "showDefault": False}, "queryType": 1,
            "resourceType": "microsoft.resourcegraph/resources", "description": "Optional. Leave empty for all.",
        },
        free_text_param(P, "Resource", "Resource",
                        "Optional. Part of a resource name or id, e.g. a VM name or 'microsoft.network/routetables'."),
        free_text_param(P, "ChangedBy", "Changed by",
                        "Optional. Part of a sign-in name or application id."),
        choice_param(P, "Kinds", "Show", [("user", "Changes people and tools made"), ("all", "All changes")], "user",
                     "Platform changes (etags, provisioning state, timestamps) are hidden unless set to All changes."),
        workspace_param(P, "Optional. The workspace the activity log is sent to. Adds failed operations, deployments "
                           "and role assignment removals, and history beyond 14 days."),
    ])


def workbook():
    most_changed = export_row(arg(f"{P}-most", "Most changed resources", MOST_CHANGED_Q, width=50,
                       formatters=[resource_link()], labels={"id": "Resource", "Kinds": "Change types"},
                       no_data="No changes."), "id", "Resource")
    return notebook([
        text(f"{P}-header", "# What changed?\n"
             "Every change to the resources in scope over the time range: what changed, each property before and "
             "after, who changed it and with what tool, with the health transitions, alerts, Service Health events and "
             "access changes from the same window alongside."),
        parameters(),
        text(f"{P}-howto", HOW_TO, "info"),
        arg(f"{P}-tiles", "", TILES_Q, vis="tiles", tiles=big_number_tiles("Signal", "State", "Value", "Detail")),
        arg(f"{P}-timeline", "Changes over time", TIMELINE_Q, vis="barchart", no_data="No changes in the time range."),
        arg(f"{P}-who", "Who changed things", WHO_Q, width=50,
            labels={"ChangedBy": "Changed by", "ByType": "Type", "Tools": "Tools"}, no_data="No changes."),
        most_changed,
        arg(f"{P}-detail", "Changes, property by property (latest 1,000)", DETAIL_Q, formatters=[resource_link()],
            labels={"id": "Resource", "ChangeType": "Change", "ChangedBy": "Changed by"},
            no_data="No changes in the time range. Widen it (up to 14 days), or set Show to All changes."),
        text(f"{P}-detail-note", DETAIL_NOTE, "info"),
        text(f"{P}-context-h", "### Around the same time"),
        arg(f"{P}-health", "Health transitions", HEALTH_Q, width=50, formatters=[resource_link(), health_fmt(), health_fmt("Previous")],
            labels={"id": "Resource"}, no_data="No Resource Health transitions in scope."),
        arg(f"{P}-alerts", "Alerts fired", ALERTS_Q, width=50,
            formatters=[resource_link(), status_fmt("Condition", good=["Resolved"], bad=["Fired"]),
                        status_fmt("Severity", warn=["Sev2", "Sev3"], bad=["Sev0", "Sev1"], neutral=["Sev4"])],
            labels={"id": "Resource"}, no_data="No alerts fired in scope."),
        arg(f"{P}-servicehealth", "Service Health events (selected subscriptions)", SERVICE_HEALTH_Q,
            formatters=[status_fmt("Status", good=["Resolved"], warn=["Active"])],
            labels={"EventType": "Type", "ImpactStart": "Impact start", "ImpactEnd": "Mitigated", "LastUpdate": "Last update",
                    "TrackingId": "Tracking id"},
            no_data="No Service Health events in the time range."),
        arg(f"{P}-roles", "Role assignments created or updated", ROLES_Q, width=50,
            formatters=[status_fmt("Role", bad=["Owner", "User Access Administrator"])],
            labels={"PrincipalType": "Principal type", "PrincipalId": "Principal id", "CreatedBy": "Created by"},
            no_data="No role assignments created or updated in scope."),
        arg(f"{P}-policy", "Policy assignments and exemptions created or updated", POLICY_Q, width=50,
            formatters=[resource_link("Scope"), status_fmt("Enforcement", good=["Default"], warn=["DoNotEnforce"])],
            labels={"Kind": "Type", "By": "Changed by"},
            no_data="No policy assignments or exemptions changed in the time range."),
        text(f"{P}-activity-h", "### Activity log"),
        text(f"{P}-ws-hint", "Select a **Log Analytics workspace** that receives the activity log for failed operations, "
             "deployments, role assignment removals and history beyond 14 days.", "info", visible_when=WORKSPACE_UNSET),
        la(f"{P}-activity-timeline", "Activity log events by category", ACTIVITY_TIMELINE_Q, vis="barchart"),
        la(f"{P}-failed", "Failed operations", FAILED_Q, formatters=[resource_link()],
           labels={"id": "Resource", "LastSeen": "Last seen"}, no_data="No failed operations in scope."),
        la(f"{P}-deployments", "Deployments", DEPLOYMENTS_Q, formatters=[ACTIVITY_STATUS, resource_link("Scope")],
           labels={"Minutes": "Duration (min)", "CorrelationId": "Correlation id"},
           no_data="No deployments in scope."),
        la(f"{P}-rbac", "Role assignments added and removed", RBAC_Q, formatters=[ACTIVITY_STATUS, resource_link("Scope"),
                                                                                    status_fmt("Change", good=["Added"], warn=["Removed"])],
           no_data="No role assignment changes in scope."),
        group(f"{P}-ops", [
            la(f"{P}-operations", "Operations (latest 500, final status of each)", OPERATIONS_Q,
               formatters=[ACTIVITY_STATUS, resource_link()],
               labels={"id": "Resource", "CorrelationId": "Correlation id"}, no_data="No operations in scope."),
        ], load_button="Show every operation"),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
