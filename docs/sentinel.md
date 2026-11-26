# Microsoft Sentinel operations

*Reference for [sentinel.workbook.json](../workbook/sentinel.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

For the team that runs Sentinel: is it collecting what it should, are detections and automation running, is the incident queue being worked, what does it cost, and is Purview data arriving?

It has 40 panels across 7 tabs. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Time range | Applies to health, alerts, closed incidents and cost. Open incidents and table baselines use fixed windows. |
| Sentinel workspace | Workspaces with Microsoft Sentinel turned on. |
| Table is silent after | A table that has sent nothing for this long is flagged. Some tables are naturally quiet (alerts, rarely used connectors), so read the list rather than the count. |
| Triage due within | A medium or high incident still New after this long counts as not triaged. |
| Playbooks | Which playbooks to include. |

## Tab: Overview

#### Tile silent

*Tiles · Log Analytics* · reads `Usage`

#### Tile health

*Tiles · Log Analytics* · reads `SentinelHealth`

#### Tile high

*Tiles · Log Analytics* · reads `SecurityIncident`

#### Tile untriaged

*Tiles · Log Analytics* · reads `SecurityIncident`

#### Tile activity

*Tiles · Log Analytics* · reads `AzureActivity`

#### Tile workspace

*Tiles · Azure Resource Graph*

> A table is *silent* when nothing has arrived for **{SilentHours} hours** and *dropped* when the last 24 hours
> brought in less than half its daily average of the 7 days before. An incident is *not triaged* when it is still
> **New** after **{TriageHours} hours**. Incidents are counted over the last 90 days whatever the time range.
> A daily cap on a Sentinel workspace stops security data arriving when it is reached, and Sentinel includes 90 days
> of retention, so less than that is usually a mistake.

#### Ingestion by table, top 10 (GB)

*Time chart · Log Analytics* · reads `Usage`

#### Incidents created per day by severity

*Bar chart · Log Analytics* · reads `SecurityIncident`

#### Connectors, rules and automation failing (latest state)

*Table · Log Analytics* · reads `SentinelHealth`

Columns: Type, Resource, Status, Since, Detail.

When there is nothing to show: *Nothing is failing (or health monitoring is not turned on: Sentinel → Settings → Auditing and health monitoring).*

## Tab: Data collection

#### Tables: last record and volume (last 24 hours against the 7 days before)

*Table · Log Analytics* · reads `Usage`

Columns: Table, Status, Last data, Hours since data, GB last 24 h, GB per day (7-day average), Billable.

> Read from the `Usage` table, which records every table's volume each hour. A table that sent nothing for the whole 8 days is not listed: check the data connector itself.

#### Data connector health

*Table · Log Analytics* · reads `SentinelHealth`

Columns: Connector, Kind, Status, Failures, Last report, Detail.

When there is nothing to show: *No data connector health records. Only some connectors report health, and only once health monitoring is turned on.*

#### Data connectors configured

*Table · Azure Resource Manager*: `GET {Workspace}/providers/Microsoft.SecurityInsights/dataConnectors`

Columns: Connector, Kind.

When there is nothing to show: *No data connectors returned. Connectors installed from the Content hub as solutions may not be listed here.*

#### Subscriptions sending the activity log to this workspace

*Table · Log Analytics* · reads `AzureActivity`

Columns: Subscription, Subscription Id, State, Status, Records, Last record.

#### Ingestion by table over time, top 10 (GB)

*Time chart · Log Analytics* · reads `Usage`

## Tab: Detections

#### Analytics rules with failed runs

*Table · Log Analytics* · reads `SentinelHealth`

Columns: Rule, Kind, Status, Failures, Runs, Last failure, Last failure detail, Last run.

When there is nothing to show: *No analytics rule failures (or health monitoring is not turned on).*

> Sentinel turns off a scheduled rule that keeps failing (for example because a table or column it reads no longer exists). Such a rule shows here before it is turned off, and as *Enabled: false* below after.

#### Analytics rules

*Table · Azure Resource Manager*: `GET {Workspace}/providers/Microsoft.SecurityInsights/alertRules`

Columns: Rule, Kind, Enabled, Severity, Frequency, Last modified, Template version.

When there is nothing to show: *No analytics rules.*

#### Rules to tune: closed incidents that were not true positives

*Table · Log Analytics* · reads `SecurityIncident`, `SecurityAlert`

Columns: Rule, Closed, Not true positive %, False positive, Benign positive, Undetermined, True positive.

When there is nothing to show: *No rule had three or more incidents closed in the time range.*

#### Noisiest rules (alerts in the time range)

*Table · Log Analytics* · reads `SecurityAlert`

When there is nothing to show: *No alerts from analytics rules.*

#### Rules that ran but raised no alert (time range)

*Table · Log Analytics* · reads `SentinelHealth`, `SecurityAlert`

Columns: Rule, Runs, Last run.

When there is nothing to show: *Every rule that ran raised at least one alert (or health monitoring is not turned on).*

> A quiet rule is often fine. It is worth a look when the table it reads has gone silent (Data collection tab), or after the source changed its schema.

#### Changes to rules, connectors and settings (SentinelAudit)

*Table · Log Analytics* · reads `SentinelAudit`

Columns: Time Generated, Type, Resource, Operation, Status, Caller, Caller IP.

When there is nothing to show: *No changes recorded (or auditing is not turned on: Sentinel → Settings → Auditing and health monitoring).*

## Tab: Incidents

#### Open incidents by severity and age

*Table · Log Analytics* · reads `SecurityIncident`

When there is nothing to show: *No open incidents.*

#### Still New after {TriageHours} hours

*Table · Log Analytics* · reads `SecurityIncident`

Columns: Incident, Title, Severity, Owner, Created, Age (hours), Product, Link.

When there is nothing to show: *Every incident has been picked up within {TriageHours} hours.*

#### Time to triage and close, incidents created in the time range

*Table · Log Analytics* · reads `SecurityIncident`

> *Triage* is the time from creation to the first change anyone made (assigning, changing status, commenting). Incidents closed by an automation rule count as triaged at once.

#### Workload by owner

*Table · Log Analytics* · reads `SecurityIncident`

#### Closed incidents by source and classification

*Table · Log Analytics* · reads `SecurityIncident`

When there is nothing to show: *No incidents closed in the time range.*

## Tab: Automation

#### Automation rules

*Table · Azure Resource Manager*: `GET {Workspace}/providers/Microsoft.SecurityInsights/automationRules`

Columns: Rule, Order, Enabled, Triggers on, When, Expires, Last modified.

When there is nothing to show: *No automation rules.*

#### Automation rule and playbook runs

*Table · Log Analytics* · reads `SentinelHealth`

When there is nothing to show: *No automation runs recorded (or health monitoring is not turned on).*

#### Playbooks (Logic Apps that use the Sentinel connector)

*Table · Azure Resource Graph*

Columns: Playbook, State, Managed identity, Trigger, Changed, Resource Group.

When there is nothing to show: *No Logic Apps using the Sentinel connector in the selected subscriptions.*

#### Playbook runs failed

*Chart · Azure Monitor metrics* of `microsoft.logic/workflows`: RunsFailed (sum).

#### Playbook actions throttled

*Chart · Azure Monitor metrics* of `microsoft.logic/workflows`: ActionThrottledEvents (sum).

> A playbook that uses an API connection rather than a managed identity stops working when the account that authorised the connection leaves or changes its password.

## Tab: Cost and retention

#### Workspace pricing and access

*Table · Azure Resource Graph*

Columns: Workspace, Tier, Commitment tier (GB/day), Retention (days), Daily cap (GB, -1 = none), Ingestion, Public ingestion, Public query, Resource-context access only, Location.

#### Billable ingestion per day (time range)

*Table · Log Analytics* · reads `Usage`

> Compare the average with the commitment tier above. Ingestion well under the tier is paid for anyway; ingestion steadily over the next tier up is cheaper on that tier. Sentinel and Log Analytics share one commitment tier under simplified pricing.

#### Billable and free ingestion per day (GB)

*Bar chart · Log Analytics* · reads `Usage`

#### Billable ingestion by table

*Table · Log Analytics* · reads `Usage`

Columns: Table, Solution, GB, GB per day.

#### Table plans and retention

*Table · Azure Resource Manager*: `GET {Workspace}/tables`

Columns: Table, Plan, Retention (days), Total retention (days), Archive (days).

> Analytics rules can only read tables on the *Analytics* plan. High-volume data you keep for investigation rather than detection (firewall flows, verbose diagnostics) is cheaper on *Basic* or *Auxiliary*. The **Log Analytics: cost and noise** workbook shows which tables are queried and by whom.

## Tab: Purview

> Purview reaches Sentinel in several ways: DLP and Insider Risk alerts through the Defender XDR connector (as `SecurityAlert`, with alert detail in `AlertInfo` and `AlertEvidence`), sensitivity label activity through the *Microsoft Purview Information Protection* connector (`MicrosoftPurviewInformationProtection`), data map classifications through the *Microsoft Purview* connector (`PurviewDataSensitivityLogs`) and Microsoft 365 audit through *Office 365* (`OfficeActivity`). A table that is missing below is not connected.

#### Purview-related tables

*Table · Log Analytics* · reads `Usage`

Columns: Table, Status, Last data, Hours since data, GB last 24 h, GB per day (7-day average).

When there is nothing to show: *None of the Purview-related tables has received data in the last 8 days.*

#### DLP, Insider Risk and Information Protection alerts

*Time chart · Log Analytics* · reads `SecurityAlert`

When there is nothing to show: *No Purview alerts in the time range.*

#### Most frequent Purview alerts

*Table · Log Analytics* · reads `SecurityAlert`

When there is nothing to show: *No Purview alerts in the time range.*

#### Sensitivity label activity by workload

*Table · Log Analytics* · reads `MicrosoftPurviewInformationProtection`

When there is nothing to show: *No Information Protection events (or the connector is not configured).*

#### Labels removed or downgraded, by user

*Table · Log Analytics* · reads `MicrosoftPurviewInformationProtection`

When there is nothing to show: *No labels removed or downgraded in the time range.*
