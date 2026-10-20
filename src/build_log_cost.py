"""Generates the Log Analytics cost and noise workbook.

Run:  python src/build_log_cost.py
Out:  workbook/log-cost.workbook.json

Answers "where is my log ingestion going, and what could I stop paying for?" for one workspace: billable volume
and an estimated cost by table and over time, sudden spikes, which tables are never queried, the resources and
computers that send the most, what inside a table makes it big, machines collecting the same data twice, and the
workspace's plan, retention and daily cap. From Log Analytics (Usage, LAQueryLogs and the tables themselves),
Resource Graph and Resource Manager (table plans and retention). Built from the helpers in build_workbook.py so the
workbooks look alike.
"""

import pathlib

from build_workbook import (DAY_MS, arg, arm, big_number_tiles, export_row, free_text_param, group, la,
                            notebook, params, resource_link, status_fmt, subscription_param, text, time_param,
                            when_set, workspace_param, write_workbook)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "log-cost.workbook.json"

P = "lac"

# ---------------------------------------------------------------------------
# Ingestion (Usage)
# ---------------------------------------------------------------------------

# Billable volume per table per day. Usage reports megabytes (10^6 bytes) per hour; the price box is per GB, and an
# empty or non-numeric price leaves the cost columns empty.
DAILY = """let Price = todouble(trim(@'\\s+', @'{Price}'));
let Daily = Usage
    | where TimeGenerated {TimeRange}
    | where IsBillable == true
    | summarize GB = sum(Quantity) / 1000 by Day = startofday(TimeGenerated), DataType, Solution;
"""

TILES_Q = DAILY + """Daily
| summarize GB = sum(GB), Days = dcount(Day), Tables = dcount(DataType)
| extend PerDay = iff(Days > 0, GB / Days, 0.0)
| extend Peak = toscalar(Daily | summarize sum(GB) by Day | summarize max(sum_GB))
| extend rows = pack_array(
    pack('Signal', 'Billable ingestion', 'Value', round(GB, 1), 'Detail', strcat('GB from ', Tables, ' tables over ', Days, ' days')),
    pack('Signal', 'Average per day', 'Value', round(PerDay, 1), 'Detail', strcat('GB · busiest day ', round(Peak, 1), ' GB')),
    pack('Signal', 'Estimated per month', 'Value', round(PerDay * 30.4 * Price), 'Detail',
        iff(isnull(Price), 'set a price per GB at the top', strcat('at ', Price, ' per GB'))))
| mv-expand r = rows
| project Signal = tostring(r.Signal), Value = toreal(r.Value), Detail = tostring(r.Detail), State = 'Unknown'
"""

# The ten biggest tables per day, the rest as Other.
TREND_Q = DAILY + """let Top = Daily | summarize GB = sum(GB) by DataType | top 10 by GB | project DataType;
Daily
| extend Table = iff(DataType in (Top), DataType, 'Other')
| summarize GB = round(sum(GB), 2) by Day, Table
"""

# Per table: volume, share, cost, and the last 7 days against the 7 before (both inside the time range).
TABLES_Q = DAILY + """let Total = toscalar(Daily | summarize sum(GB));
let Days = toscalar(Daily | summarize dcount(Day));
Daily
| summarize GB = sum(GB), Last7 = sumif(GB, Day >= startofday(ago(7d))),
    Prev7 = sumif(GB, Day >= startofday(ago(14d)) and Day < startofday(ago(7d))),
    Solutions = strcat_array(make_set(Solution, 3), ', ') by DataType
| project DataType, GB = round(GB, 2), SharePct = round(100 * GB / Total, 1), PerDay = round(GB / Days, 2),
    CostPerMonth = round(GB / Days * 30.4 * Price, 0),
    ChangePct = iff(Prev7 > 0, round(100 * (Last7 - Prev7) / Prev7), real(null)), Solutions
| order by GB desc
"""

