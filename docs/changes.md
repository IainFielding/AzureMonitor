# What changed?

*Reference for [changes.workbook.json](../workbook/changes.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

Every change to the resources in scope over the time range: what changed, each property before and after, who changed it and with what tool, with the health transitions, alerts, Service Health events and access changes from the same window alongside.

It has 15 panels. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Time range | Resource Graph keeps 14 days of changes. Longer ranges need the activity log in a workspace. |
| Resource groups | Optional. Leave empty for all. |
| Resource | Optional. Part of a resource name or id, e.g. a VM name or 'microsoft.network/routetables'. |
| Changed by | Optional. Part of a sign-in name or application id. |
| Show | Platform changes (etags, provisioning state, timestamps) are hidden unless set to All changes. |
| Log Analytics workspace | Optional. The workspace the activity log is sent to. Adds failed operations, deployments and role assignment removals, and history beyond 14 days. |

## Panels

> Narrow it down with any of the boxes (all optional): resource groups, part of a resource name or id, and who
> made the change (a user's sign-in name, or a service principal's application id). *Show* hides the platform's
> own changes (etags, provisioning state, timestamps) unless set to *All changes*.
>
> Resource Graph keeps **14 days** of changes. Select a workspace that receives the subscriptions' activity log
> (`AzureActivity`) for anything older, and for failed operations, deployments and role assignment removals, which
> Resource Graph does not record. *Changed by* in Resource Graph is the sign-in name or the application id; the
> activity log's *Caller* is the same.

#### Tiles

*Tiles · Azure Resource Graph* · reads `resourcechanges`, `resourcecontainerchanges`

#### Changes over time

*Bar chart · Azure Resource Graph* · reads `resourcechanges`, `resourcecontainerchanges`

When there is nothing to show: *No changes in the time range.*

#### Who changed things

*Table · Azure Resource Graph* · reads `resourcechanges`, `resourcecontainerchanges`

When there is nothing to show: *No changes.*

#### Most changed resources

*Table · Azure Resource Graph* · reads `resourcechanges`, `resourcecontainerchanges`

When there is nothing to show: *No changes.*

#### Changes, property by property (latest 1,000)

*Table · Azure Resource Graph* · reads `resourcechanges`, `resourcecontainerchanges`

Columns: Time, Resource, Change, Property, Before, After, Changed by, Client, Operation, Category.

When there is nothing to show: *No changes in the time range. Widen it (up to 14 days), or set Show to All changes.*

> Select a row in *Most changed resources* or paste part of a resource id into *Resource* to see just that
> resource. *Client* is the tool the change came from: Azure Portal, Azure CLI, Azure PowerShell, ARM template
> deployments (*Arm Template*), Terraform (*Terraform* or *Go SDK*) or another SDK; *Operation* is the Resource Manager
> operation behind it. A change made by policy (*Microsoft.Authorization/policies/...* or a managed identity of a
> policy assignment) is a remediation or a modify effect.

### Around the same time

#### Health transitions

*Table · Azure Resource Graph* · reads `healthresourcechanges`

Columns: Time, Resource, Previous, Health.

When there is nothing to show: *No Resource Health transitions in scope.*

#### Alerts fired

*Table · Azure Resource Graph* · reads `alertsmanagementresources`

Columns: Fired, Severity, Alert, Resource, Condition, State, Signal, Resolved, Rule.

When there is nothing to show: *No alerts fired in scope.*

#### Service Health events (selected subscriptions)

*Table · Azure Resource Graph* · reads `servicehealthresources`

Columns: Title, Type, Status, Level, Impact start, Mitigated, Last update, Tracking id, Subscription Id.

When there is nothing to show: *No Service Health events in the time range.*

#### Role assignments created or updated

*Table · Azure Resource Graph* · reads `authorizationresources`

Columns: Created, Updated, Role, Scope, Principal type, Principal id, Created by.

When there is nothing to show: *No role assignments created or updated in scope.*

#### Policy assignments and exemptions created or updated

*Table · Azure Resource Graph* · reads `policyresources`

Columns: Updated, Created, Type, Name, Scope, Enforcement, Changed by.

When there is nothing to show: *No policy assignments or exemptions changed in the time range.*

### Activity log

> Select a **Log Analytics workspace** that receives the activity log for failed operations, deployments, role assignment removals and history beyond 14 days.

#### Activity log events by category

*Bar chart · Log Analytics* · reads `AzureActivity`

#### Failed operations

*Table · Log Analytics* · reads `AzureActivity`

When there is nothing to show: *No failed operations in scope.*

#### Deployments

*Table · Log Analytics* · reads `AzureActivity`

Columns: Started, Finished, Duration (min), Status, Deployment, Scope, Caller, Error, Correlation id.

When there is nothing to show: *No deployments in scope.*

#### Role assignments added and removed

*Table · Log Analytics* · reads `AzureActivity`

Columns: Time, Change, Status, Role, Principal, Scope, Caller.

When there is nothing to show: *No role assignment changes in scope.*

### Show every operation (loads when asked)

#### Operations (latest 500, final status of each)

*Table · Log Analytics* · reads `AzureActivity`

Columns: Time, Status, Operation, Resource, Caller, Error, Correlation id.

When there is nothing to show: *No operations in scope.*
