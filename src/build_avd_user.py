"""Generates the Azure Virtual Desktop user troubleshooting workbook.

Run:  python src/build_avd_user.py
Out:  workbook/avd-user.workbook.json

Answers "why is this user's session bad?" for one user: every connection attempt and how it ended, the errors with
their likely cause, how long sign-in took and which stage was slow, the connection's round-trip time and bandwidth,
the health and load of the session hosts they landed on, profile (FSLogix) errors on those hosts, and their Entra ID
sign-ins to Azure Virtual Desktop. All from Log Analytics: the host pool's diagnostic settings (WVD* tables), the
session hosts' performance counters and event logs, and the Entra ID sign-in logs. Built from the helpers in
build_workbook.py so the workbooks look alike.
"""

import pathlib

from build_workbook import (DAY_MS, WORKSPACE_SET, WORKSPACE_UNSET, big_number_tiles, free_text_param, la,
                            low_is_good, notebook, params, resource_link, status_fmt, subscription_param, text,
                            time_param, when_empty, when_set, workspace_param, write_workbook)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "avd-user.workbook.json"

P = "avdu"
HOUR_MS = 3600000

# ---------------------------------------------------------------------------
# The user's connections
# ---------------------------------------------------------------------------

# A connection attempt is one CorrelationId: it logs Started, then Connected if the user reached a host, then
# Completed when it ends. The host and client columns are filled in on some of those rows only. GatewayRegion and
# UdpUse were added to the table later, so they are read with column_ifexists.
USER = r"""let User = trim(@'\s+', @'{User}');
let Connections = WVDConnections
| where TimeGenerated {TimeRange}
| where isnotempty(User) and UserName contains User
| summarize Started = min(TimeGenerated), ConnectedAt = minif(TimeGenerated, State == 'Connected'),
    Ended = maxif(TimeGenerated, State == 'Completed'), LastSeen = max(TimeGenerated),
    UserName = take_any(UserName), Host = take_anyif(SessionHostName, isnotempty(SessionHostName)),
    HostPoolId = take_any(tolower(_ResourceId)), ClientType = take_anyif(ClientType, isnotempty(ClientType)),
    ClientVersion = take_anyif(ClientVersion, isnotempty(ClientVersion)), ClientOS = take_anyif(ClientOS, isnotempty(ClientOS)),
    ClientIp = take_anyif(ClientSideIPAddress, isnotempty(ClientSideIPAddress)),
    ConnectionType = take_anyif(ConnectionType, isnotempty(ConnectionType)),
    GatewayRegion = take_any(tostring(column_ifexists('GatewayRegion', ''))), UdpUse = take_any(tostring(column_ifexists('UdpUse', '')))
    by CorrelationId
| extend HostShort = tolower(tostring(split(Host, '.')[0]))
| extend Outcome = case(isnotnull(ConnectedAt) and isnotnull(Ended), 'Connected, then ended',
    isnotnull(ConnectedAt), 'Connected (still on, or end not logged)', isnotnull(Ended), 'Never connected', 'In progress or abandoned');
let Ids = Connections | project CorrelationId;
let Hosts = Connections | where isnotempty(HostShort) | summarize by HostShort;
"""

