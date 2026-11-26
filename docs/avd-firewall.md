# Azure Virtual Desktop disconnections and Azure Firewall

*Reference for [avd-firewall.workbook.json](../workbook/avd-firewall.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

Do users drop off Azure Virtual Desktop when the firewall is short of SNAT ports, unhealthy, slow or scaling? The disconnections and the firewall's signals on the same timeline, and how strongly each signal lines up with them.

It has 13 panels. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Log Analytics workspaces | Every workspace involved: the one your host pools send their diagnostics to and the one your firewalls send their logs and AllMetrics to, if different. Queries run across all of them. |
| Time range | The period the log and metric panels cover. |
| Host pools | Which host pools to include. |
| Firewalls | Which firewalls to include. |
| Time bin | How finely to line the two up. Use 1 minute over a few hours, 15 minutes over a week or more. |
| Count | Which disconnections the comparison counts. |
| SNAT stress at | The SNAT port use that counts as stress. |

## Panels

> Select the **Log Analytics workspaces** your host pools and your firewalls send to. If they are different, select both: every query runs across all the workspaces selected.

> Pick the workspaces (both, if the firewalls log to a different one from the host pools), the **host pools** whose session hosts send their traffic through the firewall, and the
> **firewalls** on that path. Each disconnection is a connection that hit a network error: a **dropped session** (the
> user was connected) or a **failed connection** (they never got on; *ReverseConnect* codes are the session host
> failing to reach the gateway, the leg that crosses the firewall). *Count* chooses which the comparison uses.
>
> **Reading it.** *Does the firewall explain the disconnections?* is the answer. For each firewall signal it takes the
> time bins where the signal was under stress (in that bin or the one before) and compares the average disconnections
> in them with the rest. *Likely related* means at least three such bins with twice the usual disconnections or more.
> *Correlation* is between -1 and 1: above about 0.3 the two move together. Then check *Disconnection spikes* and
> *Scale operations and Resource Health events* to see whether the bad moments line up. A link is a lead, not proof:
> the drops and the firewall's stress could both come from the same burst of users, such as the Monday morning sign-in.
>
> Needs the host pools' diagnostic settings (`WVDConnections`, `WVDErrors`) and the firewalls' diagnostic setting with
> **AllMetrics** (`AzureMetrics`) sent to one of the selected workspaces. The rule logs (`AZFWNetworkRule`, `AZFWApplicationRule`)
> add the denies, and the activity log (`AzureActivity`) adds Resource Health events.

#### Tiles

*Tiles · Log Analytics* · reads `WVDConnections`, `WVDErrors`, `AzureMetrics`, `AzureActivity`, `AZFWNetworkRule`, `AZFWApplicationRule`

#### Does the firewall explain the disconnections?

*Table · Log Analytics* · reads `WVDConnections`, `WVDErrors`, `AzureMetrics`, `AzureActivity`, `AZFWNetworkRule`, `AZFWApplicationRule`

Columns: Signal, Verdict, Bins under stress, Bins with data, Disconnections per bin, under stress, Disconnections per bin, otherwise, Times as many (under stress ÷ otherwise), Correlation.

When there is nothing to show: *No data. Check the host pools and firewalls picked, and that the firewalls send AllMetrics.*

> **Reading the table.** The time range is cut into bins (the *Time bin* at the top). A bin is *under stress* for a
> signal when the signal was bad in that bin or the one before. **Disconnections per bin, under stress** and
> **otherwise** are the average disconnections in those two sets of bins. **Times as many** divides the first by the
> second: 7 means users dropped seven times as often while that signal was bad. **Correlation** (-1 to 1) says whether
> the signal's value and the disconnections rise and fall together across every bin: above 0.3 is a link worth
> following, near 0 is none. **Likely related** needs at least three bins under stress with twice the usual
> disconnections. A signal that is bad in nearly every bin (*Too common to compare*) leaves no quiet time to compare
> against: fix or explain it first, then look again. The table needs the firewalls' **AllMetrics** (`AzureMetrics`)
> in one of the selected workspaces; the charts below do not.

#### Disconnections

*Time chart · Log Analytics* · reads `WVDConnections`, `WVDErrors`, `AzureMetrics`, `AzureActivity`, `AZFWNetworkRule`, `AZFWApplicationRule`

### The firewalls over the same time range
These charts read Azure Monitor metrics straight from the firewalls, so they work whatever the diagnostic settings. Line them up by eye with *Disconnections* above.

#### SNAT port use % (max)

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: SNATPortUtilization (max).

#### Health state %

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: FirewallHealth (average).

#### Capacity units (a step is a scale operation)

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: ObservedCapacity (max).

#### Latency probe (ms)

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: FirewallLatencyPng (average).

#### Throughput

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: Throughput (average).

#### Data processed

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: DataProcessed (sum).

#### Disconnection spikes and the firewall at the time

*Table · Log Analytics* · reads `WVDConnections`, `WVDErrors`, `AzureMetrics`, `AzureActivity`, `AZFWNetworkRule`, `AZFWApplicationRule`

Columns: Time, Disconnections, Users, Lowest health %, Peak SNAT %, Latency (ms), Capacity units, Scale operations, Resource Health events, Denies, Error codes.

When there is nothing to show: *No bin had at least three disconnections and three times the average.*

#### Scale operations and Resource Health events, and the disconnections either side (15 min)

*Table · Log Analytics* · reads `WVDConnections`, `WVDErrors`, `AzureMetrics`, `AzureActivity`, `AZFWNetworkRule`, `AZFWApplicationRule`

Columns: Time, Firewall, Event, Disconnections before, Disconnections after, Users after, Change.

When there is nothing to show: *No scale operations or Resource Health events on these firewalls in the time range.*

#### Disconnection error codes

*Table · Log Analytics* · reads `WVDConnections`, `WVDErrors`

When there is nothing to show: *No network errors on these host pools in the time range.*

#### Firewall denies from session hosts

*Table · Log Analytics* · reads `WVDConnections`, `WVDErrors`, `AZFWNetworkRule`, `AZFWApplicationRule`

When there is nothing to show: *No denies from the session hosts' addresses (or the AZFW rule logs are not in this workspace).*

> **If SNAT port use is the link.** Each session host holds a long-lived connection to a handful of Azure Virtual Desktop
> gateway addresses on 443, and through the firewall these share its SNAT ports, which are limited per public IP and
> instance. Add public IPs to the firewall, or send Azure Virtual Desktop traffic around it: Microsoft advises against
> inspecting it, and a route on the session host subnets for the `WindowsVirtualDesktop` service tag with next hop
> *Internet* takes it off the firewall (check this fits your routing intent first). RDP Shortpath (UDP) moves the session
> itself off the gateway path.
>
> **If scaling is the link.** The firewall adds capacity as load grows and takes several minutes to do it, so a sharp
> morning ramp can outrun it. Look at whether *Scale-out* lines up with the start-of-day sign-in. If your firewall SKU and
> region support it, set a minimum capacity (prescaling) to cover the peak.
>
> **If health or latency is the link** with no scaling and normal SNAT use, raise it with Microsoft support, quoting the
> times from *Disconnection spikes*. **If nothing lines up,** look past the firewall: the user's own network (the
> *Azure Virtual Desktop: one user* workbook shows round-trip time per connection), the session hosts' load, or the
> ExpressRoute or VPN path. The *Firewalls: blocked connections* workbook shows what any deny was.
