"""Generates the Azure Virtual Desktop disconnections and Azure Firewall workbook.

Run:  python src/build_avd_firewall.py
Out:  workbook/avd-firewall.workbook.json

Answers "do our AVD disconnections line up with the firewall struggling or scaling?". Session host traffic to the
Azure Virtual Desktop gateways (reverse connect on TCP 443, and RDP Shortpath over UDP) usually leaves through the
hub firewall, so a firewall short of SNAT ports, unhealthy, slow or in the middle of a scale operation can break
sessions. The workbook puts the disconnections and the firewall's signals on the same time bins, then for each signal
compares how many users dropped while it was under stress with how many dropped otherwise.

All from Log Analytics: the host pools' diagnostic settings (WVDConnections, WVDErrors), the firewalls' metrics
sent through their diagnostic setting (AllMetrics, the AzureMetrics table), the firewall rule logs (AZFW*) and the
activity log (Resource Health events). Built from the helpers in build_workbook.py so the workbooks look alike.
"""

import pathlib

from build_workbook import (DAY_MS, Q_FIREWALLS, WORKSPACE_SET, WORKSPACE_UNSET, big_number_tiles, choice_param,
                            high_is_good, la, low_is_good, notebook, params, resource_param, status_fmt,
                            subscription_param, text, time_param, workspace_param, write_workbook)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "avd-firewall.workbook.json"

P = "avdfw"
HOUR_MS = 3600000

Q_HOST_POOLS = "resources\n| where type =~ 'microsoft.desktopvirtualization/hostpools'"

# Error codes that mean the connection broke or never got through on the network, rather than a sign-in or
# assignment problem. ReverseConnect failures are the session host failing to reach the gateway: the leg that
# usually crosses the firewall.
NETWORK_CODES = r"(?i)(Disconnect|ConnectionBroken|NetworkDrop|MissedHeartbeat|ConnectionLost|TransportClosed|ReverseConnect|Timeout|Shortpath)"

# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------

# One row per connection attempt that hit a network error: when, the code, whether the user had connected (a
# dropped session) or not (a failed connection), and the session host's IP.
ERRS = r"""let Grain = timespan({Grain});
let Start = bin(todatetime('{TimeRange:startISO}'), Grain);
let End = todatetime('{TimeRange:endISO}');
let Conn = WVDConnections
    | where TimeGenerated {TimeRange}
    | where _ResourceId in~ ({HostPools})
    | summarize Connected = countif(State == 'Connected') > 0, UserName = take_any(UserName),
        HostIp = take_anyif(tostring(column_ifexists('SessionHostIPAddress', '')), isnotempty(tostring(column_ifexists('SessionHostIPAddress', ''))))
        by CorrelationId;
let Errs = WVDErrors
    | where TimeGenerated {TimeRange}
    | where CodeSymbolic matches regex @'NETWORK_CODES'
    | summarize At = min(TimeGenerated), Code = take_any(CodeSymbolic) by CorrelationId
    | join kind=inner Conn on CorrelationId
    | extend Kind = iff(Connected, 'Dropped session', 'Failed connection');
let HostIps = Conn | where isnotempty(HostIp) | summarize by HostIp;
""".replace("NETWORK_CODES", NETWORK_CODES)

