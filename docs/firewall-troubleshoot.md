# Firewalls: blocked connections

*Reference for [firewall-troubleshoot.workbook.json](../workbook/firewall-troubleshoot.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

Is a firewall blocking this connection, and which rule did it? Covers Azure Firewall (network, application and DNAT rules, threat intelligence and IDPS), Palo Alto, Check Point and NSGs, and shows where along the path a flow stops.

It has 16 panels. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | Where to look for workspaces to pick from. |
| Log Analytics workspace | The workspace (or workspaces) the firewalls log to. |
| Time range | The period the log and metric panels cover. |
| Platforms | Leave empty for all. NSG is the network security group decision from VNet flow logs. |
| Firewalls | Firewalls that logged in the time range. Leave empty for all of them. |
| Source IP / CIDR | Optional. One or more IPs or CIDR ranges, separated by commas, e.g. 10.1.0.4, 10.2.0.0/16. |
| Destination IP / CIDR / FQDN | Optional. IPs, CIDR ranges or FQDNs, separated by commas. FQDNs match as whole words, so contoso.com matches www.contoso.com. |
| Destination port | Optional. Ports and ranges separated by commas, e.g. 443, 1433, 11000-11999. |
| Match hops on | How *Path through the firewalls* lines up one flow across firewalls. If Azure Firewall SNATs traffic before the Palo Alto or Check Point, the source changes between hops: match on destination and port only. |
| Show | Filters the tiles, timeline, rules, top lists and events. The path, no-reply and verdict panels always use both, since they compare allowed and blocked. |
| Managed instances | Which managed instances to include. |

## Panels

> Select the **Log Analytics workspace** your firewalls log to.

> Fill in whatever you know about the connection (source, destination, port) and leave the rest empty.
> Each box takes a comma-separated list (ports also take ranges, e.g. `11000-11999`), and an empty box matches
> everything, so with nothing filled in you see everything blocked in the time range. If traffic crosses more than one firewall (say a Palo Alto
> behind an Azure Firewall), *Verdict per flow* shows what each one decided.
>
> **Azure Firewall.** Threat intelligence and IDPS are checked first and can drop traffic before any rule runs.
> Then DNAT rules, then network rules, then application rules (HTTP, HTTPS and MSSQL only). Traffic that matches no
> rule is denied, and shows as *(no rule matched: default deny)*: add an allow rule.
>
> **Palo Alto and Check Point.** The rule column is the rule that matched: Palo Alto's `interzone-default`, or
> Check Point's cleanup rule, means nothing allowed it. Palo Alto threat logs (antivirus, vulnerability, URL
> filtering) show as *Palo Alto threat*; Check Point blades show under their product name (IPS, Application Control).
>
> **NSG.** Network security group decisions come from VNet flow logs with Traffic Analytics
> (`NTANetAnalytics`). An NSG deny never shows in a firewall's log, so this is the last hop before the destination.
>
> **Nothing shows up?** Set *Show* to *Blocked and allowed*. If the flow is not logged at all, it never reached the
> firewall (check the route table on the source subnet, or vWAN routing intent), or its logs are not reaching this
> workspace: Azure Firewall needs a diagnostic setting sending the resource-specific `AZFW*` tables, and Palo Alto
> and Check Point need to send CEF (`CommonSecurityLog`), with logging turned on for the rule. Azure Firewall flow
> trace logs (`AZFWFlowTrace`) are optional and add Azure Firewall to the out-of-state check. Plain syslog and the
> older Azure Firewall `AzureDiagnostics` format are not read here.

#### Events by verdict and log source

*Tiles · Log Analytics* · reads `AZFWNetworkRule`, `AZFWApplicationRule`, `AZFWNatRule`, `AZFWThreatIntel`, `AZFWIdpsSignature`, `CommonSecurityLog`, `NTANetAnalytics`

When there is nothing to show: *No matching firewall events. Try *Blocked and allowed*, a longer time range, or fewer filters.*

#### Path through the firewalls: where does each flow stop?

*Table · Log Analytics* · reads `AZFWNetworkRule`, `AZFWApplicationRule`, `AZFWNatRule`, `AZFWThreatIntel`, `AZFWIdpsSignature`, `CommonSecurityLog`, `NTANetAnalytics`

Columns: Source IP, Destination, Port, Stopped at, Azure Firewall, Azure Firewall rule, Azure Firewall resource, Palo Alto, Palo Alto rule, Check Point, Check Point rule, NSG, NSG rule, NSG resource, Devices, Last seen.

