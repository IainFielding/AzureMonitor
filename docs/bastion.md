# Azure Bastion

*Reference for [bastion.workbook.json](../workbook/bastion.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

Every Bastion host: how it is configured, whether its subnet is right, which VMs it can reach, the rules that let RDP and SSH round it, who connected to what, how busy it is, and who changed it.

It has 25 panels across 6 tabs. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Log Analytics workspace | The workspace that receives the Bastion audit logs and the Activity log. |
| Time range | For sessions, metrics and changes. Resource Graph keeps 14 days of changes. |
| User | Optional. Part of a user's name or email, to follow one person's sessions. |
| Target | Optional. A VM name, part of its resource id, or its IP address, to see who connected to it. |
| Bastion hosts | Which bastion hosts to include. |

## Tab: Overview

#### Tile hosts

*Tiles · Azure Resource Graph*

#### Tile subnets

*Tiles · Azure Resource Graph* · reads `resourcecontainers`

#### Tile reach

*Tiles · Azure Resource Graph* · reads `resourcecontainers`

#### Tile bypass

*Tiles · Azure Resource Graph* · reads `resourcecontainers`

#### Tile links

*Tiles · Azure Resource Graph*

> Select a **Log Analytics workspace** at the top for sessions: who connected to what, from where, and for how long.

#### Session tiles

*Tiles · Log Analytics* · reads `AzureDiagnostics`

#### Findings

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Severity, Finding, Bastion, Sku, Instances, Advice, Subscription, Resource group.

When there is nothing to show: *No findings: every host is provisioned, on Basic or above, with shareable links off.*

#### Sessions by protocol

*Time chart · Log Analytics* · reads `AzureDiagnostics`

## Tab: Configuration

#### Bastion hosts

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Bastion, SKU, Instances, Access, VNet, Public IP, Zones, Native client, IP-based connection, Shareable links, File copy, Copy and paste, Kerberos, Session recording, Provisioning, Subscription, Resource group, Location.

When there is nothing to show: *No Bastion hosts in the selected subscriptions.*

> **What each SKU adds.** *Developer*: free, shared, one VNet, browser only, no peering. *Basic*: a dedicated host
> with two instances, reaching VMs in its own and directly peered VNets. *Standard*: adds scaling (2 to 50 instances),
> the native client (`az network bastion rdp/ssh`), IP-based connection (any routable address, including on-premises),
> Kerberos, shareable links and file copy. *Premium*: adds session recording and private-only deployment (no public IP).

#### AzureBastionSubnet in every VNet

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: VNet, Prefix, Bastion, NSG, Route table, State, Problems, subscription Id, Resource group.

When there is nothing to show: *No VNet has an AzureBastionSubnet.*

> The checks follow Microsoft's requirements for the subnet. An NSG on AzureBastionSubnet is optional, but if there is
> one it must allow, at least: **inbound** HTTPS (443) from *Internet* (not needed for a private-only host) and from
> *GatewayManager*, and 8080 and 5701 within *VirtualNetwork* for the host's own data plane; **outbound** RDP and SSH
> (3389, 22) to *VirtualNetwork*, HTTPS to *AzureCloud*, and 80 to *Internet* for certificate checks. The checks here
> look for the main ones by service tag; a rule that names address ranges instead is not recognised. Bastion does not
> support a route table on its subnet, so traffic from it cannot be forced through a firewall.

## Tab: Reach & bypass

#### Virtual machines by Bastion path

*Pie chart · Azure Resource Graph* · reads `resourcecontainers`

> Bastion reaches VMs in its own VNet and in VNets **directly peered** with it. In a Virtual WAN landing zone, spokes
> are connected to the hub rather than peered with each other, so a host in one spoke does not reach VMs in another
> by default: give each spoke that needs it a host (the Developer SKU costs nothing for testing), or use a Standard or
> Premium host with **IP-based connection**, which connects to any private address the host can route to (through
> the hub, or on-premises) if the NSGs allow it. VMs listed as having no path may still be reachable that way.

#### Virtual machines and the Bastion that reaches them

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Reach, Virtual machine, Private IP, VNet, Bastion, Subscription, Resource group.

When there is nothing to show: *No virtual machines in the selected subscriptions.*

### Around Bastion: RDP and SSH open to the internet

#### NSG rules allowing RDP or SSH in from any address

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Exposes, NSG, Rule, Priority, Source, Ports, NSG in use, Subnets, NICs, Subscription, Resource group.

When there is nothing to show: *No NSG rule lets RDP or SSH in from the internet.*

> A VM is reachable through such a rule only if it also has a public IP or sits behind a public load balancer, but each rule is one change away from exposing a management port, which is what Bastion is there to avoid. Narrow the source, or remove the rule and connect through Bastion. Rules on the AzureBastionSubnet's own NSG are left out.

## Tab: Sessions

> Select a **Log Analytics workspace** at the top for sessions: who connected to what, from where, and for how long.

> From each host's **Bastion audit logs** (diagnostic setting category *BastionAuditLogs*, table
> `MicrosoftAzureBastionAuditLogs`, or `AzureDiagnostics` in the older mode). A session is logged when it ends. *Client*
> is read from the user agent: the native client (`az network bastion rdp/ssh`, or `mstsc` through a tunnel) or a
> browser. Filter by **User** and **Target** at the top to follow one person or one machine.