# The firewalls' metrics, one value per bin across the selected firewalls: the worst health, the highest SNAT port
# use and latency, the total throughput. Capacity is per firewall, so a change between bins is a scale operation.
FIREWALL = r"""let Metrics = union isfuzzy=true
        (datatable(TimeGenerated: datetime, _ResourceId: string, MetricName: string, Average: real, Maximum: real)[]),
        (AzureMetrics)
    | where TimeGenerated {TimeRange}
    | where tolower(_ResourceId) in~ ({Firewalls})
    | where MetricName in ('FirewallHealth', 'SNATPortUtilization', 'FirewallLatencyPng', 'ObservedCapacity', 'Throughput');
let Fw = Metrics
    | summarize Health = minif(Average, MetricName == 'FirewallHealth'), SnatPct = maxif(Maximum, MetricName == 'SNATPortUtilization'),
        LatencyMs = maxif(Average, MetricName == 'FirewallLatencyPng'), ThroughputMbps = sumif(Average, MetricName == 'Throughput') / 1000000
        by T = bin(TimeGenerated, Grain);
let CapChanges = Metrics
    | where MetricName == 'ObservedCapacity'
    | summarize Cap = round(max(Maximum)) by Firewall = tolower(_ResourceId), T = bin(TimeGenerated, Grain)
    | order by Firewall asc, T asc
    | extend Change = iff(prev(Firewall) == Firewall, Cap - prev(Cap), 0.0);
let CapBins = CapChanges
    | summarize Capacity = sum(Cap), ScaleOut = countif(Change >= 1), ScaleIn = countif(Change <= -1) by T;
let Rh = union isfuzzy=true (datatable(TimeGenerated: datetime, _ResourceId: string, CategoryValue: string)[]), (AzureActivity)
    | where TimeGenerated {TimeRange}
    | where CategoryValue =~ 'ResourceHealth'
    | where tolower(_ResourceId) in~ ({Firewalls});
let FwDenies = union isfuzzy=true
        (datatable(TimeGenerated: datetime, SourceIp: string, Action: string)[]),
        (AZFWNetworkRule), (AZFWApplicationRule)
    | where TimeGenerated {TimeRange}
    | where Action =~ 'Deny'
    | where SourceIp in (HostIps);
"""

# Every bin in the time range, with the disconnections (Y is the measure chosen at the top) and the firewall's state.
BINS = ERRS + FIREWALL + r"""let Bins = range T from Start to End step Grain
    | join kind=leftouter (Errs | summarize Drops = countif(Connected), FailedConnects = countif(not(Connected)),
        Users = dcount(UserName) by T = bin(At, Grain)) on T
    | join kind=leftouter Fw on T
    | join kind=leftouter CapBins on T
    | join kind=leftouter (Rh | summarize RhEvents = count() by T = bin(TimeGenerated, Grain)) on T
    | join kind=leftouter (FwDenies | summarize Denies = count() by T = bin(TimeGenerated, Grain)) on T
    | project T, Drops = coalesce(Drops, 0), FailedConnects = coalesce(FailedConnects, 0), Users = coalesce(Users, 0),
        Health, SnatPct, LatencyMs, ThroughputMbps, Capacity, ScaleOut = coalesce(ScaleOut, 0), ScaleIn = coalesce(ScaleIn, 0),
        RhEvents = coalesce(RhEvents, 0), Denies = coalesce(Denies, 0)
    | extend Y = case('{Measure}' == 'drops', Drops, '{Measure}' == 'failed', FailedConnects, Drops + FailedConnects);
"""

# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------

TILES_Q = BINS + r"""let Affected = toscalar(Errs | summarize dcount(UserName));
Bins
| summarize Drops = sum(Drops), Failed = sum(FailedConnects), Health = min(Health), Snat = max(SnatPct),
    ScaleOps = sum(ScaleOut) + sum(ScaleIn), ScaleOut = sum(ScaleOut), RhEvents = sum(RhEvents), Denies = sum(Denies),
    MetricBins = countif(isnotnull(Health) or isnotnull(SnatPct))
| extend rows = pack_array(
    pack('Signal', 'Dropped sessions', 'Value', Drops, 'Detail', strcat(Affected, ' users affected in all'), 'State', iff(Drops > 0, 'Degraded', 'Available')),
    pack('Signal', 'Failed connections', 'Value', Failed, 'Detail', 'network errors before connecting', 'State', iff(Failed > 0, 'Degraded', 'Available')),
    pack('Signal', 'Lowest firewall health', 'Value', round(Health), 'Detail', iff(MetricBins == 0, 'no firewall metrics (AzureMetrics)', '%'),
        'State', case(isnull(Health), 'Unknown', Health < 90, 'Unavailable', Health < 100, 'Degraded', 'Available')),
    pack('Signal', 'Peak SNAT port use', 'Value', round(Snat), 'Detail', '%',
        'State', case(isnull(Snat), 'Unknown', Snat >= 90, 'Unavailable', Snat >= 70, 'Degraded', 'Available')),
    pack('Signal', 'Scale operations', 'Value', ScaleOps, 'Detail', strcat(ScaleOut, ' out'), 'State', 'Unknown'),
    pack('Signal', 'Resource Health events', 'Value', RhEvents, 'Detail', 'on the firewalls', 'State', iff(RhEvents > 0, 'Degraded', 'Available')),
    pack('Signal', 'Denies from session hosts', 'Value', Denies, 'Detail', 'firewall rule logs', 'State', iff(Denies > 0, 'Degraded', 'Available')))
| mv-expand r = rows
| project Signal = tostring(r.Signal), Value = toreal(r.Value), Detail = tostring(r.Detail), State = tostring(r.State)
"""