# A day at least twice the table's median day, and over 1 GB: a new source, a debug setting left on, a noisy rule.
SPIKES_Q = DAILY + """Daily
| summarize GB = sum(GB) by Day, DataType
| summarize Median = percentile(GB, 50), arg_max(GB, Day) by DataType
| where GB >= 1 and GB >= 2 * Median
| project DataType, PeakDay = Day, PeakGB = round(GB, 2), MedianGB = round(Median, 2), Times = round(GB / Median, 1)
| order by Times desc
"""

# ---------------------------------------------------------------------------
# Who reads it (LAQueryLogs)
# ---------------------------------------------------------------------------

# Every word in every query run against the workspace, matched to table names. Alert rules, workbooks and
# dashboards all show up here. LAQueryLogs needs the workspace's own diagnostic setting (category Audit).
QUERIED_Q = DAILY + r"""let Queried = union isfuzzy=true (datatable(TimeGenerated: datetime, QueryText: string)[]), (LAQueryLogs)
    | where TimeGenerated {TimeRange}
    | extend Who = coalesce(tostring(column_ifexists('AADEmail', '')), tostring(column_ifexists('AADClientId', ''))),
        App = tostring(column_ifexists('RequestClientApp', ''))
    | extend Words = set_union(extract_all(@'([A-Za-z_][A-Za-z0-9_]*)', QueryText), dynamic([]))
    | mv-expand Word = Words to typeof(string)
    | summarize Queries = count(), People = dcount(Who), Apps = strcat_array(make_set(App, 5), ', '), LastQueried = max(TimeGenerated)
        by Word;
let Audited = toscalar(union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (LAQueryLogs) | where TimeGenerated {TimeRange} | count) > 0;
Daily
| summarize GB = round(sum(GB), 2) by DataType
| join kind=leftouter Queried on $left.DataType == $right.Word
| extend Queries = coalesce(Queries, 0)
| project DataType, GB, Queries, People, Apps, LastQueried,
    Verdict = case(not(Audited), 'Unknown: query auditing is off',
        Queries == 0, 'Never queried', Queries < 10, 'Rarely queried', 'In use')
| order by case(Verdict == 'Never queried', 0, Verdict == 'Rarely queried', 1, 2) asc, GB desc
"""

# ---------------------------------------------------------------------------
# Who sends it (the tables themselves, on demand)
# ---------------------------------------------------------------------------

TOP_SOURCES_Q = """
union withsource = LogTable_ *
| where TimeGenerated {TimeRange}
| where _IsBillable == true
| extend Source = coalesce(tolower(tostring(column_ifexists('_ResourceId', ''))), tostring(column_ifexists('Computer', '')))
| summarize GB = round(sum(_BilledSize) / 1e9, 2) by Source, Table = LogTable_
| top 100 by GB desc
"""

# What makes a table big: the column that usually explains its volume, per source. A table not listed is split by
# source only.
DETAIL = """case(
    T == 'AzureDiagnostics', strcat_delim(' · ', tostring(column_ifexists('ResourceProvider', '')), tostring(column_ifexists('Category', ''))),
    T == 'AzureActivity', strcat_delim(' · ', tostring(column_ifexists('CategoryValue', '')), tostring(column_ifexists('OperationNameValue', ''))),
    T == 'AzureMetrics', tostring(column_ifexists('MetricName', '')),
    T == 'SecurityEvent', strcat('Event ', tostring(column_ifexists('EventID', ''))),
    T == 'Event', strcat_delim(' · ', tostring(column_ifexists('Source', '')), tostring(column_ifexists('EventID', ''))),
    T == 'WindowsEvent', strcat_delim(' · ', tostring(column_ifexists('Provider', '')), tostring(column_ifexists('EventID', ''))),
    T == 'Perf', strcat_delim(' · ', tostring(column_ifexists('ObjectName', '')), tostring(column_ifexists('CounterName', ''))),
    T == 'InsightsMetrics', strcat_delim(' · ', tostring(column_ifexists('Namespace', '')), tostring(column_ifexists('Name', ''))),
    T == 'Syslog', strcat_delim(' · ', tostring(column_ifexists('Facility', '')), tostring(column_ifexists('SeverityLevel', '')),
        tostring(column_ifexists('ProcessName', ''))),
    T == 'CommonSecurityLog', strcat_delim(' · ', tostring(column_ifexists('DeviceVendor', '')), tostring(column_ifexists('DeviceProduct', '')),
        tostring(column_ifexists('Activity', ''))),
    T in ('ContainerLogV2', 'ContainerLog'), strcat_delim(' · ', tostring(column_ifexists('PodNamespace', '')), tostring(column_ifexists('ContainerName', ''))),
    T startswith 'App', tostring(column_ifexists('AppRoleName', '')),
    T startswith 'AZFW', tostring(column_ifexists('Action', '')),
    T in ('SigninLogs', 'AADNonInteractiveUserSignInLogs', 'AADServicePrincipalSignInLogs'), tostring(column_ifexists('AppDisplayName', '')),
    T startswith 'Storage', tostring(column_ifexists('OperationName', '')),
    '')"""