#### Sessions

*Table · Log Analytics* · reads `AzureDiagnostics`

Columns: Start, End, Minutes, User, Client address, Target, Target IP, Protocol, Client, Bastion, User Agent.

When there is nothing to show: *No Bastion sessions in the time range, or the hosts do not send audit logs to this workspace.*

#### By person

*Table · Log Analytics* · reads `AzureDiagnostics`

When there is nothing to show: *No sessions.*

#### By machine

*Table · Log Analytics* · reads `AzureDiagnostics`

When there is nothing to show: *No sessions.*

#### Worth a second look

*Table · Log Analytics* · reads `AzureDiagnostics`

When there is nothing to show: *No sessions of 8 hours or more, and nobody connected from an address new to them.*

> *New client address* compares the second half of the time range with the first: a person who connected from an address they had not used before. Expect some from home working and changing ISPs; follow up on addresses in unexpected countries.

## Tab: Health & capacity

#### Bastion metrics (over time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.network/bastionhosts`: Communication status (average); Sessions (peak) (max); CPU usage (average); Memory used (average).

#### Sessions

*Chart · Azure Monitor metrics* of `microsoft.network/bastionhosts`: sessions (max).

#### Communication status (1 = healthy)

*Chart · Azure Monitor metrics* of `microsoft.network/bastionhosts`: pingmesh (average).

#### CPU usage

*Chart · Azure Monitor metrics* of `microsoft.network/bastionhosts`: usage_user (average).

#### Memory used

*Chart · Azure Monitor metrics* of `microsoft.network/bastionhosts`: used (average).

### Concurrent sessions, from the audit logs

> Select a **Log Analytics workspace** at the top for sessions: who connected to what, from where, and for how long.

#### Concurrent sessions per host (15-minute steps)

*Time chart · Log Analytics* · reads `AzureDiagnostics`

> Microsoft sizes each Bastion instance for about **20 concurrent RDP** or **40 concurrent SSH** sessions for typical use (fewer for heavy graphical work). A Basic host has two instances; Standard and Premium can be scaled from 2 to 50 in *Configuration → Instance count*. If the peak approaches instances × 20, scale up before people start seeing slow or refused connections. *Communication status* below 1 means the instances cannot reach each other or the control plane: check the subnet's NSG on the *Configuration* tab. The Developer SKU has no metrics and is left out of the picker.

## Tab: Changes & admin

#### Bastion hosts created, changed and deleted

*Table · Azure Resource Graph* · reads `resourcechanges`

Columns: Time, Change, Bastion, Properties changed, Changed by, Client.

When there is nothing to show: *No Bastion host changed in the time range (Resource Graph keeps 14 days).*

> Select a **Log Analytics workspace** at the top for shareable links and session management, from the Activity log.

#### Shareable links, session management and changes (Activity log)

*Table · Log Analytics* · reads `AzureActivity`

Columns: Time, Action, Caller, Caller address, Status, Bastion.

When there is nothing to show: *No Bastion actions in the Activity log in the time range.*

> A **shareable link** lets anyone who holds it reach that VM through Bastion without signing in to the Azure portal, until the link is deleted. Check who created each one, and delete links that are no longer needed (the host's *Shareable links* blade).