# For each firewall signal: the bins where it was under stress (in that bin or the one before, since a session takes
# a minute or two to be declared dropped), the average disconnections in those bins against the rest, and the
# Pearson correlation of the signal's value with the disconnections, worked out from sums so that only bins with a
# value count.
SIGNALS_Q = BINS + r"""let LatMedian = toscalar(Bins | summarize percentile(LatencyMs, 50));
Bins
| order by T asc
| extend SnatNow = coalesce(SnatPct >= {SnatThreshold}, false), HealthNow = coalesce(Health < 100, false),
    LatNow = coalesce(LatencyMs >= 2 * LatMedian and LatencyMs >= 5, false), ScaleNow = ScaleOut + ScaleIn > 0,
    ScaleOutNow = ScaleOut > 0, RhNow = RhEvents > 0, DenyNow = Denies > 0
| extend rows = pack_array(
    pack('Signal', strcat('SNAT port use at or above ', {SnatThreshold}, '%'), 'Hit', SnatNow or coalesce(prev(SnatNow), false), 'Value', SnatPct),
    pack('Signal', 'Firewall health below 100%', 'Hit', HealthNow or coalesce(prev(HealthNow), false), 'Value', 100 - Health),
    pack('Signal', 'Latency probe at least twice its median', 'Hit', LatNow or coalesce(prev(LatNow), false), 'Value', LatencyMs),
    pack('Signal', 'Scale-out', 'Hit', ScaleOutNow or coalesce(prev(ScaleOutNow), false), 'Value', toreal(ScaleOut)),
    pack('Signal', 'Any scale operation (out or in)', 'Hit', ScaleNow or coalesce(prev(ScaleNow), false), 'Value', toreal(ScaleOut + ScaleIn)),
    pack('Signal', 'Resource Health event', 'Hit', RhNow or coalesce(prev(RhNow), false), 'Value', toreal(RhEvents)),
    pack('Signal', 'Firewall denies from session hosts', 'Hit', DenyNow or coalesce(prev(DenyNow), false), 'Value', toreal(Denies)),
    pack('Signal', 'Throughput (Mbps)', 'Hit', false, 'Value', ThroughputMbps))
| mv-expand r = rows
| extend Signal = tostring(r.Signal), Hit = tobool(r.Hit), x = toreal(r.Value), y = toreal(Y)
| summarize DataBins = countif(isnotnull(x)), BinsHit = countif(Hit), WithHit = avgif(y, Hit), Without = avgif(y, not(Hit) and isnotnull(x)),
    n = countif(isnotnull(x)), sx = sumif(x, isnotnull(x)), sy = sumif(y, isnotnull(x)), sxy = sumif(x * y, isnotnull(x)),
    sxx = sumif(x * x, isnotnull(x)), syy = sumif(y * y, isnotnull(x)) by Signal
| extend Pearson = round((n * sxy - sx * sy) / sqrt((n * sxx - sx * sx) * (n * syy - sy * sy)), 2),
    Ratio = round(iff(Without > 0, WithHit / Without, real(null)), 1)
| extend Verdict = case(DataBins == 0, 'No data for this signal',
    Signal startswith 'Throughput', iff(Pearson >= 0.5, 'Disconnections rise with load', 'No sign of a link'),
    BinsHit == 0, 'Did not happen in the time range',
    BinsHit >= 3 and (Ratio >= 2 or (Without == 0 and WithHit > 0)), 'Likely related',
    Ratio >= 1.3 or Pearson >= 0.3, 'Possibly related',
    'No sign of a link')
| project Signal, Verdict, BinsHit, DataBins, WithHit = round(WithHit, 2), Without = round(Without, 2), Ratio, Pearson
| order by case(Verdict == 'Likely related', 0, Verdict == 'Possibly related', 1, Verdict == 'Disconnections rise with load', 1, 2) asc, Ratio desc
"""