TABLE_DETAIL_Q = """let T = '{SelectedTable}';
table(T)
| where TimeGenerated {TimeRange}
| where _IsBillable == true
| extend Source = coalesce(tolower(tostring(column_ifexists('_ResourceId', ''))), tostring(column_ifexists('Computer', ''))), Detail = DETAIL
| summarize GB = round(sum(_BilledSize) / 1e9, 3), Records = count() by Source, Detail
| top 100 by GB desc
""".replace("DETAIL", DETAIL)

# ---------------------------------------------------------------------------
# Collected twice
# ---------------------------------------------------------------------------

# A machine reporting through both the legacy Log Analytics agent and the Azure Monitor Agent sends its data twice;
# so does one whose performance counters go to Perf (a data collection rule) and InsightsMetrics (VM insights).
DUPLICATES_Q = """
let Agents = union isfuzzy=true (datatable(TimeGenerated: datetime, Computer: string, Category: string)[]), (Heartbeat)
    | where TimeGenerated {TimeRange}
    | summarize Agents = make_set(Category) by Computer
    | where set_has_element(Agents, 'Azure Monitor Agent') and (set_has_element(Agents, 'Direct Agent') or set_has_element(Agents, 'SCOM Agent'))
    | project Computer, Issue = 'Two agents: Azure Monitor Agent and the legacy agent', Detail = strcat_array(Agents, ', ');
let PerfGB = union isfuzzy=true (datatable(TimeGenerated: datetime, Computer: string, _BilledSize: real)[]), (Perf)
    | where TimeGenerated {TimeRange}
    | summarize PerfGB = sum(_BilledSize) / 1e9 by Computer;
let MetricsGB = union isfuzzy=true (datatable(TimeGenerated: datetime, Computer: string, _BilledSize: real)[]), (InsightsMetrics)
    | where TimeGenerated {TimeRange}
    | summarize MetricsGB = sum(_BilledSize) / 1e9 by Computer;
let Counters = PerfGB
    | join kind=inner MetricsGB on Computer
    | project Computer, Issue = 'Performance counters in both Perf and InsightsMetrics',
        Detail = strcat(round(PerfGB, 2), ' GB in Perf, ', round(MetricsGB, 2), ' GB in InsightsMetrics');
union Agents, Counters
| order by Issue asc, Computer asc
| take 500
"""

# Ingestion warnings: the daily cap being reached, data dropped or rate limited, collection stopped.
OPERATIONS_Q = """
_LogOperation
| where TimeGenerated {TimeRange}
| where Level in~ ('Warning', 'Error')
| summarize Count = count(), LastSeen = max(TimeGenerated), Detail = take_any(Detail) by Level, Category, Operation
| order by Level asc, Count desc
"""

# ---------------------------------------------------------------------------
# The workspace (Resource Graph)
# ---------------------------------------------------------------------------