# Likely causes for the common error codes. A code is one long word (ConnectionFailedNoHealthyRdshAvailable), so the
# known fragments are matched anywhere in it.
CAUSE = r"""case(
    Text matches regex @'(?i)(NoHealthyRdsh|NoHealthyRdshAvailable|SessionHostNotAvailable|NoAvailableSessionHost)',
        'No session host available: all full, in drain mode, unhealthy or shut down',
    Text matches regex @'(?i)(UserNotAuthorized|NotAuthorized|UserNotAssigned|NotInAppGroup|AuthorizationFailed)',
        'Not assigned to an application group, or (Entra ID joined hosts) no Virtual Machine User Login role',
    Text matches regex @'(?i)(TrustedRelationshipFailure|TrustRelationship)', 'The session host has lost its domain trust: rejoin it',
    Text matches regex @'(?i)(LogonFailure|PasswordExpired|PasswordMustChange|AccountLockedOut|AccountDisabled|AccountRestriction)',
        'Windows sign-in on the host failed: password, locked or disabled account, or a Kerberos or SSO problem',
    Text matches regex @'(?i)(Timeout|TimedOut|StackTimeout|ReverseConnectTimeout)',
        'The host did not answer in time: agent or RD stack unhealthy, or the host overloaded',
    Text matches regex @'(?i)(ClientDisconnect|ConnectionBroken|NetworkDrop|MissedHeartbeat|ConnectionLost|TransportClosed)',
        'The network dropped between client and host (or the user closed the client)',
    Text matches regex @'(?i)(FSLogix|Profile|ProfileLoad)', 'The user profile failed to load: see the profile events below',
    Text matches regex @'(?i)(Licensing|License)', 'Remote Desktop licensing problem on the host',
    '')"""

TILES_Q = USER + r"""let Rtt = union isfuzzy=true (datatable(TimeGenerated: datetime, CorrelationId: string)[]), (WVDConnectionNetworkData)
    | where TimeGenerated {TimeRange}
    | where CorrelationId in (Ids)
    | summarize P50 = percentile(toreal(column_ifexists('EstRoundTripTimeInMs', real(null))), 50);
let Errors = WVDErrors | where TimeGenerated {TimeRange} | where isnotempty(User) and UserName contains User | count;
Connections
| summarize Attempts = count(), Connected = countif(isnotnull(ConnectedAt)), Hosts = dcount(Host)
| extend Rtt = toscalar(Rtt), Errors = toscalar(Errors)
| extend rows = pack_array(
    pack('Signal', 'Connection attempts', 'Value', Attempts, 'Detail', strcat('to ', Hosts, ' session hosts'), 'State', 'Unknown'),
    pack('Signal', 'Never connected', 'Value', Attempts - Connected, 'Detail', strcat('of ', Attempts),
        'State', iff(Attempts - Connected > 0, 'Unavailable', 'Available')),
    pack('Signal', 'Errors', 'Value', Errors, 'Detail', 'logged for this user', 'State', iff(Errors > 0, 'Degraded', 'Available')),
    pack('Signal', 'Median round-trip time', 'Value', round(Rtt), 'Detail', 'ms',
        'State', case(isnull(Rtt), 'Unknown', Rtt > 200, 'Unavailable', Rtt > 100, 'Degraded', 'Available')))
| mv-expand r = rows
| project Signal = tostring(r.Signal), Value = toreal(r.Value), Detail = tostring(r.Detail), State = tostring(r.State)
"""

# One row per attempt, with its errors, network quality and sign-in time.
SESSIONS_Q = USER + r"""let Err = WVDErrors
    | where TimeGenerated {TimeRange}
    | where CorrelationId in (Ids)
    | summarize Errors = strcat_array(make_set(CodeSymbolic, 3), ', ') by CorrelationId;
let Net = union isfuzzy=true (datatable(TimeGenerated: datetime, CorrelationId: string)[]), (WVDConnectionNetworkData)
    | where TimeGenerated {TimeRange}
    | where CorrelationId in (Ids)
    | extend Rtt = toreal(column_ifexists('EstRoundTripTimeInMs', real(null))), Kbps = toreal(column_ifexists('EstAvailableBandwidthKBps', real(null)))
    | summarize RttP50 = round(percentile(Rtt, 50)), RttP95 = round(percentile(Rtt, 95)), BandwidthMbps = round(percentile(Kbps, 50) * 8 / 1000, 1)
        by CorrelationId;
let Ready = union isfuzzy=true (datatable(TimeGenerated: datetime, CorrelationId: string, Name: string)[]), (WVDCheckpoints)
    | where TimeGenerated {TimeRange}
    | where CorrelationId in (Ids)
    | where Name =~ 'ShellReady' or Name =~ 'RdpShellAppExecuted'
        or (Name =~ 'LaunchExecutable' and tostring(column_ifexists('Parameters', dynamic(null)).connectionStage) == 'RdpShellAppExecuted')
    | summarize Ready = min(TimeGenerated) by CorrelationId;
Connections
| join kind=leftouter Err on CorrelationId
| join kind=leftouter Net on CorrelationId
| join kind=leftouter Ready on CorrelationId
| project Started, Outcome, Errors, Host, HostPoolId, Minutes = round((coalesce(Ended, LastSeen) - Started) / 1m, 0),
    SignInSec = round((Ready - Started) / 1s), RttP50, RttP95, BandwidthMbps, Client = strcat(ClientType, ' ', ClientVersion),
    ClientOS, ClientIp, GatewayRegion, UdpUse, ConnectionType, UserName, CorrelationId
| order by Started desc
| take 500
"""

