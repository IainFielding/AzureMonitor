# Routing: what path does traffic take?

*Reference for [routing.workbook.json](../workbook/routing.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

From one IP to another: where each address lives, the route each side picks, the next hop, whether the reply comes back the same way, and what every network security group on the way decides.

It has 9 panels. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Source IP | The address the traffic comes from. |
| Destination IP | The address it is going to. |
| Destination port | Optional. Makes the NSG check exact. |
| Protocol | For the NSG check. |
| Virtual WAN hub | Starts with a hub the source or destination network is connected to, if any. |

## Panels

> Enter a source and a destination IP (a port and protocol make the NSG check exact). This works from configuration
> in Resource Graph, so it answers instantly and needs no logs or Network Watcher, but see the note on learned routes.
>
> **Reading it, top to bottom.**
> 1. **Where the addresses are.** A *Private, but not in any network here* address is on-premises or in a
>    subscription you have not selected.
> 2. **The route each side picks.** Longest prefix wins; on a tie a user route beats a system route. *Forward* is the
>    source subnet's route to the destination, *Return* the destination subnet's route back.
> 3. **The verdict.** The usual failure is **asymmetric** routing: the request goes through a firewall and the reply
>    does not (or the other way round), and the firewall drops the half-session it sees.
> 4. **The NSGs.** Outbound at the source, inbound at the destination. A flow must be allowed at every NSG.
>
> **Learned routes are not visible here.** Routes a network learns over BGP (from ExpressRoute, VPN, a Virtual WAN
> hub or Route Server) are not in Resource Graph. If a network uses a gateway or is connected to a Virtual WAN hub,
> open *Effective routes* on the network interface for the definitive answer, and check the hub's routing intent
> below. Once the route is right, use the firewall workbook to see what the firewall decided.

#### Where the two addresses are

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Role, IP, Where, Virtual network, Subnet, Subnet range, Route table, Subnet NSG, Network interface, NIC NSG, VM, IP forwarding, Effective routes, Effective security rules.

#### The path

*Table · Azure Resource Graph*

Columns: Forward, Return, Verdict.

When there is nothing to show: *Neither address is in a virtual network in the selected subscriptions.*

#### The route each side picks

*Table · Azure Resource Graph*

Columns: Direction, Towards, Prefix, Origin, Next hop, Next hop IP, Appliance, Next hop is, Via, Note.

When there is nothing to show: *Neither address is in a virtual network in the selected subscriptions.*

#### Every route that covers the other address

*Table · Azure Resource Graph*

Columns: Direction, Towards, Prefix, Origin, Next hop, Next hop IP, Via, Note.

When there is nothing to show: *No routes: neither address is in a virtual network in the selected subscriptions.*

### Network security groups

#### Decision at each NSG on the path

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Position, NSG, Decision, Rule, Priority, Check first.

#### Rules that match, or might, in the order they apply

*Table · Azure Resource Graph*

Columns: Position, Priority, Rule, Access, Match, Source, Destination, Ports, Protocol, NSG.

When there is nothing to show: *No NSG on the path.*

> *Probably matches*: the rule uses the **VirtualNetwork** or **Internet** tag for an address that is not in a network here, judged by whether it is private (VirtualNetwork also covers peered and on-premises ranges). *Cannot tell*: another service tag or an application security group, which only the effective security rules can resolve. Without a port, a rule limited to certain ports shows as *Probably matches*.

### Virtual WAN hub

> A network connected to a Virtual WAN hub learns its routes from the hub. With **routing intent**, private traffic (and internet traffic, if set) goes to the hub firewall in both directions. Without it, the connection's associated and propagated route tables decide.

#### Routing intent

*Table · Azure Resource Manager*: `GET {Hub}/routingIntent`

Columns: Policy, Traffic, Next hop.

When there is nothing to show: *No routing intent on this hub.*

#### Network connections

*Table · Azure Resource Manager*: `GET {Hub}/hubVirtualNetworkConnections`

Columns: Connection, Network, Associated route table, Propagates to, Internet via hub, State.

When there is nothing to show: *No networks connected to this hub.*

#### Hub route tables

*Table · Azure Resource Manager*: `GET {Hub}/hubRouteTables`

Columns: Route table, Labels, Routes, Associated connections, Propagating connections.

When there is nothing to show: *No route tables on this hub.*