DROPS_CHART_Q = BINS + r"""Bins
| project T, ['Dropped sessions'] = Drops, ['Failed connections'] = FailedConnects
"""

SNAT_HEALTH_Q = BINS + r"""Bins
| project T, ['SNAT port use %'] = SnatPct, ['Health %'] = Health
"""

LATENCY_Q = BINS + r"""Bins
| project T, ['Latency probe (ms)'] = LatencyMs
"""

CAPACITY_Q = ERRS + FIREWALL + r"""CapChanges
| project T, Firewall = tostring(split(Firewall, '/')[8]), Cap
"""

THROUGHPUT_Q = BINS + r"""Bins
| project T, ['Throughput (Mbps)'] = ThroughputMbps, ['Users disconnected'] = Users
"""

# Bins where disconnections jumped: at least three, and three times the average bin. Alongside, the firewall's state
# in that bin and the one before, and the codes users got.
SPIKES_Q = BINS + r"""let AvgY = toscalar(Bins | summarize avg(Y));
let BinCodes = Errs | summarize Codes = strcat_array(make_set(Code, 4), ', ') by T = bin(At, Grain);
Bins
| order by T asc
| extend PrevSnat = prev(SnatPct), PrevHealth = prev(Health), PrevScale = prev(ScaleOut + ScaleIn)
| where Y >= 3 and Y >= 3 * AvgY
| join kind=leftouter BinCodes on T
| project Time = T, Disconnections = Y, Users, Health = round(min_of(coalesce(Health, 100.0), coalesce(PrevHealth, 100.0))),
    SnatPct = round(max_of(coalesce(SnatPct, 0.0), coalesce(PrevSnat, 0.0))), LatencyMs = round(LatencyMs, 1), Capacity,
    ScaleOps = ScaleOut + ScaleIn + coalesce(PrevScale, 0), RhEvents, Denies, Codes
| order by Disconnections desc
| take 100
"""

# Each scale operation and Resource Health event, with the disconnections in the 15 minutes before and after it.
EVENTS_Q = ERRS + FIREWALL + r"""let Events = union
    (CapChanges | where abs(Change) >= 1
        | project Time = T, Firewall, Event = strcat(iff(Change > 0, 'Scaled out to ', 'Scaled in to '), Cap, ' capacity units')),
    (Rh | extend Props = coalesce(column_ifexists('Properties_d', dynamic(null)), parse_json(tostring(column_ifexists('Properties', ''))))
        | project Time = TimeGenerated, Firewall = tolower(_ResourceId),
            Event = strcat('Resource Health: ', coalesce(tostring(Props.title), tostring(Props.currentHealthStatus), 'event'),
                iff(isnotempty(tostring(Props.cause)), strcat(' (', tostring(Props.cause), ')'), ''))));
let Window = 15m;
Events
| extend k = 1
| join kind=leftouter (Errs | project At, UserName, k = 1) on k
| summarize Before = countif(At >= Time - Window and At < Time), After = countif(At >= Time and At < Time + Window),
    UsersAfter = dcountif(UserName, At >= Time and At < Time + Window) by Time, Firewall, Event
| extend Firewall = tostring(split(Firewall, '/')[8]),
    Change = case(After >= 3 and After >= 2 * Before, 'Rose after', Before >= 3 and Before >= 2 * After, 'Rose before', 'No clear change')
| project Time, Firewall, Event, Before, After, UsersAfter, Change
| order by Time desc
"""

CODES_Q = ERRS + r"""Errs
| summarize Count = count(), Users = dcount(UserName), LastSeen = max(At) by Kind, Code
| order by Count desc
| take 30
"""