When there is nothing to show: *No matching flows. Try a longer time range or fewer filters.*

> **Reading the path.** Each row is one flow, with what each hop did in path order: Azure Firewall, Palo Alto or
> Check Point, then the NSG (from VNet flow logs). *Stopped at* names the first hop that blocked it.
> - **Asymmetric routing:** the Palo Alto or Check Point dropped packets that did not start a session. The request
>   went one way and the reply came back another, so this firewall saw only half of the conversation. Check the
>   route tables on both sides, including the destination subnet's route back to the source.
> - **No reply from the destination:** every hop allowed it, but no TCP session got a byte back. The reply took
>   another path, or the destination is not listening. See *Allowed but no reply* below.
> - **Passed Azure Firewall, not seen at Palo Alto or Check Point:** the next hop never logged it. Check the route
>   from the Azure Firewall subnet to the NVA, or the NVA's logging for that rule. If Azure Firewall SNATs this
>   traffic, set *Match hops on* to *Destination and port*.
> - **Not seen at Azure Firewall:** the flow reached an NVA without going through Azure Firewall (check routing), or
>   the source was translated before it got there.
> - **Allowed everywhere it was logged:** look past the network: the host firewall, the service itself, DNS or
>   authentication.
>
> *No reply* needs byte counts, which Palo Alto, Check Point and VNet flow logs carry and Azure Firewall rule logs
> do not. Azure Firewall application rules log only the FQDN, so to follow web traffic put both the FQDN and the IP
> in *Destination*.

#### Allowed but no reply, and out-of-state drops (return path problems)

*Table · Log Analytics* · reads `AZFWNetworkRule`, `AZFWApplicationRule`, `AZFWNatRule`, `AZFWThreatIntel`, `AZFWIdpsSignature`, `CommonSecurityLog`, `NTANetAnalytics`, `AZFWFlowTrace`

Columns: Time Generated, Platform, Firewall, Device Id, Verdict, Blocked, Source, Action, Source IP, Source Port, Destination, Destination Ip, Port, Protocol, Target Url, Policy, Rule Collection Group, Rule Collection, Rule Name, Reason, Reply Bytes, Not Syn.

When there is nothing to show: *No unanswered sessions or out-of-state drops. Azure Firewall needs flow trace logs (AZFWFlowTrace) turned on to appear here: see *Azure Firewall logging* below.*

#### Azure Firewall logging: rule logs and flow trace, per firewall

*Table · Log Analytics* · reads `AZFWNetworkRule`

Columns: Azure Firewall, Rule logs, Flow trace, Flow trace records, Invalid packets, Last flow trace, Last rule log.

When there is nothing to show: *No Azure Firewalls in the selected subscriptions.*

> **Off** means the firewall's rule logs reach this workspace but no flow trace records do. Flow trace needs both:
> 1. **AZFWFlowTrace** ticked in the firewall's diagnostic setting (resource-specific mode), and
> 2. flow trace enabled for the subscription: `Register-AzProviderFeature -FeatureName AFWEnableTcpConnectionLogging
>    -ProviderNamespace Microsoft.Network`, then `Register-AzResourceProvider -ProviderNamespace Microsoft.Network`.
>    Registration can take a while to apply.
>
> Flow trace logs every SYN-ACK, FIN, RST and invalid packet, so they are high-volume and add ingestion cost. Many
> teams turn them on while troubleshooting and off again afterwards. **Unknown** means the firewall sends no rule
> logs to this workspace either; it may log to another workspace, or have no diagnostic setting.

### Show timeline, verdict per flow, rules and top talkers (loads when asked)

#### Events over time

*Time chart · Log Analytics* · reads `AZFWNetworkRule`, `AZFWApplicationRule`, `AZFWNatRule`, `AZFWThreatIntel`, `AZFWIdpsSignature`, `CommonSecurityLog`, `NTANetAnalytics`

#### Verdict per flow (latest decision by each firewall, blocked and allowed)

*Table · Log Analytics* · reads `AZFWNetworkRule`, `AZFWApplicationRule`, `AZFWNatRule`, `AZFWThreatIntel`, `AZFWIdpsSignature`, `CommonSecurityLog`, `NTANetAnalytics`

Columns: Last seen, Source IP, Destination, Port, Protocol, Firewall, Azure resource, Blocked, Allowed, Last action, Decided by, Rule, Reason, First seen.

When there is nothing to show: *No matching flows.*

#### Rules that matched

