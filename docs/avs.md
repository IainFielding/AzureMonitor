# Azure VMware Solution

*Reference for [avs.workbook.json](../workbook/avs.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

Are the private clouds healthy, do they have room to grow, are they connected and monitored, and what are vCenter, ESXi and NSX reporting?

It has 36 panels across 4 tabs. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Time range | Applies to metrics, changes and log panels. |
| Log Analytics workspace | Optional. The workspace the private clouds' diagnostic settings send VMware syslog to. Enables the Logs tab. |
| Private clouds | The private clouds the metric charts show. |
| Private cloud | Clusters, add-ons, Global Reach, NSX and run commands are read from Azure Resource Manager for one private cloud at a time. |

## Tab: Overview

#### Tile clouds

*Tiles · Azure Resource Graph* · reads `healthresources`

#### Tile connected

*Tiles · Azure Resource Graph*

#### Tile alerts

*Tiles · Azure Resource Graph*

#### Tile health

*Tiles · Azure Resource Graph* · reads `servicehealthresources`

#### Tile advisor

*Tiles · Azure Resource Graph* · reads `advisorresources`

#### Tile cpu

*Tiles · Azure Monitor metrics* of `microsoft.avs/privateclouds`: EffectiveCpuAverage (average).

#### Tile mem

*Tiles · Azure Monitor metrics* of `microsoft.avs/privateclouds`: UsageAverage (average).

#### Tile vsan

*Tiles · Azure Monitor metrics* of `microsoft.avs/privateclouds`: DiskUsedPercentage (average).

> Thresholds: CPU and memory warn at **80%** and are critical at **90%**. vSAN warns at **70%** and is critical at
> **75%**: AVS needs 25% of each vSAN datastore free to stay within its SLA. *Not connected to a hub* means no
> ExpressRoute connection you can see uses the private cloud's circuit; a gateway in a subscription you cannot read
> counts as not connected.

#### Private clouds

*Table · Azure Resource Graph* · reads `healthresources`

Columns: Private cloud, Health, Reason, Sku, Management hosts, Availability, Internet, Encryption, Network block, Provisioning, Resource Group, Location.

When there is nothing to show: *No Azure VMware Solution private clouds found.*

#### Metric alert rules per private cloud

*Table · Azure Resource Graph*

Columns: Private cloud, CPU, Memory, v SAN, Rules in total.

When there is nothing to show: *No private clouds.*

#### Advisor recommendations

*Table · Azure Resource Graph* · reads `advisorresources`

Columns: Impact, Category, Problem, Solution, Private cloud, Updated.

When there is nothing to show: *No Advisor recommendations for AVS.*

> Microsoft recommends metric alerts on at least vSAN used % (`DiskUsedPercentage`, above 70%), CPU (`EffectiveCpuAverage`, above 80%) and memory (`UsageAverage`, above 80%). A rule counts when it is enabled and scoped to the private cloud, or to its resource group or subscription with private clouds as the target type.

#### Service Health events for Azure VMware Solution (active, or updated in the last 30 days)

*Table · Azure Resource Graph* · reads `servicehealthresources`

When there is nothing to show: *No Service Health events for Azure VMware Solution.*

#### Resource Health changes (time range, up to 14 days)

*Table · Azure Resource Graph* · reads `healthresourcechanges`

Columns: Time, Private cloud, Previous, Health.

When there is nothing to show: *No Resource Health changes in the time range.*

## Tab: Capacity

> AVS needs **25% vSAN slack space** in every datastore to stay within its SLA, so keep vSAN used below **75%**. CPU or memory above 80% for days at a time is a sign the cluster needs another host; a host takes time to add, so act on the trend rather than the peak.

#### Key metrics per private cloud (time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.avs/privateclouds`: CPU % (average); Memory % (average); vSAN used % (average); Datastore used (average); Datastore capacity (average).

#### CPU % by cluster

*Chart · Azure Monitor metrics* of `microsoft.avs/privateclouds`: EffectiveCpuAverage (average, split by clustername).

#### Memory % by cluster

*Chart · Azure Monitor metrics* of `microsoft.avs/privateclouds`: UsageAverage (average, split by clustername).

#### vSAN used % by datastore

*Chart · Azure Monitor metrics* of `microsoft.avs/privateclouds`: DiskUsedPercentage (average, split by dsname).

#### Datastore used and capacity

*Chart · Azure Monitor metrics* of `microsoft.avs/privateclouds`: UsedLatest (average, split by dsname); CapacityLatest (average, split by dsname).

## Tab: Private cloud

### Configuration

#### Endpoints, network and resilience

*Table · Azure Resource Graph*

Columns: v Center, NSX Manager, HCX Cloud Manager, Network block, Extended network blocks, Internet, DNS zone type, Availability, Zone, Secondary zone, Customer-managed keys, Identity.

#### Management cluster

*Table · Azure Resource Graph*

Columns: Cluster id, Host type, Hosts, Provisioning, vSAN datastore, Hosts (names).

#### Other clusters

*Table · Azure Resource Manager*: `GET {Cloud}/clusters`

Columns: Cluster, Host type, Hosts, Provisioning.

When there is nothing to show: *No clusters besides the management cluster.*

#### Add-ons (HCX, SRM, vSphere Replication, Arc)

*Table · Azure Resource Manager*: `GET {Cloud}/addons`

Columns: Add-on, Name, Provisioning.

When there is nothing to show: *No add-ons.*

### Connectivity

#### ExpressRoute connections that use this private cloud's circuit

*Table · Azure Resource Graph*

Columns: Connection, Gateway, State, Routing weight.

#### Global Reach connections (to on-premises or another private cloud)

*Table · Azure Resource Manager*: `GET {Cloud}/globalReachConnections`

Columns: Name, State, Peer circuit, Address prefix, Provisioning.

When there is nothing to show: *No Global Reach connections.*

#### NSX segments

*Table · Azure Resource Manager*: `GET {Cloud}/workloadNetworks/default/segments`

Columns: Segment, Gateway address, Connected gateway, Status, Provisioning.

When there is nothing to show: *No NSX segments, or they were created in NSX Manager rather than through Azure.*

#### DNS forwarder zones

*Table · Azure Resource Manager*: `GET {Cloud}/workloadNetworks/default/dnsZones`

Columns: Zone, Domains, DNS servers, Source IP, Provisioning.

When there is nothing to show: *No DNS forwarder zones.*

> The private cloud's ExpressRoute circuit is managed by Microsoft. It reaches Azure through a connection from a hub's ExpressRoute gateway, using an authorisation key, and reaches on-premises through Global Reach. The Platform health workbook's ExpressRoute and Throughput tabs chart the gateway. Segments and DNS zones made in NSX Manager rather than through Azure do not appear here.

### Operations

#### Run command history

*Table · Azure Resource Manager*: `GET {Cloud}/scriptExecutions`

Columns: Run, Command, State, Submitted, Finished, Failure.

When there is nothing to show: *No run commands have been run.*

#### Diagnostic settings

*Table · Azure Resource Manager*: `GET {Cloud}/providers/Microsoft.Insights/diagnosticSettings`

Columns: Setting, Workspace, Storage account, Event hub, Logs, Metrics.

When there is nothing to show: *No diagnostic settings: VMware syslog is not being collected for this private cloud.*

#### Changes to the private cloud (time range, up to 14 days)

*Table · Azure Resource Graph* · reads `resourcechanges`

Columns: Time, Resource, Change, Properties, Changed by, Client, Operation.

When there is nothing to show: *No changes in the time range.*

## Tab: Logs

> Select a **Log Analytics workspace** at the top. The logs come from each private cloud's diagnostic setting (category *VMware Syslog*, table `AVSSyslog`), which carries vCenter, ESXi, vSAN and NSX syslog.

#### Private clouds by last record in the workspace

*Table · Log Analytics*

Columns: Private cloud, Status, Records, Last record, Tables, Resource Group.

When there is nothing to show: *No private clouds.*

#### Syslog records by level

*Time chart · Log Analytics* · reads `AVSSyslog`

When there is nothing to show: *No VMware syslog in the time range.*

#### Errors and warnings by source

*Table · Log Analytics* · reads `AVSSyslog`

When there is nothing to show: *No errors or warnings in the time range.*

#### vCenter alarms raised (time range)

*Table · Log Analytics* · reads `AVSSyslog`

Columns: Alarm, Object, Latest state, Times raised, Last change.

When there is nothing to show: *No vCenter alarms turned yellow or red in the time range.*

#### Most frequent error messages

*Table · Log Analytics* · reads `AVSSyslog`

When there is nothing to show: *No errors in the time range.*

#### NSX firewall: dropped and rejected flows

*Table · Log Analytics* · reads `AVSSyslog`

When there is nothing to show: *No dropped flows logged. NSX only logs flows for rules that have logging turned on.*

#### Azure operations on private clouds (activity log)

*Table · Log Analytics* · reads `AzureActivity`

When there is nothing to show: *No Azure operations on private clouds in the time range (or the activity log is not sent to this workspace).*