ERRORS_Q = USER + r"""WVDErrors
| where TimeGenerated {TimeRange}
| where isnotempty(User) and UserName contains User
| extend Text = strcat(CodeSymbolic, ' ', Message)
| project Time = TimeGenerated, Source, Operation = tostring(column_ifexists('Operation', '')), Code = CodeSymbolic,
    Side = iff(tobool(ServiceError), 'Azure Virtual Desktop service', 'Host, configuration or client'),
    LikelyCause = CAUSE, Message, CorrelationId
| order by Time desc
| take 500
""".replace("CAUSE", CAUSE)

# Time to the desktop: from the connection starting to the shell being ready, less the time spent at a credential
# prompt, and the Windows sign-in stages the host reports (LogonDelay) for each new session. Reconnects to an
# existing session have neither.
LOGON_Q = USER + r"""let Checkpoints = union isfuzzy=true (datatable(TimeGenerated: datetime, CorrelationId: string, Name: string)[]), (WVDCheckpoints)
    | where TimeGenerated {TimeRange}
    | where CorrelationId in (Ids)
    | extend Parameters = column_ifexists('Parameters', dynamic(null));
let Stages = Checkpoints
    | where Name == 'LogonDelay'
    | extend stages = bag_remove_keys(Parameters, dynamic(['LogonType', 'WinLogonPid']))
    | mv-expand bagexpansion=array stages
    | extend Stage = tostring(stages[0]), Seconds = toreal(stages[1]) / 1000
    | where Stage startswith 'WinLogon_Logon_'
    | summarize Seconds = round(sum(Seconds), 1) by CorrelationId, Stage = substring(Stage, strlen('WinLogon_Logon_'))
    | order by Seconds desc
    | summarize WindowsSignInSec = round(sum(Seconds), 1), SlowestStages = strcat_array(make_list(strcat(Stage, ' ', Seconds, 's'), 4), ' · ')
        by CorrelationId;
let Prompt = Checkpoints
    | where Name in~ ('OnCredentialsAcquisitionCompleted', 'SSOTokenRetrieval')
    | summarize PromptSec = sum(tolong(Parameters.DurationMS)) / 1000.0 by CorrelationId;
let Ready = Checkpoints
    | where Name =~ 'ShellReady' or Name =~ 'RdpShellAppExecuted'
        or (Name =~ 'LaunchExecutable' and tostring(Parameters.connectionStage) == 'RdpShellAppExecuted')
    | summarize Ready = min(TimeGenerated) by CorrelationId;
Connections
| join kind=inner Ready on CorrelationId
| join kind=leftouter Prompt on CorrelationId
| join kind=leftouter Stages on CorrelationId
| project Started, Host, ToDesktopSec = round((Ready - Started) / 1s - coalesce(PromptSec, 0.0)), AtPromptSec = round(PromptSec),
    WindowsSignInSec, SlowestStages, CorrelationId
| order by Started desc
"""

NETWORK_Q = USER + r"""union isfuzzy=true (datatable(TimeGenerated: datetime, CorrelationId: string)[]), (WVDConnectionNetworkData)
| where TimeGenerated {TimeRange}
| where CorrelationId in (Ids)
| join kind=inner (Connections | project CorrelationId, Host) on CorrelationId
| summarize RttMs = round(avg(toreal(column_ifexists('EstRoundTripTimeInMs', real(null))))) by bin(TimeGenerated, {TimeRange:grain}), Host
"""

