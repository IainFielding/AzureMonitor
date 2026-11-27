# Public IP addresses

*Reference for [public-ip.workbook.json](../workbook/public-ip.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

Every public IP address and prefix: what uses it, which are paid for but unused or on the retired Basic SKU, whether DDoS Protection covers them, how much traffic they carry, who changed them, and whose an address is.

It has 26 panels across 7 tabs. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Time range | For the traffic charts, DDoS logs and changes. Resource Graph keeps 14 days of changes. |
| Find | An IP address or DNS name, for the Find an IP tab. |
| Price per IP a month | What one Standard public IP costs you a month, in your currency, for the cost estimates. |
| Log Analytics workspace | Optional. The workspace that receives the public IPs' DDoS diagnostic logs. |
| Public IPs | Which public ips to include. |

## Tab: Overview

#### Tiles

*Tiles · Azure Resource Graph* · reads `resourcecontainers`

#### Tile prefixes

*Tiles · Azure Resource Graph*

#### Public IPs by what uses them

*Pie chart · Azure Resource Graph* · reads `resourcecontainers`

#### Public IPs by region

*Pie chart · Azure Resource Graph* · reads `resourcecontainers`

#### Needs attention

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Issue, Public IP, Address, Attached to, Used by, SKU, Zones, Fix, Subscription, Resource group.

When there is nothing to show: *Every public IP is in use, Standard SKU, not pinned to one zone and has DDoS protection left on.*

> **Zones.** *Zone-redundant* survives the loss of a zone; *Zone 1/2/3* is pinned to that zone and goes down
> with it. *No zone set* is either a region without availability zones or an IP created without a zone: Microsoft
> has been making Standard IPs created without a zone zone-redundant in regions that have zones, but Resource Graph
> still shows no zones for them, so check the IP's *Overview* blade before replacing it. A zone cannot be changed on
> an existing IP: it has to be recreated, which changes the address.

## Tab: Inventory

#### Public IP addresses

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Public IP, Address, Attached to, Used by, DNS name, SKU, Tier, Allocation, Version, Zones, DDoS protection, From prefix, IP tags, Idle timeout (min), Provisioning, Subscription, Resource group, Location.

When there is nothing to show: *No public IP addresses in the selected subscriptions.*

> *Used by* is the resource the address is attached to: a virtual machine (rather than its NIC), load balancer, gateway, firewall, Bastion or NAT gateway. *NIC with no VM* is an address on a network interface whose VM was deleted. *IP tags* show a routing preference (`RoutingPreference=Internet` sends traffic over the public internet rather than Microsoft's network) or a first-party service tag.

#### Public IP prefixes

*Table · Azure Resource Graph*

Columns: Prefix, Range, Version, Addresses, Used, Free, Used %, Zones, Range owner, Provisioning, subscription Id, Resource group, Location.

When there is nothing to show: *No public IP prefixes in the selected subscriptions.*

## Tab: Find an IP

> Type an **IP address** or a public IP's **DNS name** (for example `myapp.westeurope.cloudapp.azure.com`) in
> *Find* at the top. The search covers public IP addresses and prefixes in the selected subscriptions, and also the
> addresses Azure manages for you that are not public IP resources: App Service outbound addresses, the public
> addresses of secured virtual hub firewalls (Virtual WAN), and Virtual WAN VPN gateways.

#### Who has {Search}?

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Match, Resource, Address, Used by, DNS name, subscription Id, Resource group, Location.

When there is nothing to show: *The address is not in the selected subscriptions. It may belong to a subscription you cannot read, be a Microsoft-owned address shared by a platform service (check the Azure IP ranges and service tags download), or not be an Azure address at all.*

> **Not covered:** addresses Azure assigns to a service without a public IP resource, other than those above:
> default outbound access of VMs with no public IP, NAT gateway or load balancer (a Microsoft-owned address that can
> change, retired for new VNets from 30 September 2025), Azure Front Door and API Management's shared addresses,
> and the ExpressRoute and VPN gateways' own management addresses.

## Tab: Clean-up & cost

### Paid for but not in use

#### Public IPs not attached to anything

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Public IP, Address, Attached to, NIC, SKU, Allocation, DNS name, From prefix, Est. per month, Kept on purpose?, Subscription, Resource group, Location.

When there is nothing to show: *Every public IP is attached to something.*

> **What an unused address costs.** A Standard public IP is billed by the hour whether or not it is attached,
> about 3.65 a month in US dollars at list price (set *Price per IP a month* at the top to your own rate). A
> dynamic Basic IP is free while unattached, but Basic is retired. An IP taken from a **public IP prefix** is paid
> for through the prefix, which bills for every address in it whether used or not, so deleting the IP alone saves
> nothing: reuse it, or shrink the prefix.
>
> Before deleting, check the address is not kept on purpose: allow-listed by a partner or a SaaS provider, held for
> disaster recovery, or behind a DNS record (a deleted address left in DNS is a subdomain takeover risk). Rows tagged
> with *keep*, *reserved*, *allowlist* or *dr* are listed last.

#### Public IP prefixes less than half used

*Table · Azure Resource Graph*

Columns: Prefix, Range, Version, Addresses, Used, Free, Used %, Zones, Range owner, Provisioning, subscription Id, Resource group, Location.

When there is nothing to show: *Every public IP prefix is at least half used.*

### Basic SKU (retired)

#### Basic SKU public IPs

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Public IP, Address, Attached to, Used by, Allocation, DNS name, Subscription, Resource group, Location.

When there is nothing to show: *No Basic SKU public IPs.*

> Basic SKU public IPs were retired on **30 September 2025**: they no longer have an SLA or support, and Microsoft
> may stop them working. Upgrade a static Basic IP to Standard in place (the address is kept); a dynamic one must be
> made static first, and a Basic IP on a Basic load balancer or VPN gateway is upgraded with that resource. Standard
> IPs are closed to inbound traffic unless an NSG allows it, so add the NSG rules the service needs before upgrading
> an IP on a VM.

### Azure Advisor

#### Advisor recommendations for public IPs and prefixes

*Table · Azure Resource Graph* · reads `advisorresources`

Columns: Resource, Category, Impact, Problem, Solution, Updated.

When there is nothing to show: *Advisor has no recommendations for public IPs.*

## Tab: DDoS protection

#### Effective DDoS protection

*Pie chart · Azure Resource Graph* · reads `resourcecontainers`

#### DDoS protection plans

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Plan, VNets linked, Provisioning, subscription Id, Resource group, Location.

When there is nothing to show: *No DDoS protection plans: public IPs have platform default protection only, unless IP Protection is enabled on them.*

> Every public IP gets Azure's **platform default** protection against large volumetric attacks, tuned to protect
> Azure rather than your service. **DDoS Network Protection** (a plan linked to the VNet) and **DDoS IP Protection**
> (per IP) add mitigation tuned to each IP's normal traffic, attack alerts and logs, and cost protection. A public
> IP's *DDoS protection* setting is *Inherited from virtual network* by default, so it is covered when the VNet of
> the resource using it is linked to a plan. *Follows the backend VNet* is a load balancer frontend: it is covered
> when the backend VNet is.

#### Protection of each public IP

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Public IP, Address, Protection, Attached to, Used by, VNet, Plan, Setting on the IP, Subscription, Resource group.

When there is nothing to show: *No public IP addresses in the selected subscriptions.*

### Attacks and mitigations

> Select a **Log Analytics workspace** at the top for the DDoS notifications, mitigation reports and flow logs. The attack charts on the *Traffic* tab need no workspace.

#### Mitigation notifications and reports

*Table · Log Analytics* · reads `AzureDiagnostics`

Columns: Time, Category, Event, Address, Public IP, Detail.

When there is nothing to show: *No DDoS mitigations in the time range. These logs exist only for IPs with Network or IP Protection whose diagnostic settings send DDoSProtectionNotifications and DDoSMitigationReports here.*

#### Traffic dropped or forwarded during mitigation, busiest sources

*Table · Log Analytics* · reads `AzureDiagnostics`

When there is nothing to show: *No DDoS mitigation flow logs in the time range.*

## Tab: Traffic

> Charts start with the first 10 attached public IPs; choose others, or **All**, in the picker. *Data path availability* is Azure's probe of the address from inside its own network.

#### Public IP metrics (over time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.network/publicipaddresses`: Data path availability % (average); Bytes (sum); Packets (sum); SYN packets (sum); Under DDoS attack (max).

#### Bytes

*Chart · Azure Monitor metrics* of `microsoft.network/publicipaddresses`: ByteCount (sum, split by Direction).

#### Packets

*Chart · Azure Monitor metrics* of `microsoft.network/publicipaddresses`: PacketCount (sum, split by Direction).

#### SYN packets (new TCP connections)

*Chart · Azure Monitor metrics* of `microsoft.network/publicipaddresses`: SynCount (sum, split by Direction).

#### Data path availability

*Chart · Azure Monitor metrics* of `microsoft.network/publicipaddresses`: VipAvailability (average).

#### Under DDoS attack (1 = yes)

*Chart · Azure Monitor metrics* of `microsoft.network/publicipaddresses`: IfUnderDDoSAttack (max).

#### Inbound packets dropped by DDoS mitigation

*Chart · Azure Monitor metrics* of `microsoft.network/publicipaddresses`: PacketsDroppedDDoS (max).

## Tab: Changes

#### Public IPs and prefixes created, changed and deleted

*Table · Azure Resource Graph* · reads `resourcechanges`

Columns: Time, Change, Resource, Properties changed, Changed by, Client, Operation, Kind.

When there is nothing to show: *No public IPs or prefixes changed in the time range (Resource Graph keeps 14 days).*

#### Public IPs attached, detached or moved

*Table · Azure Resource Graph* · reads `resourcechanges`

Columns: Time, Resource, Property, Before, After, Changed by, Client.

When there is nothing to show: *No public IP was attached or detached in the time range.*

> From Resource Graph's change history, which keeps 14 days. *Changed by* is filled in for changes made through Azure Resource Manager; a change made by the platform (an AKS cluster adding a load balancer IP) shows the service's identity. For older changes, use the **What changed?** workbook with the Activity log in a workspace.