DENIES_Q = ERRS + r"""union isfuzzy=true
    (datatable(TimeGenerated: datetime, SourceIp: string, Action: string)[]),
    (AZFWNetworkRule | extend Table = 'Network rule'), (AZFWApplicationRule | extend Table = 'Application rule')
| where TimeGenerated {TimeRange}
| where Action =~ 'Deny'
| where SourceIp in (HostIps)
| extend Destination = coalesce(tostring(column_ifexists('Fqdn', '')), tostring(column_ifexists('DestinationIp', ''))),
    Port = tostring(column_ifexists('DestinationPort', '')), Protocol = tostring(column_ifexists('Protocol', '')),
    Rule = coalesce(tostring(column_ifexists('Rule', '')), tostring(column_ifexists('ActionReason', '')), 'default deny')
| summarize Count = count(), Hosts = dcount(SourceIp), FirstSeen = min(TimeGenerated), LastSeen = max(TimeGenerated)
    by Table, Destination, Port, Protocol, Rule
| order by Count desc
| take 100
"""

VERDICT = status_fmt("Verdict", good=["No sign of a link"], warn=["Possibly related", "Disconnections rise with load"],
                     bad=["Likely related"], neutral=["Did not happen in the time range", "No data for this signal"])

HOW_TO = """\
Pick the workspace, the **host pools** whose session hosts send their traffic through the firewall, and the
**firewalls** on that path. Each disconnection is a connection that hit a network error: a **dropped session** (the
user was connected) or a **failed connection** (they never got on; *ReverseConnect* codes are the session host
failing to reach the gateway, the leg that crosses the firewall). *Count* chooses which the comparison uses.

**Reading it.** *Does the firewall explain the disconnections?* is the answer. For each firewall signal it takes the
time bins where the signal was under stress (in that bin or the one before) and compares the average disconnections
in them with the rest. *Likely related* means at least three such bins with twice the usual disconnections or more.
*Correlation* is between -1 and 1: above about 0.3 the two move together. Then check *Disconnection spikes* and
*Scale operations and Resource Health events* to see whether the bad moments line up. A link is a lead, not proof:
the drops and the firewall's stress could both come from the same burst of users, such as the Monday morning sign-in.

Needs the host pools' diagnostic settings (`WVDConnections`, `WVDErrors`) and the firewalls' diagnostic setting with
**AllMetrics** (`AzureMetrics`) sent to the same workspace. The rule logs (`AZFWNetworkRule`, `AZFWApplicationRule`)
add the denies, and the activity log (`AzureActivity`) adds Resource Health events."""

WHAT_NEXT = """\
**If SNAT port use is the link.** Each session host holds a long-lived connection to a handful of Azure Virtual Desktop
gateway addresses on 443, and through the firewall these share its SNAT ports, which are limited per public IP and
instance. Add public IPs to the firewall, or send Azure Virtual Desktop traffic around it: Microsoft advises against
inspecting it, and a route on the session host subnets for the `WindowsVirtualDesktop` service tag with next hop
*Internet* takes it off the firewall (check this fits your routing intent first). RDP Shortpath (UDP) moves the session
itself off the gateway path.

**If scaling is the link.** The firewall adds capacity as load grows and takes several minutes to do it, so a sharp
morning ramp can outrun it. Look at whether *Scale-out* lines up with the start-of-day sign-in. If your firewall SKU and
region support it, set a minimum capacity (prescaling) to cover the peak.

**If health or latency is the link** with no scaling and normal SNAT use, raise it with Microsoft support, quoting the
times from *Disconnection spikes*. **If nothing lines up,** look past the firewall: the user's own network (the
*Azure Virtual Desktop: one user* workbook shows round-trip time per connection), the session hosts' load, or the
ExpressRoute or VPN path. The *Firewalls: blocked connections* workbook shows what any deny was."""


def parameters():
    return params(f"{P}-params", [
        subscription_param(P),
        workspace_param(P, "The workspace your host pools and firewalls send their logs and metrics to.", required=True),
        time_param(P, DAY_MS, (4 * HOUR_MS, 12 * HOUR_MS, DAY_MS, 3 * DAY_MS, 7 * DAY_MS, 14 * DAY_MS, 30 * DAY_MS)),
        resource_param("HostPools", "Host pools", Q_HOST_POOLS),
        resource_param("Firewalls", "Firewalls", Q_FIREWALLS),
        choice_param(P, "Grain", "Time bin", [("1m", "1 minute"), ("5m", "5 minutes"), ("15m", "15 minutes")], "5m",
                     "How finely to line the two up. Use 1 minute over a few hours, 15 minutes over a week or more."),
        choice_param(P, "Measure", "Count", [("both", "Dropped sessions and failed connections"),
                                             ("drops", "Dropped sessions only"), ("failed", "Failed connections only")],
                     "both", "Which disconnections the comparison counts."),
        choice_param(P, "SnatThreshold", "SNAT stress at", [("50", "50%"), ("70", "70%"), ("90", "90%")], "70",
                     "The SNAT port use that counts as stress."),
    ])


