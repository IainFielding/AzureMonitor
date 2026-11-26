# Azure Virtual Desktop: one user's sessions

*Reference for [avd-user.workbook.json](../workbook/avd-user.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

Why is this user's session failing, slow to start, or laggy? Their connections and how each ended, the errors and their likely cause, sign-in time by stage, network quality, and the health and load of the session hosts they used.

It has 13 panels. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Log Analytics workspace | The workspace your host pools, session hosts and Entra ID sign-in logs send to. |
| Time range | The period the log and metric panels cover. |
| Find user | Part of the user's sign-in name, e.g. jane.smith, to narrow the User list. Leave empty to list the 1,000 users seen most recently. |
| User | Users who connected to, or failed to connect to, Azure Virtual Desktop in the time range, most recent first, with their error count. |
| Nerdio Manager app id | Optional. The application (client) id of Nerdio Manager's app registration, to label its actions on the session hosts. |

## Panels

> Select the **Log Analytics workspace** your host pools send their diagnostics to.

> Pick a **user** to begin (type part of their name in *Find user* to narrow the list).

> Pick the user from the list, typing part of their name in *Find user* first to narrow it. The list holds the users
> who connected or hit an error in the time range, most recent first. Every panel follows the connections that user
> made: when, from which client, to which session host, how they ended, and why.
>
> **Reading it.** *Never connected* attempts carry the error: *Side* says whether Azure Virtual Desktop itself failed
> or the host, its configuration or the client did, and *Likely cause* explains the common codes. A slow sign-in
> shows in *Time to the desktop* with its slowest Windows stages: *Profile* is usually FSLogix (see the profile
> events), *GroupPolicy* is policy processing, *Shell* is the desktop starting. A laggy session is usually the
> network (round-trip time above about 150 ms, or low bandwidth) or the host (high CPU, low free memory, input delay).
>
> Needs the host pool's and workspace's diagnostic settings (`WVDConnections`, `WVDErrors`, `WVDCheckpoints`,
> `WVDConnectionNetworkData`, `WVDAgentHealthStatus`). Host load needs the hosts' performance counters (`Perf`) or VM
> insights (`InsightsMetrics`); profile events need the FSLogix and User Profile Service event logs collected
> (`Event`); sign-ins need the Entra ID sign-in logs (`SigninLogs`), and actions on the hosts (Nerdio Manager
> auto-scale, scaling plans) the subscription activity log (`AzureActivity`), in the same workspace. Disk space
> needs the `LogicalDisk(*)` counters (AVD Insights collects only C:) and low disk warnings the System event log.

#### Tiles

*Tiles · Log Analytics* · reads `WVDConnections`, `WVDConnectionNetworkData`, `WVDErrors`

When there is nothing to show: *No connections for this user in the time range.*

#### Connection attempts

*Table · Log Analytics* · reads `WVDConnections`, `WVDErrors`, `WVDConnectionNetworkData`, `WVDCheckpoints`

Columns: Started, Outcome, Errors, Host, Host pool, Duration (min), To desktop (s), RTT p50 (ms), RTT p95 (ms), Bandwidth (Mbps), Client, Client OS, Client IP, Gateway region, UDP use, Type, User, Correlation id.

When there is nothing to show: *No connections for this user in the time range. Check the name, or widen the time range.*

#### Errors and their likely cause

*Table · Log Analytics* · reads `WVDConnections`, `WVDErrors`

Columns: Time, Source, Operation, Code, Side, Likely cause, Message, Correlation id.

When there is nothing to show: *No errors logged for this user.*

#### Time to the desktop, and the slowest Windows sign-in stages

*Table · Log Analytics* · reads `WVDConnections`, `WVDCheckpoints`

Columns: Started, Host, To desktop (s), At credential prompt (s), Windows sign-in (s), Slowest stages, Correlation id.

When there is nothing to show: *No new sessions in the time range (reconnects to an existing session have no sign-in).*

#### Round-trip time by session host (ms)

*Time chart · Log Analytics* · reads `WVDConnections`, `WVDConnectionNetworkData`

When there is nothing to show: *No network data (WVDConnectionNetworkData).*

#### Available bandwidth by session host (Mbps)

*Time chart · Log Analytics* · reads `WVDConnections`, `WVDConnectionNetworkData`

When there is nothing to show: *No network data (WVDConnectionNetworkData).*

### The session hosts they used

#### Session host health (latest report)

*Table · Log Analytics* · reads `WVDConnections`, `WVDAgentHealthStatus`

Columns: Session host, Status, Failing health checks, Allows new sessions, Active sessions, Disconnected sessions, Agent, Last report, Host pool.

When there is nothing to show: *No agent health reports for these hosts (WVDAgentHealthStatus).*

#### Host load over the time range

*Table · Log Analytics* · reads `WVDConnections`, `Perf`, `InsightsMetrics`

When there is nothing to show: *No performance counters from these hosts (Perf or InsightsMetrics).*

#### Host CPU % over time

*Time chart · Log Analytics* · reads `WVDConnections`, `Perf`, `InsightsMetrics`

When there is nothing to show: *No CPU counters from these hosts.*

#### Disk space on those hosts (fullest first)

*Table · Log Analytics* · reads `WVDConnections`, `Perf`, `InsightsMetrics`, `Event`

Columns: Host, Volume, Kind, Free % (latest), Lowest free %, Free GB (latest), Low disk warnings, Last warning, Last report.

When there is nothing to show: *No disk counters from these hosts (LogicalDisk in Perf, or VM insights).*

> **A low disk space warning in the session** is usually the user's FSLogix profile disk (a *mounted virtual disk* here) filling up, not C:. Personal desktops: look at C:. Pooled hosts show one mounted disk per signed-in user and the counters do not say whose is whose, so a full one on the host the user was on is a strong lead. FSLogix errors about the profile disk show in the profile panel below. Grow the container by expanding the VHDX, or raise FSLogix's *SizeInMBs* for new ones.

#### Profile (FSLogix) and User Profile Service errors on those hosts

*Table · Log Analytics* · reads `WVDConnections`, `Event`

Columns: Time, Host, Source, Event, Level, Names this user, Description.

When there is nothing to show: *No profile errors or warnings on these hosts (or the FSLogix and User Profile Service event logs are not collected).*

#### Auto-scale and other actions on those hosts (Nerdio Manager, scaling plans, admins)

*Table · Log Analytics* · reads `WVDConnections`, `AzureActivity`

Columns: Time, Host, Action, During their session, Status, Kind, Caller, Error, Message, Correlation id.

When there is nothing to show: *No Resource Manager actions on these hosts in the time range (or AzureActivity is not in this workspace).*

#### Entra ID sign-ins to Azure Virtual Desktop

*Table · Log Analytics* · reads `WVDConnections`, `SigninLogs`

Columns: Time, App, Resource, Outcome, Result, Reason, Conditional Access, Client app, Ip, Os, Where.

When there is nothing to show: *No Azure Virtual Desktop sign-ins for this user (or SigninLogs is not in this workspace).*
