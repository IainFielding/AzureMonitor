# DNS and private endpoints

*Reference for [dns-troubleshoot.workbook.json](../workbook/dns-troubleshoot.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

Why does this name not resolve, or resolve to the wrong address? Follows a Private Link name from the endpoint to its private DNS zone, the networks the zone is linked to, and the DNS server the client uses, then shows what the DNS servers actually answered.

It has 12 panels. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Name to resolve | The FQDN (or URL) that will not resolve, e.g. mystg.blob.core.windows.net. |
| Client IP | Optional. The private IP of the machine doing the lookup, to find its network and DNS servers. |
| DNS server | Optional. The DNS server the client uses, if not its network's. For a client on-premises, the address its forwarder sends to. |
| Log Analytics workspace | Optional. The workspace your firewalls, DNS security policies or DNS servers log to. |
| Time range | Applies to the DNS logs. |
| Zone | Which zone to include. |
| Ruleset | Which ruleset to include. |

## Panels

> Type the name that will not resolve, e.g. `mystg.blob.core.windows.net` (a URL works too). Add the **client IP**
> to see which DNS server the client uses and whether that server can see the private zone. For a client
> on-premises, or to follow a forwarder, put the DNS server's address in **DNS server** instead.
>
> **How a Private Link name resolves.** The public name (`mystg.blob.core.windows.net`) is a CNAME to the
> Private Link name (`mystg.privatelink.blob.core.windows.net`). Azure DNS answers that from a private DNS zone
> **only if the zone is linked to the virtual network the lookup is made from**; otherwise it carries on to public
> DNS and returns the public address. So check, in order:
> 1. **The endpoint:** approved, and with a DNS zone group, so its A record is written into the zone.
> 2. **The zone:** one copy of `privatelink.…` that holds the record. Two copies in different subscriptions each
>    answer only for the networks linked to them.
> 3. **The lookup network:** the zone is linked to the network the DNS server looks up from (the client's own
>    network for Azure-provided DNS; the resolver's network for a DNS Private Resolver; the firewall's for DNS proxy).
> 4. **On-premises:** a conditional forwarder for the public zone (`blob.core.windows.net`, not `privatelink.…`) to
>    a resolver inbound endpoint.

#### Private endpoints for this name

*Table · Azure Resource Graph*

Columns: Private endpoint, Should resolve to, Connection, DNS zone group, Provisioning, Target, Sub-resource, Virtual network, Subnet, Names it serves.

When there is nothing to show: *No private endpoint serves this name in the selected subscriptions. The name resolves publicly unless a zone holds a record for it by hand.*

#### Private DNS zones that can answer this name

*Table · Azure Resource Graph*

Columns: Zone, Answers for, Lookup network, Copies, Links, Record sets, Internet fallback, Resource Group, Subscription.

When there is nothing to show: *No private DNS zone in the selected subscriptions covers this name, so Azure DNS answers it from public DNS.*

> *Lookup network* says whether the zone is linked to a network that resolves for the client (fill in *Client IP*
> or *DNS server*). *Copies* above 1 means the same zone exists more than once: each copy answers only for the
> networks linked to it, so the record may be in one and the client's network linked to the other. *Internet
> fallback* (`NxDomainRedirect`) answers from public DNS when the private zone has no record, which hides a missing
> record. A Virtual WAN hub cannot be linked to a zone, so a secured hub firewall's DNS proxy must forward to a
> resolver.

#### Networks linked to those zones

*Table · Azure Resource Graph*

Columns: Zone, Virtual network, Resolves for the client, State, Auto-registration, Fallback, Provisioning.

When there is nothing to show: *The matching zones are not linked to any virtual network.*

### The client's DNS servers

#### DNS servers the client uses, and where each looks names up

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Client network, Subnet, DNS server, Server is, Resource, Looks up from, Then.

When there is nothing to show: *Enter a client IP or a DNS server. A client IP that is not in any virtual network in the selected subscriptions is probably on-premises: enter its DNS server instead.*

### Records in a zone

> Record sets are not in Resource Graph, so pick a zone to read its A records from Azure Resource Manager. The Private Link name needs an A record for the first label (e.g. `mystg`) pointing at the endpoint's address above.

#### A records

*Table · Azure Resource Manager*: `GET {Zone}/A`

Columns: Record, FQDN, Addresses, TTL, Auto-registered.

When there is nothing to show: *The zone has no A records.*

### DNS Private Resolver

#### Resolvers and their inbound endpoints

*Table · Azure Resource Graph*

Columns: Resolver, Virtual network, Inbound endpoint IPs, Outbound endpoints, State, Provisioning, Location.

When there is nothing to show: *No DNS Private Resolvers in the selected subscriptions.*

#### Forwarding rulesets

*Table · Azure Resource Graph*

Columns: Ruleset, Outbound endpoints of, Provisioning, Resource Group, Location.

When there is nothing to show: *No forwarding rulesets in the selected subscriptions.*

> A forwarding rule sends every name under its domain to the target servers instead of Azure DNS, so a rule for `windows.net.` or `.` stops the private zones being used for networks linked to the ruleset. Pick a ruleset to read its rules and links from Azure Resource Manager.

#### Forwarding rules

*Table · Azure Resource Manager*: `GET {Ruleset}/forwardingRules`

Columns: Rule, Domain, Target servers, State.

When there is nothing to show: *The ruleset has no rules.*

#### Networks linked to the ruleset

*Table · Azure Resource Manager*: `GET {Ruleset}/virtualNetworkLinks`

Columns: Link, Virtual network.

When there is nothing to show: *The ruleset is not linked to any network.*

### What the DNS servers answered

> Select a **Log Analytics workspace** to see the lookups your DNS servers logged.

> *Answered* reads **Public address** when the lookup succeeded but returned a public IP: the private zone was not
> used, so the request goes to the public endpoint (and is usually refused there). **NXDOMAIN** for the Private
> Link name means the zone was used but has no record: check the endpoint's DNS zone group. Sources: Azure Firewall
> DNS proxy (`AZFWDnsQuery`), DNS security policy (`DNSQueryLogs`), and Windows DNS servers (`DnsEvents`, or
> `ASimDnsActivityLogs` from the Windows DNS events connector). Azure-provided DNS logs nothing on its own: add a DNS
> security policy to the client network to see those lookups.

#### Lookups by server, name and answer

*Table · Log Analytics* · reads `AZFWDnsQuery`, `DNSQueryLogs`, `DnsEvents`, `ASimDnsActivityLogs`

When there is nothing to show: *No matching lookups. Widen the time range, clear Client IP, or check the DNS logs reach this workspace.*

#### Lookups over time by answer

*Time chart · Log Analytics* · reads `AZFWDnsQuery`, `DNSQueryLogs`, `DnsEvents`, `ASimDnsActivityLogs`

#### Lookups (latest 500)

*Table · Log Analytics* · reads `AZFWDnsQuery`, `DNSQueryLogs`, `DnsEvents`, `ASimDnsActivityLogs`

Columns: Time, Log, Server, Client, Query, Type, Answered, Answer, Detail.

When there is nothing to show: *No matching lookups.*
