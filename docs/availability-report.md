# Platform availability

*Reference for [availability-report.workbook.json](../workbook/availability-report.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

The availability of each shared platform service against a **Target%** target, the incidents behind it, and the Azure-wide incidents and maintenance that touched the estate.

It has 8 panels. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Log Analytics workspace | The central workspace that receives every subscription's activity log. |
| Month | The calendar month to report on. |
| Target | The availability each service is measured against. |
| Count as down | Whether a Degraded state counts against availability as well as Unavailable. |
| User-initiated | Whether periods Resource Health marks as caused by your own action count as down. |
| Commentary | Optional. A few lines for the review (what went wrong, what was done about it). Shown at the top of the report. |

## Panels

> Select the **Log Analytics workspace** that receives the subscriptions' activity logs.

### Commentary
{Commentary}

#### Tiles

*Tiles · Log Analytics* · reads `AzureActivity`

#### Sh tiles

*Tiles · Log Analytics* · reads `AzureActivity`

### Availability by service

#### Services

*Table · Log Analytics* · reads `AzureActivity`

Columns: Service, Available %, Target, Resources, Resources affected, Incidents, Minutes impaired, Longest (minutes), Average resource %.

When there is nothing to show: *No platform resources found.*

#### Minutes impaired per day, by service

*Bar chart · Log Analytics* · reads `AzureActivity`

When there is nothing to show: *No platform resource was impaired this month.*

### Six-month trend

#### Available % by month

*Table · Log Analytics* · reads `AzureActivity`

Columns: Service, Label, Pct.

When there is nothing to show: *No platform resources found.*

### Resource Health incidents

#### Incidents

*Table · Log Analytics* · reads `AzureActivity`

Columns: Resource, Service, Start, End, Minutes impaired, Ongoing, State, Cause, Title.

When there is nothing to show: *No platform resource was impaired this month.*

### Azure Service Health

#### Incidents affecting the subscriptions

*Table · Log Analytics* · reads `AzureActivity`

Columns: Started, Mitigated, Hours of impact, Title, Services, Regions, Subscriptions, Incident review, Stage, Tracking ID.

When there is nothing to show: *No Azure Service Health incidents were posted to these subscriptions this month.*

#### Planned maintenance

*Table · Log Analytics* · reads `AzureActivity`

Columns: Started, Mitigated, Hours, Title, Services, Regions, Subscriptions, Tracking ID.

When there is nothing to show: *No planned maintenance was posted to these subscriptions this month.*

> **How availability is worked out.** *Available %* is the share of the month during which **no** resource of the
> service was impaired according to Azure Resource Health, so one firewall out of four going down counts against
> Azure Firewall for as long as it was down. *Average resource %* spreads the same downtime across every resource of
> the service, which is kinder to services with many resources (storage accounts, private DNS zones). Impaired means
> *Unavailable*, plus *Degraded* when **Count as down** says so; *Unknown* is not counted as down. Periods Resource
> Health marks as user-initiated (a gateway someone stopped, a planned resize) are left out unless **User-initiated**
> says to count them. For the current month the window runs to now.
>
> Resources deleted since the month ended are left out, because the list of platform resources comes from Resource
> Graph. Resource Health is Microsoft's view of each resource; it does not see problems in your own configuration
> (a wrong route, a firewall rule), so pair this report with the incidents your team handled.