BANDWIDTH_Q = USER + r"""union isfuzzy=true (datatable(TimeGenerated: datetime, CorrelationId: string)[]), (WVDConnectionNetworkData)
| where TimeGenerated {TimeRange}
| where CorrelationId in (Ids)
| join kind=inner (Connections | project CorrelationId, Host) on CorrelationId
| summarize Mbps = round(avg(toreal(column_ifexists('EstAvailableBandwidthKBps', real(null)))) * 8 / 1000, 1)
    by bin(TimeGenerated, {TimeRange:grain}), Host
"""

# ---------------------------------------------------------------------------
# The session hosts they used
# ---------------------------------------------------------------------------

# Latest agent report per host, and any health check that is not passing. The checks are a JSON list in
# SessionHostHealthCheckResult.
HOST_HEALTH_Q = USER + r"""WVDAgentHealthStatus
| where TimeGenerated {TimeRange}
| extend HostShort = tolower(tostring(split(SessionHostName, '.')[0]))
| where HostShort in (Hosts)
| summarize arg_max(TimeGenerated, *) by SessionHostName
| extend Status = iff(TimeGenerated < ago(30m), 'Offline', Status)
| mv-expand check = iff(isempty(tostring(column_ifexists('SessionHostHealthCheckResult', ''))), dynamic([null]),
    parse_json(tostring(column_ifexists('SessionHostHealthCheckResult', ''))))
| extend Failed = iff(isnotempty(tostring(check.HealthCheckResult)) and tostring(check.HealthCheckResult) !~ 'HealthCheckSucceeded',
    strcat(tostring(check.HealthCheckName), ': ', tostring(check.AdditionalFailureDetails.Message)), '')
| summarize FailingChecks = strcat_array(make_set_if(Failed, isnotempty(Failed)), ' · '),
    arg_max(TimeGenerated, Status, LastReport = TimeGenerated, AllowNewSessions = tostring(column_ifexists('AllowNewSessions', '')),
        ActiveSessions = toint(column_ifexists('ActiveSessions', int(null))), InactiveSessions = toint(column_ifexists('InactiveSessions', int(null))),
        AgentVersion = tostring(column_ifexists('AgentVersion', '')), HostPoolId = tolower(_ResourceId))
    by SessionHostName
| project SessionHostName, Status, FailingChecks, AllowNewSessions, ActiveSessions, InactiveSessions, AgentVersion, LastReport, HostPoolId
"""

# CPU, memory and input delay on those hosts over the time range, from the Windows performance counters (Perf) or
# VM insights (InsightsMetrics), whichever the hosts send.
HOST_PERF = r"""let Perf_ = union isfuzzy=true
    (union isfuzzy=true (datatable(TimeGenerated: datetime, Computer: string)[]), (Perf)
    | where TimeGenerated {TimeRange}
    | extend HostShort = tolower(tostring(split(Computer, '.')[0]))
    | where HostShort in (Hosts)
    | extend Object = tostring(column_ifexists('ObjectName', '')), Counter = tostring(column_ifexists('CounterName', '')),
        Instance = tostring(column_ifexists('InstanceName', '')), Value = toreal(column_ifexists('CounterValue', real(null)))
    | extend Metric = case(Object in ('Processor', 'Processor Information') and Counter == '% Processor Time' and Instance == '_Total', 'CpuPct',
        Object == 'Memory' and Counter == 'Available MBytes', 'FreeMemoryMB',
        Object == 'User Input Delay per Session' and Counter == 'Max Input Delay', 'InputDelayMs', '')
    | where isnotempty(Metric)),
    (union isfuzzy=true (datatable(TimeGenerated: datetime, Computer: string)[]), (InsightsMetrics)
    | where TimeGenerated {TimeRange}
    | extend HostShort = tolower(tostring(split(Computer, '.')[0]))
    | where HostShort in (Hosts)
    | extend Namespace = tostring(column_ifexists('Namespace', '')), Name = tostring(column_ifexists('Name', '')),
        Value = toreal(column_ifexists('Val', real(null)))
    | extend Metric = case(Namespace == 'Processor' and Name == 'UtilizationPercentage', 'CpuPct',
        Namespace == 'Memory' and Name == 'AvailableMB', 'FreeMemoryMB', '')
    | where isnotempty(Metric));
"""