WORKSPACE_Q = """
resources
| where id =~ '{Workspace}'
| project id, Sku = tostring(properties.sku.name),
    CommitmentGBPerDay = toint(properties.sku.capacityReservationLevel),
    RetentionDays = toint(properties.retentionInDays),
    DailyCapGB = iff(todouble(properties.workspaceCapping.dailyQuotaGb) < 0, real(null), todouble(properties.workspaceCapping.dailyQuotaGb)),
    Ingestion = tostring(properties.workspaceCapping.dataIngestionStatus),
    CapResetsAt = tostring(properties.workspaceCapping.quotaNextResetTime),
    Location = location
"""

HOW_TO = """\
Pick one workspace and a time range (30 days gives a fair month), and set **Price per GB** to what you pay for
Analytics logs in your region and currency (pay-as-you-go, before any commitment tier discount), so the cost
columns are close. Usage is billable volume as Azure Monitor meters it; Microsoft Sentinel and Defender for
Servers charges and data allowances are not included.

**Where savings usually are**, roughly in order:
1. **Stop collecting what nobody reads.** *Who reads it* lists tables no query has touched. Drop them at the
   source (diagnostic setting categories, data collection rules), or filter them with a transformation.
2. **Trim noisy sources.** Select a table under *Tables* to see what inside it is big: a debug log category, a
   Windows event ID, a performance counter at a 10-second interval, one chatty resource.
3. **Collect once.** *Collected twice* finds machines sending the same data through two agents or two paths.
4. **Cheaper plans** for logs kept for investigation, not alerting: *Basic* or *Auxiliary* tables cost far less
   to ingest but limit how they can be queried. Not every table supports them; see *Table plans and retention*.
5. **A commitment tier** once you ingest a steady 100 GB a day or more."""

TABLES_NOTE = """\
Select a table to see its biggest sources and what makes it big, below. *Change* compares the last 7 days with
the 7 before; it needs a time range of 14 days or more. *Spikes* lists any day at least twice the table's normal
day."""


def parameters():
    return params(f"{P}-params", [
        subscription_param(P),
        workspace_param(P, "The workspace to analyse.", required=True, multi=False),
        time_param(P, 30 * DAY_MS, tuple(d * DAY_MS for d in (1, 7, 14, 30, 60, 90))),
        free_text_param(P, "Price", "Price per GB",
                        "What you pay per GB of Analytics logs, in your currency. Used for the estimated cost columns.",
                        value="2.30"),
    ])