def workbook():
    return notebook([
        text(f"{P}-header", "# Azure Virtual Desktop disconnections and Azure Firewall\n"
             "Do users drop off Azure Virtual Desktop when the firewall is short of SNAT ports, unhealthy, slow or "
             "scaling? The disconnections and the firewall's signals on the same timeline, and how strongly each "
             "signal lines up with them."),
        parameters(),
        text(f"{P}-ws-hint", "Select the **Log Analytics workspace** your host pools and firewalls send to.", "info",
             visible_when=WORKSPACE_UNSET),
        text(f"{P}-howto", HOW_TO, "info", visible_when=WORKSPACE_SET),
        la(f"{P}-tiles", "", TILES_Q, vis="tiles", tiles=big_number_tiles("Signal", "State", "Value", "Detail")),
        la(f"{P}-signals", "Does the firewall explain the disconnections?", SIGNALS_Q,
           formatters=[VERDICT, low_is_good("Ratio", 1.3, 2, digits=1), low_is_good("Pearson", 0.3, 0.5, digits=2)],
           labels={"BinsHit": "Bins under stress", "DataBins": "Bins with data", "WithHit": "Disconnections per bin, under stress",
                   "Without": "Disconnections per bin, otherwise", "Ratio": "Times as many", "Pearson": "Correlation"},
           no_data="No data. Check the host pools and firewalls picked, and that the firewalls send AllMetrics."),
        la(f"{P}-drops", "Disconnections", DROPS_CHART_Q, vis="timechart", width=50),
        la(f"{P}-snat", "Firewall SNAT port use and health (%)", SNAT_HEALTH_Q, vis="timechart", width=50,
           no_data="No firewall metrics: send the firewalls' AllMetrics to this workspace."),
        la(f"{P}-capacity", "Firewall capacity units (a step is a scale operation)", CAPACITY_Q, vis="timechart", width=50,
           no_data="No ObservedCapacity metric from these firewalls."),
        la(f"{P}-latency", "Firewall latency probe (ms)", LATENCY_Q, vis="timechart", width=50),
        la(f"{P}-throughput", "Firewall throughput and users disconnected", THROUGHPUT_Q, vis="timechart"),
        la(f"{P}-spikes", "Disconnection spikes and the firewall at the time", SPIKES_Q,
           formatters=[high_is_good("Health", 100, 90), low_is_good("SnatPct", 70, 90),
                       low_is_good("ScaleOps", 1, 3), low_is_good("RhEvents", 1, 1), low_is_good("Denies", 1, 100)],
           labels={"Health": "Lowest health %", "SnatPct": "Peak SNAT %", "LatencyMs": "Latency (ms)",
                   "Capacity": "Capacity units", "ScaleOps": "Scale operations", "RhEvents": "Resource Health events",
                   "Codes": "Error codes"},
           no_data="No bin had at least three disconnections and three times the average."),
        la(f"{P}-events", "Scale operations and Resource Health events, and the disconnections either side (15 min)",
           EVENTS_Q, formatters=[status_fmt("Change", bad=["Rose after"], warn=["Rose before"], good=["No clear change"])],
           labels={"Before": "Disconnections before", "After": "Disconnections after", "UsersAfter": "Users after"},
           no_data="No scale operations or Resource Health events on these firewalls in the time range."),
        la(f"{P}-codes", "Disconnection error codes", CODES_Q, width=45,
           no_data="No network errors on these host pools in the time range."),
        la(f"{P}-denies", "Firewall denies from session hosts", DENIES_Q, width=55,
           no_data="No denies from the session hosts' addresses (or the AZFW rule logs are not in this workspace)."),
        text(f"{P}-next", WHAT_NEXT, "info", visible_when=WORKSPACE_SET),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