HOST_LOAD_Q = USER + HOST_PERF + r"""Perf_
| summarize CpuP95 = round(percentile(iff(Metric == 'CpuPct', Value, real(null)), 95)), CpuMax = round(maxif(Value, Metric == 'CpuPct')),
    FreeMemoryMinMB = round(minif(Value, Metric == 'FreeMemoryMB')), InputDelayMaxMs = round(maxif(Value, Metric == 'InputDelayMs'))
    by Host = HostShort
| order by CpuP95 desc
"""

HOST_CPU_Q = USER + HOST_PERF + r"""Perf_
| where Metric == 'CpuPct'
| summarize CpuPct = round(avg(Value)) by bin(TimeGenerated, {TimeRange:grain}), HostShort
"""

# Profile problems: FSLogix's own log, and the Windows User Profile Service (1511 and 1515 are temporary
# profiles). Rows that name the user are flagged; FSLogix logs the user's SAM name, the part before the @.
PROFILE_Q = USER + r"""let Sam = tolower(tostring(split(User, '@')[0]));
union isfuzzy=true (datatable(TimeGenerated: datetime, Computer: string)[]), (Event)
| where TimeGenerated {TimeRange}
| extend HostShort = tolower(tostring(split(Computer, '.')[0]))
| where HostShort in (Hosts)
| extend Source = tostring(column_ifexists('Source', '')), Level = tostring(column_ifexists('EventLevelName', '')),
    EventId = toint(column_ifexists('EventID', int(null))), Description = tostring(column_ifexists('RenderedDescription', ''))
| where Source has 'FSLogix' or Source has 'frx' or Source == 'Microsoft-Windows-User Profile Service'
    or (Source == 'User Profile Service' and EventId in (1500, 1508, 1511, 1515, 1521, 1530))
| where Level in ('Error', 'Warning')
| project Time = TimeGenerated, Host = HostShort, Source, EventId, Level,
    ThisUser = iff(isnotempty(Sam) and tolower(Description) contains Sam, 'Yes', ''), Description = substring(Description, 0, 400)
| order by ThisUser desc, Time desc
| take 300
"""

# Entra ID sign-ins to Azure Virtual Desktop and the Windows sign-in the client makes for single sign-on.
SIGNINS_Q = USER + r"""union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (SigninLogs)
| where TimeGenerated {TimeRange}
| extend Upn = tostring(column_ifexists('UserPrincipalName', '')), App = tostring(column_ifexists('AppDisplayName', '')),
    Resource = tostring(column_ifexists('ResourceDisplayName', ''))
| where isnotempty(User) and Upn contains User
| where App has_any ('Virtual Desktop', 'Remote Desktop', 'Windows 365', 'Windows Cloud Login')
    or Resource has_any ('Virtual Desktop', 'Windows Cloud Login', 'Microsoft Remote Desktop')
| extend Result = tostring(column_ifexists('ResultType', '')), Status = column_ifexists('Status', dynamic(null)),
    Device = column_ifexists('DeviceDetail', dynamic(null)), Location = column_ifexists('LocationDetails', dynamic(null))
| project Time = TimeGenerated, App, Resource, Outcome = iff(Result == '0', 'Success', 'Failure'), Result,
    Reason = tostring(Status.failureReason), ConditionalAccess = tostring(column_ifexists('ConditionalAccessStatus', '')),
    ClientApp = tostring(column_ifexists('ClientAppUsed', '')), Ip = tostring(column_ifexists('IPAddress', '')),
    Os = tostring(Device.operatingSystem), Where = strcat_delim(', ', tostring(Location.city), tostring(Location.countryOrRegion))
| order by Time desc
| take 200
"""

