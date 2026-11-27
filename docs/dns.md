# DNS

*Reference for [dns.workbook.json](../workbook/dns.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

DNS across the estate: Azure Firewall DNS proxy, private DNS zones and their links, DNS Private Resolvers, forwarding rulesets and DNS security policies, the DNS servers each VNet uses, and what the DNS servers are answering. To follow one name, use the **DNS and private endpoints** workbook.

It has 51 panels across 7 tabs. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Log Analytics workspace | The workspace that receives the firewall, DNS security policy and DNS server logs. |
| Time range | For the DNS logs and zone metrics. |
| Name contains | Optional. Only lookups for names containing this. |
| Client IP | Optional. Only lookups from this address. |
| Zones to chart | Which zones to chart to include. |
| Ruleset | Pick a ruleset to see its rules and the VNets linked to it. |
| Watched forwarders | Forwarder addresses to follow, separated by commas. Cisco Umbrella / OpenDNS by default. |
| Internal suffixes | Optional. Your internal domains, separated by commas (contoso.local, corp.contoso.com). A name ending in one counts as internal, on top of what the servers answered from their own zones. |

## Tab: Overview

#### Tile proxy

*Tiles · Azure Resource Graph*

#### Tile zones

*Tiles · Azure Resource Graph*

#### Tile vnets

*Tiles · Azure Resource Graph*

#### Tile resolvers

*Tiles · Azure Resource Graph*

#### Tile pe

*Tiles · Azure Resource Graph*

> Select a **Log Analytics workspace** at the top for what the DNS servers are answering: Azure Firewall DNS proxy, DNS security policy and Windows DNS server logs.

#### Lookup tiles

*Tiles · Log Analytics* · reads `AZFWDnsQuery`, `DNSQueryLogs`, `DnsEvents`, `ASimDnsActivityLogs`

#### Azure Firewall DNS proxy

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: State, Firewall, Proxy, DNS proxy address, Deployment, Network, Forwards to, VNets using it, FQDN network rules, Findings, Rules from, Policy, Parent, Subscription, Resource group.

When there is nothing to show: *No Azure Firewalls in the selected subscriptions.*

#### Private DNS zone findings

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Finding, Zone, Kind, Copies, Record sets %, Links %, Subscription, Resource group.

When there is nothing to show: *No findings on the private DNS zones.*

#### VNets by kind of DNS server

*Pie chart · Azure Resource Graph*

#### DNS lookups by result

*Time chart · Log Analytics* · reads `AZFWDnsQuery`, `DNSQueryLogs`, `DnsEvents`, `ASimDnsActivityLogs`

## Tab: Firewall DNS proxy

#### Firewalls and their DNS proxy

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: State, Firewall, Proxy, DNS proxy address, Deployment, Network, Forwards to, VNets using it, FQDN network rules, Findings, Rules from, Policy, Parent, Subscription, Resource group.

When there is nothing to show: *No Azure Firewalls in the selected subscriptions.*

> **How DNS proxy works.** With DNS proxy on, the firewall listens on port 53 at its private address and forwards
> lookups to Azure DNS or to the custom servers in its policy. VNets use it by setting the firewall's private address
> (a secured hub's *private IP*) as their DNS server. It matters for two things:
> - **FQDN network rules.** A network rule that names an FQDN is resolved by the firewall itself, and only works with
>   DNS proxy on. Clients must use the proxy too, or they may get a different address from the one the rule allows
>   (common with CDN-backed names), and the connection is denied.
> - **Private DNS zones in Virtual WAN.** A Virtual WAN hub cannot be linked to a private DNS zone, so a secured hub
>   firewall that forwards to Azure DNS cannot resolve `privatelink` names. Forward to a **DNS Private Resolver inbound
>   endpoint** in a VNet linked to the zones instead.
>
> *Clients* counts VNets whose DNS servers include the firewall's address. FQDN rules include those inherited from
> a parent policy, and a child policy with no DNS settings of its own is shown with its parent's.

#### Where each DNS proxy forwards

*Table · Azure Resource Graph*

Columns: Firewall, Server, Kind, Owner, Looks up from, And then.

When there is nothing to show: *No firewall with DNS proxy on forwards to custom servers: they all use Azure DNS.*

### What the proxy is answering

> Select a **Log Analytics workspace** at the top for the firewalls' DNS query logs.

#### Fw tiles

*Tiles · Log Analytics* · reads `AZFWDnsQuery`

#### Proxy lookups by response code

*Time chart · Log Analytics* · reads `AZFWDnsQuery`

#### Answer time, milliseconds (p95 by firewall)

*Time chart · Log Analytics* · reads `AZFWDnsQuery`

#### By firewall

*Table · Log Analytics* · reads `AZFWDnsQuery`

Columns: Firewall, Lookups, Clients, Not NOERROR %, SERVFAIL, p50 ms, p95 ms, TCP %, Last.

When there is nothing to show: *No DNS proxy logs in the time range. Turn on the AZFWDnsQuery category (resource-specific) on the firewalls' diagnostic settings.*

#### Names the proxy did not resolve

*Table · Log Analytics* · reads `AZFWDnsQuery`

When there is nothing to show: *Every proxy lookup returned NOERROR.*

#### Busiest clients

*Table · Log Analytics* · reads `AZFWDnsQuery`

When there is nothing to show: *No proxy lookups.*

#### Slow names (p95 of 500 ms or more)

*Table · Log Analytics* · reads `AZFWDnsQuery`

When there is nothing to show: *No name took 500 ms or more at the 95th percentile.*

#### Proxy errors

*Table · Log Analytics* · reads `AZFWDnsQuery`

When there is nothing to show: *The proxy reported no errors.*

#### FQDN network rules the firewall cannot resolve

*Table · Log Analytics* · reads `AZFWInternalFqdnResolutionFailure`

When there is nothing to show: *No FQDN resolution failures, or the AZFWFqdnResolveFailure category is not collected.*

> From each firewall's diagnostic setting in **resource-specific** mode: *Azure Firewall DNS query* (`AZFWDnsQuery`) for
> every lookup the proxy answers, and *Azure Firewall FQDN Resolution Failure* (`AZFWInternalFqdnResolutionFailure`)
> for FQDN network rules it cannot resolve. *Not NOERROR* includes NXDOMAIN, which is normal in small numbers (a client
> trying its DNS suffixes, an AAAA lookup for a name with no IPv6 address). SERVFAIL and proxy errors mean the server
> the proxy forwards to did not answer: check it is up and that the firewall can reach it on port 53. A high share of
> TCP lookups is usually large answers being truncated over UDP.

## Tab: Private DNS zones

#### Private DNS zones

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Zone, Kind, Record sets, Record sets % of limit, Links, Links % of limit, Auto-registration links, Copies, Findings, Subscription, Resource group.

When there is nothing to show: *No private DNS zones in the selected subscriptions.*

> In a landing zone, each Private Link zone (`privatelink.blob.core.windows.net` and so on) should exist **once**, in
> the connectivity subscription, linked to the VNet of the DNS Private Resolver (and any other VNet that resolves with
> Azure DNS directly), with records added by each private endpoint's DNS zone group (usually through Azure Policy). A
> second copy of a zone, or one in a landing zone subscription, answers only the VNets linked to it, and those VNets
> then cannot see the records in the central copy. The central subscription is taken to be the one with the most
> Private Link zones. *Internet fallback* on a link (resolution policy *NxDomainRedirect*) sends names the zone does not
> hold to public DNS, which avoids failures for resources without a private endpoint.

#### Virtual network links

*Table · Azure Resource Graph*

Columns: Zone, Link, VNet, State, Registration, Names the zone does not hold, Problem, Provisioning, Zone resource.

When there is nothing to show: *No virtual network links.*

#### Private endpoints with no DNS zone group

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Private endpoint, Target, Sub-resource, Names it needs, subscription Id, Resource group.

When there is nothing to show: *Every private endpoint has a DNS zone group.*

> Nothing registers these endpoints' addresses in the central zones, so their names resolve to the public address unless someone keeps the records by hand. Add a zone group (or let the landing zone's *Deploy-Private-DNS-Zones* policies do it).

#### Queries answered per zone

*Chart · Azure Monitor metrics* of `microsoft.network/privatednszones`: QueryVolume (sum).

#### Record sets, % of limit

*Chart · Azure Monitor metrics* of `microsoft.network/privatednszones`: RecordSetCapacityUtilization (max).

## Tab: Resolvers & policies

#### DNS Private Resolvers

*Table · Azure Resource Graph*

Columns: Resolver, VNet, Inbound endpoint addresses, Outbound endpoints, State, Provisioning, Location.

When there is nothing to show: *No DNS Private Resolvers in the selected subscriptions.*

> **DNS Private Resolver** answers on its *inbound endpoints* (the address on-premises conditional forwarders and
> secured hub firewalls forward to) with Azure DNS from its own VNet, so it sees the private DNS zones linked there.
> *Outbound endpoints* with a **forwarding ruleset** send chosen domains elsewhere, usually on-premises domain
> controllers; a ruleset acts for every VNet linked to it. A **DNS security policy** filters lookups made through Azure
> DNS in the VNets linked to it, against domain lists, and logs them to `DNSQueryLogs`.

#### Forwarding rulesets

*Table · Azure Resource Graph*

Columns: Ruleset, Resolvers (outbound endpoints), Provisioning, Resource Group, Location.

When there is nothing to show: *No forwarding rulesets.*

#### Forwarding rules

*Table · Azure Resource Manager*: `GET {Ruleset}/forwardingRules`

Columns: Rule, Domain, Targets, State.

When there is nothing to show: *The ruleset has no rules.*

#### VNets linked to the ruleset

*Table · Azure Resource Manager*: `GET {Ruleset}/virtualNetworkLinks`

Columns: Link, VNet, Provisioning.

When there is nothing to show: *No VNets are linked to this ruleset.*

### DNS security policies

#### DNS security policies and domain lists

*Table · Azure Resource Graph*

Columns: Kind, Resource, Domains, Provisioning, Resource group, Location.

When there is nothing to show: *No DNS security policies or domain lists.*

#### Lookups a DNS security policy blocked or alerted on

*Table · Log Analytics* · reads `DNSQueryLogs`

When there is nothing to show: *No lookups blocked or alerted on in the time range, or no DNS security policy logs here.*

## Tab: VNet DNS settings

#### VNets by kind of DNS server

*Pie chart · Azure Resource Graph*

> Every VM gets its DNS servers from its VNet (or its NIC, which overrides the VNet) when it starts or renews its
> lease, so a change reaches running VMs only after a restart or `ipconfig /renew`. In a landing zone, spokes usually
> point at the central resolution service: the secured hub firewall's DNS proxy, or a DNS Private Resolver inbound
> endpoint. *Azure-provided DNS* (168.63.129.16) resolves only the private DNS zones linked to that VNet itself.
> *Mixed* servers (say a firewall and an on-premises server) are used in no fixed order, so clients can get different
> answers for the same name.

#### DNS servers each VNet hands out

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Finding, VNet, Kind of server, DNS servers, Subscription, Resource group.

When there is nothing to show: *No VNets in the selected subscriptions.*

#### NICs with their own DNS servers (overriding the VNet)

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: VM (or NIC), NIC, DNS servers, VNet, subscription Id, Resource group.

When there is nothing to show: *No NIC overrides its VNet's DNS servers.*

## Tab: Queries

> Select a **Log Analytics workspace** at the top for what the DNS servers are answering: Azure Firewall DNS proxy, DNS security policy and Windows DNS server logs.

> Lookups from every DNS log in the workspace, in one shape: Azure Firewall DNS proxy (`AZFWDnsQuery`), DNS security
> policy (`DNSQueryLogs`), and Windows DNS servers (`DnsEvents` from DNS Analytics, or `ASimDnsActivityLogs`). Lookups
> made straight to Azure DNS from a VNet with no DNS security policy are not logged anywhere. Filter with **Name** and
> **Client IP** at the top. For one name, the **DNS and private endpoints** workbook works out which zone, record and
> server should answer it.

#### Q tiles

*Tiles · Log Analytics* · reads `AZFWDnsQuery`, `DNSQueryLogs`, `DnsEvents`, `ASimDnsActivityLogs`

#### Lookups by result

*Time chart · Log Analytics* · reads `AZFWDnsQuery`, `DNSQueryLogs`, `DnsEvents`, `ASimDnsActivityLogs`

#### By log and server

*Table · Log Analytics* · reads `AZFWDnsQuery`, `DNSQueryLogs`, `DnsEvents`, `ASimDnsActivityLogs`

When there is nothing to show: *No DNS logs in the time range.*

#### Private Link names that do not exist (NXDOMAIN)

*Table · Log Analytics* · reads `AZFWDnsQuery`, `DNSQueryLogs`, `DnsEvents`, `ASimDnsActivityLogs`

When there is nothing to show: *No privatelink name returned NXDOMAIN.*

> An NXDOMAIN for a `privatelink` name means the zone exists but holds no record for it: the private endpoint has no DNS zone group, the record was deleted, or the endpoint is gone and something still uses the name. Look the name up in the **DNS and private endpoints** workbook.

#### Names that failed

*Table · Log Analytics* · reads `AZFWDnsQuery`, `DNSQueryLogs`, `DnsEvents`, `ASimDnsActivityLogs`

When there is nothing to show: *Every lookup returned NOERROR.*

#### Busiest clients

*Table · Log Analytics* · reads `AZFWDnsQuery`, `DNSQueryLogs`, `DnsEvents`, `ASimDnsActivityLogs`

When there is nothing to show: *No lookups.*

## Tab: Windows DNS servers

> Select a **Log Analytics workspace** at the top for what the DNS servers are answering: Azure Firewall DNS proxy, DNS security policy and Windows DNS server logs.

> What the Windows DNS servers (the domain controllers) are doing, from their query events. **Internal** lookups are
> answered from a zone the server holds, such as the AD domain. **External** lookups are forwarded to another server.
> Each name a server forwards is counted, with where it went. List the **Watched forwarders** (by default the
> Cisco Umbrella / OpenDNS resolvers) to see exactly which names go to them, and which clients asked for them.
>
> The query events come from the DNS server's analytical log (event IDs 256 to 262). They reach the workspace in one
> of these ways:
>
> - Sentinel's **Windows DNS Events via AMA** connector (`ASimDnsActivityLogs`).
> - `Microsoft-Windows-DNSServer` events in `Event` or `WindowsEvent`.
> - The retired DNS Analytics solution (`DnsEvents`). This gives lookups only, so it can't show forwarding. Use
>   **Internal suffixes** to split those lookups.
>
> The **DNS Server** event log (event 4013 and the like) and the Audit log record server and zone changes, not
> lookups. The first table shows which of these logs this workspace holds.

#### DNS server logs in this workspace

*Table · Log Analytics* · reads `ASimDnsActivityLogs`, `Event`, `DnsEvents`, `Usage`

Columns: Table, Detail, Events, Servers, Last, Event Id.

When there is nothing to show: *No DNS server logs in the time range.*

#### Windns tiles

*Tiles · Log Analytics* · reads `ASimDnsActivityLogs`, `Event`, `DnsEvents`

#### How lookups were answered

*Time chart · Log Analytics* · reads `ASimDnsActivityLogs`, `Event`, `DnsEvents`

#### Internal and external

*Pie chart · Log Analytics* · reads `ASimDnsActivityLogs`, `Event`, `DnsEvents`

#### Where the DNS servers forward

*Table · Log Analytics* · reads `ASimDnsActivityLogs`, `Event`, `DnsEvents`

When there is nothing to show: *No forwarding events (260). DnsEvents and the DNS Server event log don't record forwarding.*

#### Internal: zones the DNS servers answered from

*Table · Log Analytics* · reads `ASimDnsActivityLogs`, `Event`, `DnsEvents`

When there is nothing to show: *No lookups answered from the servers' own zones.*

#### External: domains the DNS servers forwarded

*Table · Log Analytics* · reads `ASimDnsActivityLogs`, `Event`, `DnsEvents`

When there is nothing to show: *No forwarded names.*

#### Names sent to the watched forwarders

*Table · Log Analytics* · reads `ASimDnsActivityLogs`, `Event`, `DnsEvents`

When there is nothing to show: *Nothing was forwarded to the watched forwarders.*

#### Clients behind those names

*Table · Log Analytics* · reads `ASimDnsActivityLogs`, `Event`, `DnsEvents`

When there is nothing to show: *No client lookups (256) match names sent to the watched forwarders.*

> Port 53 connections straight to a watched forwarder, from Azure Firewall's network rule log (`AZFWNetworkRule`). The
> DNS servers sending their forwards should be the only sources. Any other source is a client that bypasses them,
> through its own DNS settings or a hard-coded resolver. Each of these connections, like each forward, takes a SNAT
> port on the firewall. The **Azure Firewall** workbook's **Sources by destination** tab breaks them down further.

#### Port 53 to the watched forwarders through Azure Firewall

*Table · Log Analytics* · reads `ASimDnsActivityLogs`, `Event`, `DnsEvents`, `AZFWNetworkRule`

Columns: Source, Is it a DNS server?, Connections, Denied, Destination, Firewalls, Last.

When there is nothing to show: *No port 53 connections to the watched forwarders in AZFWNetworkRule.*
