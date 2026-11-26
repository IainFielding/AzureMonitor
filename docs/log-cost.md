# Log Analytics: cost and noise

*Reference for [log-cost.workbook.json](../workbook/log-cost.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

Where is ingestion going, what does it cost, and what could you stop paying for? Volume by table and source, spikes, tables nobody queries, data collected twice, and the workspace's plan and limits.

It has 11 panels. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Log Analytics workspace | The workspace to analyse. |
| Time range | The period the log and metric panels cover. |
| Price per GB | What you pay per GB of Analytics logs, in your currency. Used for the estimated cost columns. |

## Panels

> Pick one workspace and a time range (30 days gives a fair month), and set **Price per GB** to what you pay for
> Analytics logs in your region and currency (pay-as-you-go, before any commitment tier discount), so the cost
> columns are close. Usage is billable volume as Azure Monitor meters it; Microsoft Sentinel and Defender for
> Servers charges and data allowances are not included.
>
> **Where savings usually are**, roughly in order:
> 1. **Stop collecting what nobody reads.** *Who reads it* lists tables no query has touched. Drop them at the
>    source (diagnostic setting categories, data collection rules), or filter them with a transformation.
> 2. **Trim noisy sources.** Select a table under *Tables* to see what inside it is big: a debug log category, a
>    Windows event ID, a performance counter at a 10-second interval, one chatty resource.
> 3. **Collect once.** *Collected twice* finds machines sending the same data through two agents or two paths.
> 4. **Cheaper plans** for logs kept for investigation, not alerting: *Basic* or *Auxiliary* tables cost far less
>    to ingest but limit how they can be queried. Not every table supports them; see *Table plans and retention*.
> 5. **A commitment tier** once you ingest a steady 100 GB a day or more.

#### Workspace

*Table · Azure Resource Graph*

Columns: Workspace, Sku, Commitment tier (GB/day), Retention (days), Daily cap (GB), Ingestion, Cap resets at, Location.

#### Tiles

*Tiles · Log Analytics* · reads `Usage`

#### Billable GB per day, ten biggest tables

*Bar chart · Log Analytics* · reads `Usage`

#### Tables by billable volume

*Table · Log Analytics* · reads `Usage`

Columns: Table, GB, Share %, GB per day, Est. per month, Change % (7 days), Solutions.

When there is nothing to show: *No billable ingestion in the time range.*

> Select a table to see its biggest sources and what makes it big, below. *Change* compares the last 7 days with
> the 7 before; it needs a time range of 14 days or more. *Spikes* lists any day at least twice the table's normal
> day.

#### {SelectedTable}: biggest sources, and what makes it big

*Table · Log Analytics*

When there is nothing to show: *No billable records in this table in the time range.*

#### Spikes: days at least twice a table's normal volume

*Table · Log Analytics* · reads `Usage`

Columns: Table, Day, GB that day, Normal day (GB), Times normal.

When there is nothing to show: *No spikes over 1 GB.*

#### Ingestion warnings (daily cap, dropped or throttled data)

*Table · Log Analytics*

When there is nothing to show: *No ingestion warnings.*

### Who reads it

#### Tables and the queries that read them

*Table · Log Analytics* · reads `Usage`, `LAQueryLogs`

Columns: Table, GB, Queries, People and apps, Client apps, Last queried, Verdict.

When there is nothing to show: *No billable ingestion in the time range.*

> Counts every query run against this workspace in the time range: people in the portal, alert rules, workbooks, dashboards and other tools. It needs the workspace's own diagnostic setting sending **Audit** (`LAQueryLogs`); queries that reach the table through a function or another workspace's cross-workspace query may be missed. *Never queried* over 30 days is a strong hint, not proof: check for alert rules and data exports first.

### Who sends it

### Show the biggest sources (reads every table: slow over a long time range) (loads when asked)

#### Biggest sources (resource or computer, by table)

*Table · Log Analytics*

When there is nothing to show: *No billable records.*

#### Collected twice

*Table · Log Analytics* · reads `Heartbeat`, `Perf`, `InsightsMetrics`

When there is nothing to show: *No machine sends through two agents, or the same counters to both Perf and InsightsMetrics.*

### Table plans and retention

#### Tables

*Table · Azure Resource Manager*: `GET {Workspace}/tables`

Columns: Table, Plan, Retention (days), Total retention (days), Kind, Collected by.

When there is nothing to show: *Could not read the workspace's tables.*

> *Analytics* is the full plan. *Basic* and *Auxiliary* cost much less to ingest but are charged per query and cannot drive most alerts; they suit verbose logs kept for investigation. Retention beyond the workspace default, and *Total retention* (long-term), are charged per GB per month.