def workbook():
    tables = export_row(la(f"{P}-tables", "Tables by billable volume", TABLES_Q,
                           formatters=[{"columnMatch": "ChangePct", "formatter": 18, "formatOptions": {
                               "thresholdsOptions": "icons", "thresholdsGrid": [
                                   {"operator": ">=", "thresholdValue": "50", "representation": "4", "text": "{0}{1}"},
                                   {"operator": ">=", "thresholdValue": "20", "representation": "2", "text": "{0}{1}"},
                                   {"operator": "Default", "thresholdValue": None, "representation": "success", "text": "{0}{1}"}]}},
                                       {"columnMatch": "SharePct", "formatter": 4, "formatOptions": {"palette": "blue", "min": 0, "max": 100}}],
                           labels={"DataType": "Table", "SharePct": "Share %", "PerDay": "GB per day",
                                   "CostPerMonth": "Est. per month", "ChangePct": "Change % (7 days)"},
                           no_data="No billable ingestion in the time range."), "DataType", "SelectedTable")
    table_cols = [("Table", "$.name", None), ("Plan", "$.properties.plan", None),
                  ("Retention (days)", "$.properties.retentionInDays", None),
                  ("Total retention (days)", "$.properties.totalRetentionInDays", None),
                  ("Kind", "$.properties.schema.tableType", None), ("Collected by", "$.properties.schema.tableSubType", None)]
    return notebook([
        text(f"{P}-header", "# Log Analytics: cost and noise\n"
             "Where is ingestion going, what does it cost, and what could you stop paying for? Volume by table and "
             "source, spikes, tables nobody queries, data collected twice, and the workspace's plan and limits."),
        parameters(),
        text(f"{P}-howto", HOW_TO, "info"),
        arg(f"{P}-workspace", "Workspace", WORKSPACE_Q,
            formatters=[resource_link(), status_fmt("Ingestion", good=["RespectQuota"], bad=["OverQuota", "SubscriptionSuspended"],
                                                   warn=["ApproachingQuota"])],
            labels={"id": "Workspace", "CommitmentGBPerDay": "Commitment tier (GB/day)", "RetentionDays": "Retention (days)",
                    "DailyCapGB": "Daily cap (GB)", "CapResetsAt": "Cap resets at"}),
        la(f"{P}-tiles", "", TILES_Q, vis="tiles", tiles=big_number_tiles("Signal", "State", "Value", "Detail")),
        la(f"{P}-trend", "Billable GB per day, ten biggest tables", TREND_Q, vis="barchart"),
        tables,
        text(f"{P}-tables-note", TABLES_NOTE, "info"),
        when_set(la(f"{P}-table-detail", "{SelectedTable}: biggest sources, and what makes it big", TABLE_DETAIL_Q,
                    formatters=[resource_link("Source")],
                    labels={"Detail": "What (category, event, counter...)"},
                    no_data="No billable records in this table in the time range."), "SelectedTable"),
        la(f"{P}-spikes", "Spikes: days at least twice a table's normal volume", SPIKES_Q, width=50,
           labels={"DataType": "Table", "PeakDay": "Day", "PeakGB": "GB that day", "MedianGB": "Normal day (GB)",
                   "Times": "Times normal"},
           no_data="No spikes over 1 GB."),
        la(f"{P}-ops", "Ingestion warnings (daily cap, dropped or throttled data)", OPERATIONS_Q, width=50,
           formatters=[status_fmt("Level", warn=["Warning"], bad=["Error"])], labels={"LastSeen": "Last seen"},
           no_data="No ingestion warnings."),
        text(f"{P}-read-h", "### Who reads it"),
        la(f"{P}-queried", "Tables and the queries that read them", QUERIED_Q,
           formatters=[status_fmt("Verdict", good=["In use"], warn=["Rarely queried"], bad=["Never queried"],
                                  neutral=["Unknown: query auditing is off"])],
           labels={"DataType": "Table", "People": "People and apps", "Apps": "Client apps", "LastQueried": "Last queried"},
           no_data="No billable ingestion in the time range."),
        text(f"{P}-queried-note", "Counts every query run against this workspace in the time range: people in the "
             "portal, alert rules, workbooks, dashboards and other tools. It needs the workspace's own diagnostic "
             "setting sending **Audit** (`LAQueryLogs`); queries that reach the table through a function or another "
             "workspace's cross-workspace query may be missed. *Never queried* over 30 days is a strong hint, not proof: "
             "check for alert rules and data exports first.", "info"),
        text(f"{P}-send-h", "### Who sends it"),
        group(f"{P}-sources", [
            la(f"{P}-top-sources", "Biggest sources (resource or computer, by table)", TOP_SOURCES_Q,
               formatters=[resource_link("Source")],
               no_data="No billable records."),
        ], load_button="Show the biggest sources (reads every table: slow over a long time range)"),
        la(f"{P}-duplicates", "Collected twice", DUPLICATES_Q,
           no_data="No machine sends through two agents, or the same counters to both Perf and InsightsMetrics."),
        text(f"{P}-plans-h", "### Table plans and retention"),
        arm(f"{P}-plans", "Tables", "{Workspace}/tables", "2022-10-01", table_cols,
            no_data="Could not read the workspace's tables."),
        text(f"{P}-plans-note", "*Analytics* is the full plan. *Basic* and *Auxiliary* cost much less to ingest but are "
             "charged per query and cannot drive most alerts; they suit verbose logs kept for investigation. Retention "
             "beyond the workspace default, and *Total retention* (long-term), are charged per GB per month.", "info"),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