OUTCOME = status_fmt("Outcome", good=["Connected, then ended", "Success"], warn=["Connected (still on, or end not logged)",
                                                                              "In progress or abandoned"],
                     bad=["Never connected", "Failure"])

HOW_TO = """\
Enter the user's sign-in name (or part of it). Every panel follows the connections that user made in the time
range: when, from which client, to which session host, how they ended, and why.

**Reading it.** *Never connected* attempts carry the error: *Side* says whether Azure Virtual Desktop itself failed
or the host, its configuration or the client did, and *Likely cause* explains the common codes. A slow sign-in
shows in *Time to the desktop* with its slowest Windows stages: *Profile* is usually FSLogix (see the profile
events), *GroupPolicy* is policy processing, *Shell* is the desktop starting. A laggy session is usually the
network (round-trip time above about 150 ms, or low bandwidth) or the host (high CPU, low free memory, input delay).

Needs the host pool's and workspace's diagnostic settings (`WVDConnections`, `WVDErrors`, `WVDCheckpoints`,
`WVDConnectionNetworkData`, `WVDAgentHealthStatus`). Host load needs the hosts' performance counters (`Perf`) or VM
insights (`InsightsMetrics`); profile events need the FSLogix and User Profile Service event logs collected
(`Event`); sign-ins need the Entra ID sign-in logs (`SigninLogs`) in the same workspace."""


def parameters():
    return params(f"{P}-params", [
        subscription_param(P),
        workspace_param(P, "The workspace your host pools, session hosts and Entra ID sign-in logs send to.", required=True),
        time_param(P, DAY_MS, (HOUR_MS, 4 * HOUR_MS, 12 * HOUR_MS, DAY_MS, 3 * DAY_MS, 7 * DAY_MS, 14 * DAY_MS, 30 * DAY_MS)),
        free_text_param(P, "User", "User", "The user's sign-in name, or part of it, e.g. jane.smith@contoso.com."),
    ])


def user(item):
    return when_set(item, "User")


