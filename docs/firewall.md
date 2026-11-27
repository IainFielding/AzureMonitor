# Azure Firewall

*Reference for [firewall.workbook.json](../workbook/firewall.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

Every Azure Firewall: how it is built and reaches the internet, how healthy and busy it is, why it runs short of SNAT ports and who is taking them, its policies, and the traffic it denies or flags.

It has 22 panels across 5 tabs. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Firewalls | Which firewalls to include. |
| Log Analytics workspace | The workspace that receives the firewall logs (resource-specific AZFW* tables). |
| Time range | For the metrics and logs. |

## Tab: Overview

#### Tiles

*Tiles · Azure Resource Graph*

#### Key metrics over the time range

*Table, one row per resource · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: Health % (average); Max SNAT % (max); Observed capacity units (max) (max); Avg throughput (average); Latency probe (ms) (average).

#### Firewalls

*Table · Azure Resource Graph*

Columns: Firewall, Tier, Hub, Policy, Zones, Public IPs, Outbound through, Private IP, Provisioning, Resource group, Location.

When there is nothing to show: *No Azure Firewalls found.*

> Running short of SNAT ports? Start on the **SNAT ports** tab. For a connection the firewall blocks, use the **Firewalls: blocked connections** workbook.

## Tab: SNAT ports

### SNAT ports
Every outbound connection the firewall translates to a public IP takes a **SNAT port**. Azure Firewall has 2,496
ports per public IP per instance, and a port can be reused only for a *different* destination IP and port. So
ports usually run out because many connections go to **one destination** (a storage or API endpoint, an external DNS
server) faster than ports are freed, rather than because of total traffic. When they run out, new connections fail
while existing ones carry on. Work down the page: is the firewall built with enough ports, when did use peak, and
which destinations and sources were taking them at the time.

#### SNAT capacity and settings by firewall

*Table · Azure Resource Graph*

Columns: Firewall, Hub, Outbound through, Firewall public IPs, NAT gateway IPs, NAT gateway prefixes, SNAT ports per instance, NAT gateway SNAT ports, Not SNATed (private ranges), What to do.

When there is nothing to show: *No Azure Firewalls selected.*

#### SNAT port use % by protocol (max)

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: SNATPortUtilization (max, split by Protocol).

#### Observed capacity units (max): did scale-out keep up?

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: ObservedCapacity (max).

> Select a **Log Analytics workspace** at the top for what the firewall logs show (needs the resource-specific firewall logs, such as `AZFWNetworkRule` and `AZFWApplicationRule`).

#### New outbound connections taking SNAT ports, by protocol

*Time chart · Log Analytics* · reads `AZFWNetworkRule`, `AZFWApplicationRule`

When there is nothing to show: *No allowed outbound connections logged (or the structured firewall logs are not enabled).*

#### Destinations taking the most connections (ports run out per destination)

*Table · Log Analytics* · reads `AZFWNetworkRule`, `AZFWApplicationRule`

When there is nothing to show: *No outbound connections to public destinations.*

#### Sources opening the most outbound connections

*Table · Log Analytics* · reads `AZFWNetworkRule`, `AZFWApplicationRule`

When there is nothing to show: *No outbound connections to public destinations.*

#### Busiest minutes (select one to see who was connecting)

*Table · Log Analytics* · reads `AZFWNetworkRule`, `AZFWApplicationRule`

When there is nothing to show: *No outbound connections to public destinations.*

#### Connections in the selected minute

*Table · Log Analytics* · reads `AZFWNetworkRule`, `AZFWApplicationRule`

> The logs record each **new** connection, so these panels show how fast ports are taken, not how many are held; a
> port stays taken for a while after its connection closes. Line the busiest minutes up with the SNAT chart above.
> Application rule rows name the FQDN rather than the address it resolved to. To find what a source address is, use
> the **Routing** workbook.

> **What to do, in order of effect**
> 1. **Hub VNet firewall: associate a NAT gateway with `AzureFirewallSubnet`.** Outbound then uses the NAT gateway's
>    64,512 ports per public IP (up to 16 addresses, or a prefix) instead of 2,496 per IP per instance. A firewall in a
>    Virtual WAN secured hub cannot use a NAT gateway: add public IPs to it instead (up to 250).
> 2. **Stop SNATing what does not need it.** With private ranges set to `255.255.255.255/32`, traffic to private
>    addresses takes ports too. Reach Azure PaaS services through private endpoints rather than their public addresses.
> 3. **Fix the heaviest destination.** Where one destination takes most connections, the client is usually opening a
>    new connection per request: reuse connections (HTTP keep-alive, connection pooling, one shared HTTP client). For
>    DNS, use the firewall's DNS proxy or Azure DNS rather than an external resolver.
> 4. **Scale out ahead of known peaks.** Each extra instance brings its own ports, but scaling out takes minutes, so a
>    sudden burst can exhaust ports first. If *Observed capacity* stays flat while SNAT use climbs, the burst outran
>    scale-out.

## Tab: Health & capacity

#### Health state %

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: FirewallHealth (average).

#### Latency probe (ms)

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: FirewallLatencyPng (average).

#### Throughput

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: Throughput (average).

#### Observed capacity units (max)

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: ObservedCapacity (max).

#### Data processed

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: DataProcessed (sum).

#### Rule hits

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: NetworkRuleHit (sum); ApplicationRuleHit (sum).

> Health below 100% with SNAT use near 100% is SNAT exhaustion: health includes SNAT port use. Low health with normal SNAT use and no scaling is worth raising with Microsoft support, with the firewall and the times.

## Tab: Policy

#### Firewall policies

*Table · Azure Resource Graph*

Columns: Policy, Tier, Threat intel, IDPS, TLS inspection, DNS proxy, Not SNATed (private ranges), Firewalls, Parent policy, Rule collection groups, Rule collections, Rules, Provisioning, Resource group.

When there is nothing to show: *No firewall policies found.*

> A policy attached to no firewall is flagged. Rule counts are totals across the policy's own rule collection groups; rules inherited from a parent policy are counted on the parent. DNS proxy must be on for FQDNs in network rules to resolve the same way the clients do.

## Tab: Traffic & threats

> Select a **Log Analytics workspace** at the top for what the firewall logs show (needs the resource-specific firewall logs, such as `AZFWNetworkRule` and `AZFWApplicationRule`).

#### Top denied flows

*Table · Log Analytics* · reads `AZFWNetworkRule`, `AZFWApplicationRule`

When there is nothing to show: *No denied flows (or the structured firewall logs are not enabled).*

#### Threat intel and IDPS detections

*Table · Log Analytics* · reads `AZFWThreatIntel`, `AZFWIdpsSignature`

When there is nothing to show: *No threat intel or IDPS hits.*

#### DNS proxy queries by response code

*Time chart · Log Analytics* · reads `AZFWDnsQuery`

When there is nothing to show: *No DNS proxy queries (DNS proxy off, or its logs are not enabled).*

#### Top failing DNS proxy queries

*Table · Log Analytics* · reads `AZFWDnsQuery`

When there is nothing to show: *No failing DNS queries.*