*Table · Log Analytics* · reads `AZFWNetworkRule`, `AZFWApplicationRule`, `AZFWNatRule`, `AZFWThreatIntel`, `AZFWIdpsSignature`, `CommonSecurityLog`, `NTANetAnalytics`

Columns: Time Generated, Platform, Device, Device Id, Verdict, Blocked, Log, Action, Source Ip, Source Port, Destination, Destination Ip, Destination Port, Protocol, Target Url, Policy, Rule collection group, Rule collection / layer, Rule, Reason, Reply Bytes, Not Syn.

When there is nothing to show: *No matching rule hits.*

#### Top source IPs

*Table · Log Analytics* · reads `AZFWNetworkRule`, `AZFWApplicationRule`, `AZFWNatRule`, `AZFWThreatIntel`, `AZFWIdpsSignature`, `CommonSecurityLog`, `NTANetAnalytics`

Columns: Time Generated, Platform, Device, Device Id, Verdict, Blocked, Source, Action, Source IP, Source Port, Destination, Destination Ip, Destination Port, Protocol, Target Url, Policy, Rule Collection Group, Rule Collection, Rule Name, Reason, Reply Bytes, Not Syn.

#### Top destinations

*Table · Log Analytics* · reads `AZFWNetworkRule`, `AZFWApplicationRule`, `AZFWNatRule`, `AZFWThreatIntel`, `AZFWIdpsSignature`, `CommonSecurityLog`, `NTANetAnalytics`

Columns: Time Generated, Platform, Device, Device Id, Verdict, Blocked, Source, Action, Source Ip, Source Port, Destination, Destination Ip, Destination Port, Protocol, Target Url, Policy, Rule Collection Group, Rule Collection, Rule Name, Reason, Reply Bytes, Not Syn.

#### Events (latest 500)

*Table · Log Analytics* · reads `AZFWNetworkRule`, `AZFWApplicationRule`, `AZFWNatRule`, `AZFWThreatIntel`, `AZFWIdpsSignature`, `CommonSecurityLog`, `NTANetAnalytics`

Columns: Time, Verdict, Firewall, Azure resource, Log, Action, Source IP, Source port, Destination, Port, Protocol, URL, Policy, Rule collection group, Rule collection / layer, Rule, Reason.

When there is nothing to show: *No matching events.*

### DNS (Azure Firewall)
A name that does not resolve looks like a block from the client. These need DNS proxy on the firewall policy.

#### Failing DNS proxy queries

*Table · Log Analytics* · reads `AZFWDnsQuery`

When there is nothing to show: *No failing DNS queries (or DNS proxy logs are not enabled).*

#### FQDNs in network rules that failed to resolve

*Table · Log Analytics* · reads `AZFWInternalFqdnResolutionFailure`

When there is nothing to show: *No FQDN resolution failures.*

### Show SQL Managed Instance checks (loads when asked)

### SQL Managed Instance checks
Configuration that commonly breaks connectivity to a managed instance: connection type and ports, routes and NSG rules on its subnet, and what changed.

> Connection type decides the ports: **Proxy** uses 1433 only. **Redirect** connects on 1433, then sends the client
> straight to the instance's node on **11000-11999**, so every firewall and NSG on the way must allow both, to the
> whole instance subnet rather than one IP. The public endpoint uses **3342**. To check the path above, put the
> instance subnet in *Destination* and `1433, 11000-11999` in *Destination port*.

#### Managed instances

*Table · Azure Resource Graph*

Columns: Instance, State, Connection type, Ports to allow, FQDN, Subnet, Subnet range, Route table, NSG, Public endpoint, Minimum TLS.

When there is nothing to show: *No managed instances in the selected subscriptions.*

#### Routes on the instance subnet

*Table · Azure Resource Graph*

Columns: Instance, Route table, Route, Prefix, Next hop, Next hop IP, Check.

When there is nothing to show: *No route table on the instance subnet.*

#### NSG rules on the instance subnet covering SQL ports

*Table · Azure Resource Graph*

Columns: Instance, NSG, Direction, Priority, Rule, Access, Source, Destination, Ports, SQL ports covered.

When there is nothing to show: *No custom NSG rules cover 1433, 11000-11999 or 3342: the default rules apply (virtual network traffic allowed, internet inbound denied).*

#### Changes to the instance, its network, route table and NSG (time range, up to 14 days)

*Table · Azure Resource Graph* · reads `resourcechanges`

Columns: Time, Resource, Type, Change, Properties, Changed by, Client, Operation.

When there is nothing to show: *No changes in the time range. Widen it (Resource Graph keeps 14 days).*