def workbook():
    return notebook([
        text(f"{P}-header", "# Azure Virtual Desktop: one user's sessions\n"
             "Why is this user's session failing, slow to start, or laggy? Their connections and how each ended, the "
             "errors and their likely cause, sign-in time by stage, network quality, and the health and load of the "
             "session hosts they used."),
        parameters(),
        text(f"{P}-ws-hint", "Select the **Log Analytics workspace** your host pools send their diagnostics to.", "info",
             visible_when=WORKSPACE_UNSET),
        when_empty(text(f"{P}-user-hint", "Enter a **user** to begin.", "info"), "User"),
        text(f"{P}-howto", HOW_TO, "info", visible_when=WORKSPACE_SET),
        user(la(f"{P}-tiles", "", TILES_Q, vis="tiles", tiles=big_number_tiles("Signal", "State", "Value", "Detail"),
                no_data="No connections for this user in the time range.")),
        user(la(f"{P}-sessions", "Connection attempts", SESSIONS_Q,
                formatters=[OUTCOME, resource_link("HostPoolId"), low_is_good("SignInSec", 60, 120),
                            low_is_good("RttP50", 100, 200), low_is_good("RttP95", 150, 300)],
                labels={"HostPoolId": "Host pool", "Minutes": "Duration (min)", "SignInSec": "To desktop (s)",
                        "RttP50": "RTT p50 (ms)", "RttP95": "RTT p95 (ms)", "BandwidthMbps": "Bandwidth (Mbps)",
                        "ClientOS": "Client OS", "ClientIp": "Client IP", "GatewayRegion": "Gateway region",
                        "UdpUse": "UDP use", "ConnectionType": "Type", "UserName": "User", "CorrelationId": "Correlation id"},
                no_data="No connections for this user in the time range. Check the name, or widen the time range.")),
        user(la(f"{P}-errors", "Errors and their likely cause", ERRORS_Q,
                formatters=[status_fmt("Side", warn=["Host, configuration or client"], bad=["Azure Virtual Desktop service"])],
                labels={"LikelyCause": "Likely cause", "CorrelationId": "Correlation id"},
                no_data="No errors logged for this user.")),
        user(la(f"{P}-logon", "Time to the desktop, and the slowest Windows sign-in stages", LOGON_Q,
                formatters=[low_is_good("ToDesktopSec", 60, 120), low_is_good("WindowsSignInSec", 30, 60)],
                labels={"ToDesktopSec": "To desktop (s)", "AtPromptSec": "At credential prompt (s)",
                        "WindowsSignInSec": "Windows sign-in (s)", "SlowestStages": "Slowest stages",
                        "CorrelationId": "Correlation id"},
                no_data="No new sessions in the time range (reconnects to an existing session have no sign-in).")),
        user(la(f"{P}-rtt", "Round-trip time by session host (ms)", NETWORK_Q, vis="timechart", width=50,
                no_data="No network data (WVDConnectionNetworkData).")),
        user(la(f"{P}-bandwidth", "Available bandwidth by session host (Mbps)", BANDWIDTH_Q, vis="timechart", width=50,
                no_data="No network data (WVDConnectionNetworkData).")),
        user(text(f"{P}-hosts-h", "### The session hosts they used")),
        user(la(f"{P}-host-health", "Session host health (latest report)", HOST_HEALTH_Q,
                formatters=[status_fmt("Status", good=["Available"], warn=["Upgrading", "NeedsAssistance"],
                                       bad=["Unavailable", "UpgradeFailed", "NoHeartbeat"], neutral=["Offline", "Shutdown"]),
                            status_fmt("AllowNewSessions", good=["true", "True"], warn=["false", "False"]),
                            resource_link("HostPoolId")],
                labels={"SessionHostName": "Session host", "FailingChecks": "Failing health checks",
                        "AllowNewSessions": "Allows new sessions", "ActiveSessions": "Active sessions",
                        "InactiveSessions": "Disconnected sessions", "AgentVersion": "Agent", "LastReport": "Last report",
                        "HostPoolId": "Host pool"},
                no_data="No agent health reports for these hosts (WVDAgentHealthStatus).")),
        user(la(f"{P}-host-load", "Host load over the time range", HOST_LOAD_Q, width=45,
                formatters=[low_is_good("CpuP95", 80, 95), low_is_good("CpuMax", 90, 100),
                            low_is_good("InputDelayMaxMs", 200, 500)],
                labels={"CpuP95": "CPU p95 %", "CpuMax": "CPU max %", "FreeMemoryMinMB": "Lowest free memory (MB)",
                        "InputDelayMaxMs": "Worst input delay (ms)"},
                no_data="No performance counters from these hosts (Perf or InsightsMetrics).")),
        user(la(f"{P}-host-cpu", "Host CPU % over time", HOST_CPU_Q, vis="timechart", width=55,
                no_data="No CPU counters from these hosts.")),
        user(la(f"{P}-profile", "Profile (FSLogix) and User Profile Service errors on those hosts", PROFILE_Q,
                formatters=[status_fmt("Level", warn=["Warning"], bad=["Error"]), status_fmt("ThisUser", bad=["Yes"])],
                labels={"EventId": "Event", "ThisUser": "Names this user"},
                no_data="No profile errors or warnings on these hosts (or the FSLogix and User Profile Service event "
                        "logs are not collected).")),
        user(la(f"{P}-signins", "Entra ID sign-ins to Azure Virtual Desktop", SIGNINS_Q,
                formatters=[OUTCOME, status_fmt("ConditionalAccess", good=["success", "notApplied"], bad=["failure"])],
                labels={"ConditionalAccess": "Conditional Access", "ClientApp": "Client app"},
                no_data="No Azure Virtual Desktop sign-ins for this user (or SigninLogs is not in this workspace).")),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
