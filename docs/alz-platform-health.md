# Enterprise Scale Platform Health

*Reference for [alz-platform-health.workbook.json](../workbook/alz-platform-health.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

Health, capacity and throughput of the shared platform: Virtual WAN connectivity (Firewall, ExpressRoute, VPN, end-to-end connectivity tests), application delivery, AI Foundry, shared services, identity, Azure VMware Solution, Azure Virtual Desktop, storage, build agents, governance, security, monitoring and backup.

It has 247 panels across 19 tabs. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Time range | The period the log and metric panels cover. |
| Log Analytics workspace | The central platform workspace. Enables the log-based panels. |
| Build agent name pattern | Regex matched against scale set names to identify build agent pools. |
| Domain controller name pattern | Regex matched against virtual machine and computer names on the Identity tab. |
| Storage account pattern | Regex matched against storage account and resource group names on the Storage and Throughput tabs. Metric charts handle at most 200 accounts; use '.' for all. |
| Nerdio Manager name pattern | Regex matched against resource names to find Nerdio Manager's own app service, database, key vault, automation account and Application Insights (AVD tab). |
| Nerdio tag prefix | The prefix of the tags Nerdio Manager puts on what it manages: NMW_ unless it was changed at install. Case-sensitive (AVD tab). |
| Nerdio Manager app id | Optional. The application (client) id of Nerdio Manager's app registration, to label its actions on session hosts apart from other automation (AVD tab). |
| Hubs | Which hubs to include. |
| Firewalls | Which firewalls to include. |
| Circuits | Which circuits to include. |
| ER gateways | Which er gateways to include. |
| S2S gateways | Which s2s gateways to include. |
| P2S gateways | Which p2s gateways to include. |
| Application gateways | Which application gateways to include. |
| Front Door profiles | Which front door profiles to include. |
| API Management | Which api management to include. |
| AI Foundry resources | Which ai foundry resources to include. |
| Subscription | The subscriptions to read. Defaults to all you can see. |
| Region |  |
| Bastions | Which bastions to include. |
| Key vaults | Which key vaults to include. |
| Public IPs | Which public ips to include. |
| Domain controllers | Which domain controllers to include. |
| Agent scale sets | Which agent scale sets to include. |
| Private clouds | Which private clouds to include. |
| Storage accounts | Which storage accounts to include. |
| Subscription | The subscriptions to read. Defaults to all you can see. |
| Region |  |

## Tab: Overview

> Status comes from **Azure Resource Health** where available; otherwise from the resource's configuration state (provisioning, hub routing state, circuit/provider state, DNS limits, workspace ingestion) — see the *Signal* column. Each service tab adds metric-based health. *History and inventory* at the bottom of this tab loads health state changes, availability, recent changes and the full inventory when asked.

### Issues

> One tile per check, drawn from every tab. The number is how many things the check found wrong; a green tick means none. The line under it names the tab that has the detail. *Defender plans off* counts subscriptions, *Exemptions expiring* looks 30 days ahead, and *High incidents open* is Sentinel.

#### Issues resources

*Tiles · Azure Resource Graph*

#### Issues health

*Tiles · Azure Resource Graph* · reads `healthresourcechanges`

#### Issues patch

*Tiles · Azure Resource Graph* · reads `patchassessmentresources`

#### Issues retirement

*Tiles · Azure Resource Graph* · reads `advisorresources`

#### Issues exemptions

*Tiles · Azure Resource Graph* · reads `policyresources`

#### Issues defender

*Tiles · Azure Resource Graph* · reads `securityresources`

#### Issues access

*Tiles · Azure Resource Graph* · reads `authorizationresources`

#### Issues logs

*Tiles · Log Analytics* · reads `NWConnectionMonitorTestResult`, `WVDAgentHealthStatus`, `AzureActivity`, `Perf`, `InsightsMetrics`, `Heartbeat`, `SecurityIncident`

### At a glance

#### Servicehealth tile

*Tiles · Azure Resource Graph* · reads `servicehealthresources`

#### Policy

*Tiles · Azure Resource Graph* · reads `policyresources`

#### Defender

*Tiles · Azure Resource Graph* · reads `securityresources`

#### Advisor

*Tiles · Azure Resource Graph* · reads `advisorresources`

#### Backup

*Tiles · Azure Resource Graph* · reads `recoveryservicesresources`

#### Platform services

*Tiles · Azure Resource Graph* · reads `healthresources`

When there is nothing to show: *No platform resources found in the selected subscriptions.*

### Azure VMware Solution at a glance

#### Avs clouds

*Tiles · Azure Resource Graph*

#### Avs cpu

*Tiles · Azure Monitor metrics* of `microsoft.avs/privateclouds`: EffectiveCpuAverage (average).

#### Avs mem

*Tiles · Azure Monitor metrics* of `microsoft.avs/privateclouds`: UsageAverage (average).

#### Avs vsan

*Tiles · Azure Monitor metrics* of `microsoft.avs/privateclouds`: DiskUsedPercentage (average).

#### Azure Virtual Desktop session hosts

*Tiles · Log Analytics* · reads `WVDAgentHealthStatus`

When there is nothing to show: *No AVD session host data in the selected workspace.*

> Select the **Log Analytics workspace** at the top to see AVD session host status here.

#### Resources needing attention

*Table · Azure Resource Graph* · reads `healthresources`

Columns: Resource, Service, Health, Signal, Reason, Since, Resource Group, Location.

When there is nothing to show: *All platform resources report Available.*

#### Fired alerts on platform resources

*Table · Azure Resource Graph* · reads `alertsmanagementresources`

Columns: Severity, Alert, Target, State, Fired.

When there is nothing to show: *No fired alerts.*

#### Active Azure Service Health events

*Table · Azure Resource Graph* · reads `servicehealthresources`

Columns: Title, Event Type, Level, Tracking Id, Impact Start, Subscription Id.

When there is nothing to show: *No active Service Health events.*

### History and inventory

### Show health history, availability, changes and failed operations (loads when asked)

#### Health state changes (time range, up to 14 days)

*Table · Azure Resource Graph* · reads `healthresourcechanges`

Columns: Time, Resource, Service, From, To.

When there is nothing to show: *No Resource Health state changes on platform resources in the time range.*

#### Availability over the time range (resources with health incidents, up to 14 days)

*Table · Azure Resource Graph* · reads `healthresourcechanges`

Columns: Resource, Service, Available %, Incidents, Minutes impaired, Longest incident (min), Last incident.

When there is nothing to show: *No platform resource left the Available state in the time range.*

#### Recent changes to platform resources (time range, up to 14 days)

*Table · Azure Resource Graph* · reads `resourcechanges`

Columns: Time, Resource, Service, Change, Properties changed, Changed by, Client, Operation.

When there is nothing to show: *No changes to platform resources in the time range.*

#### Failed operations and deployments on platform resources

*Table · Log Analytics* · reads `AzureActivity`

When there is nothing to show: *No failed operations in the time range (or the activity log is not sent to this workspace).*

### Show all platform resources (loads when asked)

#### All platform resources

*Table · Azure Resource Graph* · reads `healthresources`

Columns: Resource, Service, Health, Signal, Reason, Resource Group, Location.

## Tab: Virtual WAN

#### Virtual WANs

*Table · Azure Resource Graph*

Columns: Virtual WAN, Wan Type, Hubs, Vpn Sites, Branch To Branch, Provisioning, Resource Group, Location.

When there is nothing to show: *No Virtual WANs found.*

#### Virtual hubs

*Table · Azure Resource Graph*

Columns: Hub, Wan, Address Prefix, Routing State, Routing Preference, Min routing units, Secured, Express Route, S2 SVpn, P2 SVpn, Provisioning, Location.

When there is nothing to show: *No virtual hubs found.*

#### Hub router metrics (over time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.network/virtualhubs`: Spoke VM utilisation % (max) (max); Routing infra units (max); Routes learned (max) (max); Data processed (sum).

> Each routing infrastructure unit supports ~1,000 spoke VMs. If *Spoke VM utilisation* approaches 100%, raise the hub's minimum routing units.

#### Hub BGP peer status by peer (1 = up)

*Chart · Azure Monitor metrics* of `microsoft.network/virtualhubs`: BgpPeerStatus (max, split by bgppeerip).

#### Spoke VM utilisation %

*Chart · Azure Monitor metrics* of `microsoft.network/virtualhubs`: SpokeVMUtilization (max).

#### Routes learned from peers

*Chart · Azure Monitor metrics* of `microsoft.network/virtualhubs`: CountOfRoutesLearnedFromPeer (max, split by bgppeerip).

#### Hub data processed

*Chart · Azure Monitor metrics* of `microsoft.network/virtualhubs`: VirtualHubDataProcessed (sum).

#### Spoke VNet connections (peerings)

*Table · Azure Resource Graph*

Columns: Spoke VNet, Connected To, Peering State, Sync Level, Address Space, Resource Group.

When there is nothing to show: *No VNet peerings found.*

## Tab: Firewall

#### Firewalls

*Table · Azure Resource Graph*

Columns: Firewall, Tier, Hub, Policy, Public IPs, Private IP, Zones, Provisioning, Resource Group, Location.

When there is nothing to show: *No Azure Firewalls found.*

#### Key metrics (over time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: Health % (average); Max SNAT % (max); Avg throughput (average); Observed capacity units (max) (max); Latency probe (ms) (average); Data processed (sum).

#### Health state %

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: FirewallHealth (average).

#### Throughput

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: Throughput (average).

#### SNAT port utilisation % (max)

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: SNATPortUtilization (max).

#### Observed capacity units

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: ObservedCapacity (max).

#### Latency probe (ms)

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: FirewallLatencyPng (average).

#### Rule hits

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: NetworkRuleHit (sum); ApplicationRuleHit (sum).

### Firewall policy

#### Firewall policies

*Table · Azure Resource Graph*

Columns: Policy, Tier, Threat intel, IDPS, TLS inspection, DNS proxy, Firewalls, Parent policy, Rule collection groups, Rule collections, Rules, Provisioning, Resource Group.

When there is nothing to show: *No firewall policies found.*

> A policy attached to no firewall is flagged. Rule counts are totals across the policy's own rule collection groups; rules inherited from a parent policy are counted on the parent. The TLS inspection certificate lives in Key Vault, so its expiry shows under *Expiry & retirement* on the Governance tab.

> Select a **Log Analytics workspace** at the top to see denied traffic, threat detections and DNS proxy queries (requires resource-specific firewall logs, e.g. `AZFWNetworkRule`).

#### Top denied flows

*Table · Log Analytics* · reads `AZFWNetworkRule`, `AZFWApplicationRule`

When there is nothing to show: *No denied flows (or structured firewall logs are not enabled).*

#### Threat intel & IDPS detections

*Table · Log Analytics* · reads `AZFWThreatIntel`, `AZFWIdpsSignature`

When there is nothing to show: *No threat intel or IDPS hits.*

#### DNS proxy queries by response code

*Time chart · Log Analytics* · reads `AZFWDnsQuery`

#### Top failing DNS proxy queries

*Table · Log Analytics* · reads `AZFWDnsQuery`

When there is nothing to show: *No failing DNS queries (or DNS proxy logs are not enabled).*

## Tab: ExpressRoute

#### Circuits

*Table · Azure Resource Graph*

Columns: Circuit, Circuit State, Provider State, Provider, Peering Location, Bandwidth Mbps, Sku, Peerings, Global Reach, Resource Group, Location.

When there is nothing to show: *No ExpressRoute circuits found.*

#### Circuit key metrics (over time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.network/expressroutecircuits`: BGP availability % (average); ARP availability % (average); Max ingress util % (max); Max egress util % (max); QoS drops in (bits/s) (average).

#### BGP availability % by peering

*Chart · Azure Monitor metrics* of `microsoft.network/expressroutecircuits`: BgpAvailability (average, split by PeeringType).

#### ARP availability % by peering

*Chart · Azure Monitor metrics* of `microsoft.network/expressroutecircuits`: ArpAvailability (average, split by PeeringType).

#### Circuit throughput (bits/s)

*Chart · Azure Monitor metrics* of `microsoft.network/expressroutecircuits`: BitsInPerSecond (average); BitsOutPerSecond (average).

#### Circuit bandwidth utilisation % (max)

*Chart · Azure Monitor metrics* of `microsoft.network/expressroutecircuits`: IngressBandwidthUtilization (max); EgressBandwidthUtilization (max).

#### vWAN ExpressRoute gateways

*Table · Azure Resource Graph*

Columns: Gateway, Hub, Min Scale Units, Connections, Provisioning, Resource Group, Location.

When there is nothing to show: *No vWAN ExpressRoute gateways found.*

#### Gateway connections

*Table · Azure Resource Graph*

Columns: Gateway, Connection, Circuit, Routing Weight, Internet Security, Fast Path, Provisioning.

When there is nothing to show: *No ExpressRoute connections found.*

#### Gateway key metrics (over time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.network/expressroutegateways`: CPU % (average); Avg bits/s (average); Avg packets/s (average); Max active flows (max); Routes learned (max).

#### Gateway CPU % by instance

*Chart · Azure Monitor metrics* of `microsoft.network/expressroutegateways`: ExpressRouteGatewayCpuUtilization (average, split by roleInstance).

#### Gateway throughput (bits/s)

*Chart · Azure Monitor metrics* of `microsoft.network/expressroutegateways`: ExpressRouteGatewayBitsPerSecond (average).

#### Routes learned by BGP peer

*Chart · Azure Monitor metrics* of `microsoft.network/expressroutegateways`: ExpressRouteGatewayCountOfRoutesLearnedFromPeer (max, split by BgpPeerAddress).

#### Bits in/s by connection

*Chart · Azure Monitor metrics* of `microsoft.network/expressroutegateways`: ErGatewayConnectionBitsInPerSecond (average, split by ConnectionName).

## Tab: VPN

#### vWAN VPN gateways

*Table · Azure Resource Graph*

Columns: Gateway, Kind, Hub, Scale Units, Connections, Bgp, Provisioning, Resource Group, Location.

When there is nothing to show: *No vWAN VPN gateways found.*

#### Site-to-site key metrics (over time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.network/vpngateways`: BGP peers up (1 = all) (average); Avg S2S bandwidth (average); Ingress drops (sum); Egress drops (sum); Traffic selector mismatch drops (sum).

#### Tunnel bandwidth by connection

*Chart · Azure Monitor metrics* of `microsoft.network/vpngateways`: TunnelAverageBandwidth (average, split by ConnectionName).

#### BGP peer status by peer (1 = up)

*Chart · Azure Monitor metrics* of `microsoft.network/vpngateways`: BgpPeerStatus (average, split by BgpPeerAddress).

#### Tunnel packet drops

*Chart · Azure Monitor metrics* of `microsoft.network/vpngateways`: TunnelIngressPacketDropCount (sum); TunnelEgressPacketDropCount (sum).

#### Tunnel bytes in / out

*Chart · Azure Monitor metrics* of `microsoft.network/vpngateways`: TunnelIngressBytes (sum); TunnelEgressBytes (sum).

#### P2S connections

*Chart · Azure Monitor metrics* of `microsoft.network/p2svpngateways`: P2SConnectionCount (sum).

#### P2S bandwidth

*Chart · Azure Monitor metrics* of `microsoft.network/p2svpngateways`: P2SBandwidth (average).

#### VPN sites

*Table · Azure Resource Graph*

Columns: Site, Vendor, Model, Links, Link Speed Mbps, Provider, Provisioning, Resource Group, Location.

When there is nothing to show: *No VPN sites found.*

#### Site connections

*Table · Azure Resource Graph*

Columns: Gateway, Connection, Site, Links, Bgp, Internet Security, Provisioning.

When there is nothing to show: *No VPN connections found.*

#### Tunnel connect/disconnect events

*Table · Log Analytics* · reads `AzureDiagnostics`

Columns: Time Generated, Gateway, Connection, Remote IP, Status, Reason.

When there is nothing to show: *No tunnel events (or gateway diagnostic logs are not sent to this workspace).*

## Tab: Connectivity

> End-to-end reachability from **Network Watcher Connection Monitor** tests. The other network tabs show each component's own metrics, which can all be healthy while a route between on-premises, the hub and a spoke is broken. Tests have to exist first: create them in Network Watcher and send their results to the selected workspace.

#### Connection monitors

*Table · Azure Resource Graph*

Columns: Connection monitor, Endpoints, Test groups, Test configurations, Workspace, Provisioning, Location.

When there is nothing to show: *No connection monitors found in the selected subscriptions.*

> Select the **Log Analytics workspace** that receives Connection Monitor results to see test status, packet loss and latency.

#### Tests by latest result

*Tiles · Log Analytics* · reads `NWConnectionMonitorTestResult`

When there is nothing to show: *No Connection Monitor results in the selected workspace.*

#### Tests (latest result, loss and latency over time range)

*Table · Log Analytics* · reads `NWConnectionMonitorTestResult`

Columns: Monitor, Test group, Source, Destination, Protocol, Result, Loss %, Avg RTT (ms), Max RTT (ms), Failed runs, Last result.

When there is nothing to show: *No Connection Monitor results in the time range.*

#### Checks failed % by path

*Time chart · Log Analytics* · reads `NWConnectionMonitorTestResult`

#### Average round-trip time (ms) by path

*Time chart · Log Analytics* · reads `NWConnectionMonitorTestResult`

### Network traffic (VNet flow logs)

#### Virtual networks by flow log coverage

*Table · Azure Resource Graph*

Columns: Virtual network, Flow logs, Retention (days), Subnets, Resource Group, Location.

When there is nothing to show: *No virtual networks found.*

#### Traffic by flow type (bytes)

*Time chart · Log Analytics* · reads `NTANetAnalytics`

#### Top talkers (allowed traffic)

*Table · Log Analytics* · reads `NTANetAnalytics`

Columns: Source, Source VM, Destination, Destination VM, GB, Flows.

When there is nothing to show: *No flow records in the time range (or Traffic Analytics does not write to this workspace).*

#### Top denied flows

*Table · Log Analytics* · reads `NTANetAnalytics`

When there is nothing to show: *No denied flows in the time range.*

> Coverage counts a flow log that targets the virtual network itself; one that targets a single subnet or network interface is not counted. The traffic panels read the Traffic Analytics table for VNet flow logs (`NTANetAnalytics`), not the older NSG flow log table.

## Tab: App Delivery

### Application Gateway

#### Application gateways

*Table · Azure Resource Graph*

Columns: Application gateway, Tier, State, Instances, Zones, Listeners, Backend pools, WAF policy, Provisioning, Resource Group, Location.

When there is nothing to show: *No application gateways found.*

#### Key metrics (over time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.network/applicationgateways`: Unhealthy backends (max) (max); Healthy backends (min) (min); Failed requests (sum); Total requests (sum); Total time (ms) (average); Capacity units (max) (max).

#### Unhealthy backends by pool

*Chart · Azure Monitor metrics* of `microsoft.network/applicationgateways`: UnhealthyHostCount (max, split by BackendSettingsPool).

#### Responses by status group

*Chart · Azure Monitor metrics* of `microsoft.network/applicationgateways`: ResponseStatus (sum, split by HttpStatusGroup).

#### Total time and backend response time (ms)

*Chart · Azure Monitor metrics* of `microsoft.network/applicationgateways`: ApplicationGatewayTotalTime (average); BackendLastByteResponseTime (average).

#### Capacity units and throughput

*Chart · Azure Monitor metrics* of `microsoft.network/applicationgateways`: CapacityUnits (max); Throughput (average).

### Azure Front Door

#### Front Door profiles

*Table · Azure Resource Graph*

Columns: Profile, Tier, State, Provisioning, Resource Group.

When there is nothing to show: *No Front Door profiles found.*

#### Key metrics (over time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.cdn/profiles`: Origin health % (average); 5xx % (average); 4xx % (average); Requests (sum); Total latency (ms) (average); Origin latency (ms) (average).

#### Origin health % by origin

*Chart · Azure Monitor metrics* of `microsoft.cdn/profiles`: OriginHealthPercentage (average, split by Origin).

#### 4xx and 5xx %

*Chart · Azure Monitor metrics* of `microsoft.cdn/profiles`: Percentage4XX (average); Percentage5XX (average).

#### Total and origin latency (ms)

*Chart · Azure Monitor metrics* of `microsoft.cdn/profiles`: TotalLatency (average); OriginLatency (average).

#### WAF requests by action

*Chart · Azure Monitor metrics* of `microsoft.cdn/profiles`: WebApplicationFirewallRequestCount (sum, split by Action).

### API Management

#### API Management services

*Table · Azure Resource Graph*

Columns: Service, Tier, Units, Network, Public access, Platform, Regions, Zones, Gateway URL, Provisioning, Resource Group, Location.

When there is nothing to show: *No API Management services found.*

#### Key metrics (over time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.apimanagement/service`: Capacity % (average); Requests (sum); Overall duration (ms) (average); Backend duration (ms) (average).

#### Requests by gateway response

*Chart · Azure Monitor metrics* of `microsoft.apimanagement/service`: Requests (sum, split by GatewayResponseCodeCategory).

#### Requests by backend response

*Chart · Azure Monitor metrics* of `microsoft.apimanagement/service`: Requests (sum, split by BackendResponseCodeCategory).

#### Overall and backend duration (ms)

*Chart · Azure Monitor metrics* of `microsoft.apimanagement/service`: Duration (average); BackendDuration (average).

#### Capacity %

*Chart · Azure Monitor metrics* of `microsoft.apimanagement/service`: Capacity (average).

#### API operations returning errors

*Table · Log Analytics* · reads `ApiManagementGatewayLogs`

When there is nothing to show: *No failed requests in the time range (or gateway logs are not sent to this workspace).*

> *Capacity* is the gateway's own load figure; Microsoft's guidance is to add units or scale up when it stays above about 70%. A 4xx from the gateway with a backend code of 0 was rejected by the gateway itself (authentication, rate limit or policy) and never reached the backend.

### Web Application Firewall

#### WAF policies

*Table · Azure Resource Graph*

Columns: Policy, Protects, Mode, State, Managed rule sets, Custom rules, Attached to, Resource Group.

When there is nothing to show: *No WAF policies found.*

> Select a **Log Analytics workspace** at the top to see the WAF rules that are matching requests.

#### Top WAF rule matches

*Table · Log Analytics* · reads `AGWFirewallLogs`, `AzureDiagnostics`

When there is nothing to show: *No WAF matches in the time range (or WAF logs are not sent to this workspace).*

> A policy in *Detection* mode logs matches but lets the request through. TLS certificates for both products are held in Key Vault or managed by Azure, so their expiry is not shown here.

## Tab: AI Foundry

#### AI Foundry and Azure OpenAI resources

*Table · Azure Resource Graph*

Columns: Resource, Kind, Sku, Public access, Private endpoints, Key access, Endpoint, Provisioning, Business owner, Subscription, Resource Group, Location.

When there is nothing to show: *No AI Foundry or Azure OpenAI resources found.*

#### Model deployments

*Table · Azure Resource Graph*

Columns: Account, Deployment, Model, Version, Deployment type, Capacity, Version upgrade, Provisioning, Resource Group.

When there is nothing to show: *No model deployments found.*

#### Hubs and projects (hub-based)

*Table · Azure Resource Graph*

Columns: Hub or project, Kind, Hub, Public access, Provisioning, Resource Group, Location.

When there is nothing to show: *No hub-based AI Foundry hubs or projects found.*

### Usage and performance

#### Key metrics (over time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.cognitiveservices/accounts`: Availability % (average); Calls (sum); Client errors (4xx) (sum); Server errors (5xx) (sum); Tokens processed (sum).

#### Requests by status code (429 = throttled)

*Chart · Azure Monitor metrics* of `microsoft.cognitiveservices/accounts`: AzureOpenAIRequests (sum, split by StatusCode).

#### Requests by deployment

*Chart · Azure Monitor metrics* of `microsoft.cognitiveservices/accounts`: AzureOpenAIRequests (sum, split by ModelDeploymentName).

#### Prompt and generated tokens

*Chart · Azure Monitor metrics* of `microsoft.cognitiveservices/accounts`: ProcessedPromptTokens (sum); GeneratedTokens (sum).

#### Tokens processed by deployment

*Chart · Azure Monitor metrics* of `microsoft.cognitiveservices/accounts`: TokenTransaction (sum, split by ModelDeploymentName).

#### Time to response (ms) by deployment

*Chart · Azure Monitor metrics* of `microsoft.cognitiveservices/accounts`: AzureOpenAITimeToResponse (average, split by ModelDeploymentName).

#### Provisioned utilisation % by deployment

*Chart · Azure Monitor metrics* of `microsoft.cognitiveservices/accounts`: AzureOpenAIProvisionedManagedUtilizationV2 (average, split by ModelDeploymentName).

> A deployment is throttled when it runs past its tokens-per-minute or requests-per-minute limit, which shows as status 429. *Provisioned utilisation* only has data for provisioned deployments; above 100% they start returning 429 too.

### Model quota

> Quota is granted per subscription, region and model, in thousands of tokens a minute, and is shared by every deployment of that model in the region. It is read from Azure Resource Manager for one subscription and region at a time.

#### Model quota used against limit

*Table · Azure Resource Manager*: `GET {FoundrySubscription}/providers/Microsoft.CognitiveServices/locations/{FoundryRegion}/usages`

Columns: Quota, Used, Limit.

When there is nothing to show: *No model quota returned for this subscription and region.*

> Select a **Log Analytics workspace** at the top to see the requests that failed or were throttled.

#### Requests that failed or were throttled

*Table · Log Analytics* · reads `AzureDiagnostics`

When there is nothing to show: *No failed requests in the time range (or request logs are not sent to this workspace).*

## Tab: Shared

### Azure Bastion

#### Bastion hosts

*Table · Azure Resource Graph*

Columns: Bastion, Sku, Scale Units, Tunneling, Ip Connect, Vnet, Provisioning, Resource Group, Location.

When there is nothing to show: *No Bastion hosts found.*

#### Bastion metrics (over time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.network/bastionhosts`: Communication status (average); Sessions (sum); CPU usage (average); Memory used (average).

#### Bastion sessions

*Chart · Azure Monitor metrics* of `microsoft.network/bastionhosts`: sessions (sum).

### DDoS Protection

#### Coverage

*Tiles · Azure Resource Graph*

#### DDoS protection plans

*Table · Azure Resource Graph*

Columns: Plan, Protected Vnets, Provisioning, Resource Group, Location.

When there is nothing to show: *No DDoS protection plans found.*

#### Under DDoS attack (1 = yes)

*Chart · Azure Monitor metrics* of `microsoft.network/publicipaddresses`: IfUnderDDoSAttack (max).

#### Packets dropped by DDoS mitigation

*Chart · Azure Monitor metrics* of `microsoft.network/publicipaddresses`: PacketsDroppedDDoS (max).

### DNS

#### DNS Private Resolvers

*Table · Azure Resource Graph*

Columns: Resolver, State, Vnet, Provisioning, Resource Group, Location.

When there is nothing to show: *No DNS Private Resolvers found.*

#### Private DNS zones (limits & links)

*Table · Azure Resource Graph*

Columns: Zone, Record Sets, Record sets % of limit, Links, VNet links % of limit, Registration Links, Resource Group.

When there is nothing to show: *No Private DNS zones found.*

### Private endpoints

#### Pe tiles

*Tiles · Azure Resource Graph*

#### Private endpoints needing attention

*Table · Azure Resource Graph*

Columns: Private endpoint, Connection, DNS, Provisioning, Target, Sub-resource, Resource Group.

When there is nothing to show: *Every private endpoint is approved, provisioned and has a private DNS zone group.*

#### Private Link DNS zones that exist more than once

*Table · Azure Resource Graph*

When there is nothing to show: *Each privatelink zone exists once.*

> An endpoint with no private DNS zone group has no record registered for it in the central zones, so its name resolves to the public address unless a record is kept by hand. A privatelink zone that exists twice splits resolution: a VNet linked to the extra copy cannot see the records in the central one.

### Key Vault

> The Key Vault and DDoS charts start with the first 10 key vaults and public IPs selected, because charting hundreds at once is slow. Choose others, or **All**, in the pickers at the top of this tab. The key vault inventory table below always lists every vault.

#### Key Vault metrics (over time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.keyvault/vaults`: Availability % (average); Saturation % (average); Latency (ms) (average); API hits (count).

#### API results by status code

*Chart · Azure Monitor metrics* of `microsoft.keyvault/vaults`: ServiceApiResult (count, split by StatusCode).

#### Availability %

*Chart · Azure Monitor metrics* of `microsoft.keyvault/vaults`: Availability (average).

#### Key vaults

*Table · Azure Resource Graph*

Columns: Key vault, Sku, Rbac, Soft Delete, Purge Protection, Public Network, Private Endpoints, Resource Group, Location.

When there is nothing to show: *No key vaults found.*

## Tab: Identity

### Microsoft Entra ID

> Select the **Log Analytics workspace** that receives the Entra ID diagnostic logs to see sign-ins, Conditional Access results, risky users and directory changes.

#### Entra tiles

*Tiles · Log Analytics* · reads `SigninLogs`

When there is nothing to show: *No interactive sign-ins in the time range (or Entra ID sign-in logs are not sent to this workspace).*

#### Interactive sign-ins by result

*Time chart · Log Analytics* · reads `SigninLogs`

#### Top reasons a sign-in did not succeed

*Table · Log Analytics* · reads `SigninLogs`

When there is nothing to show: *Every sign-in in the time range succeeded.*

#### Conditional Access policies blocking sign-ins

*Table · Log Analytics* · reads `SigninLogs`

When there is nothing to show: *No sign-ins were blocked by Conditional Access.*

#### Service principals failing to sign in

*Table · Log Analytics* · reads `AADServicePrincipalSignInLogs`

Columns: Service principal, Failures, Cause, Code, Error, Last seen, App ID.

When there is nothing to show: *No failed service principal sign-ins (or those logs are not sent to this workspace).*

#### Users at risk (risk changed in time range)

*Table · Log Analytics* · reads `AADRiskyUsers`

Columns: User, Risk level, Risk state, Risk detail, Updated.

When there is nothing to show: *No users at risk (or risky user logs are not sent to this workspace).*

#### Role, policy, credential and consent changes

*Table · Log Analytics* · reads `AuditLogs`

Columns: Category, Operation, Result, Changes, Actors, Last changed by, Last seen.

When there is nothing to show: *No role, policy, credential or consent changes in the time range.*

> These panels read the Entra ID diagnostic logs: `SigninLogs`, `AuditLogs`, `AADServicePrincipalSignInLogs` and `AADRiskyUsers`. A sign-in that is *not successful* includes interrupted ones, such as a prompt for multifactor authentication, as well as real failures; the reasons table tells them apart. Non-interactive sign-ins are not counted.

> Domain controller virtual machines are found by **name** using the *Domain controller name pattern* parameter at the top. A managed domain in Microsoft Entra Domain Services is listed without it.

### Microsoft Entra Domain Services

#### Managed domains by replica set

*Table · Azure Resource Graph*

Columns: Managed domain, Domain, Sku, Replica set, Service status, Health alerts, Health evaluated, Secure LDAP, Secure LDAP certificate expires, Provisioning.

When there is nothing to show: *No Microsoft Entra Domain Services managed domains found.*

### Domain controllers

#### Domain controller virtual machines

*Table · Azure Resource Graph* · reads `healthresources`

Columns: Domain controller, Health, Power, Size, Zone, Resource Group, Location.

When there is nothing to show: *No virtual machines matched the domain controller name pattern.*

#### Pending patches (Azure Update Manager)

*Table · Azure Resource Graph* · reads `patchassessmentresources`

Columns: Domain controller, Critical patches, Security patches, Reboot pending, Assessed.

When there is nothing to show: *No virtual machines matched the domain controller name pattern.*

#### Domain controller metrics (over time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.compute/virtualmachines`: VM availability (average); Avg CPU % (average); Avg free memory % (average); OS disk IOPS used % (average).

#### CPU %

*Chart · Azure Monitor metrics* of `microsoft.compute/virtualmachines`: Percentage CPU (average).

#### Available memory %

*Chart · Azure Monitor metrics* of `microsoft.compute/virtualmachines`: Available Memory Percentage (average).

> Select a **Log Analytics workspace** at the top to see domain controller heartbeats, directory service errors and failed logons.

#### Domain controller heartbeats

*Table · Log Analytics* · reads `Heartbeat`

When there is nothing to show: *No heartbeats from machines matching the domain controller name pattern.*

#### Directory, replication and DNS errors and warnings

*Table · Log Analytics* · reads `Event`

When there is nothing to show: *No errors or warnings (or these event logs are not collected from the domain controllers).*

#### Failed logons and account lockouts

*Time chart · Log Analytics* · reads `SecurityEvent`

## Tab: Agents

> Build agent scale sets are found by **name** using the *Build agent name pattern* parameter at the top. Azure DevOps scale set agent pools expect **Overprovision = false** and **Upgrade policy = Manual**.

#### Agent scale sets

*Table · Azure Resource Graph* · reads `computeresources`

Columns: Scale set, Sku, Capacity, Orchestration, Image, Overprovision, Upgrade Policy, Provisioning, Resource Group, Location.

When there is nothing to show: *No scale sets matched the build agent name pattern.*

#### Scale set metrics (over time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.compute/virtualmachinescalesets`: Avg CPU % (average); Avg free memory % (average); OS disk IOPS used % (average); OS disk queue depth (average); VM availability (average).

#### CPU %

*Chart · Azure Monitor metrics* of `microsoft.compute/virtualmachinescalesets`: Percentage CPU (average).

#### Available memory %

*Chart · Azure Monitor metrics* of `microsoft.compute/virtualmachinescalesets`: Available Memory Percentage (average).

#### OS disk IOPS consumed %

*Chart · Azure Monitor metrics* of `microsoft.compute/virtualmachinescalesets`: OS Disk IOPS Consumed Percentage (average).

#### Network in / out

*Chart · Azure Monitor metrics* of `microsoft.compute/virtualmachinescalesets`: Network In Total (sum); Network Out Total (sum).

#### Agent heartbeats (Azure Monitor Agent)

*Table · Log Analytics* · reads `Heartbeat`

When there is nothing to show: *No heartbeats — is the Azure Monitor Agent deployed to the agent scale sets?*

#### Free disk space (VM insights)

*Table · Log Analytics* · reads `InsightsMetrics`

Columns: Scale Set, Computer, Disk, Free Percent, Updated.

When there is nothing to show: *No disk data — requires VM insights on the agent scale sets.*

## Tab: AVS

#### Private clouds

*Table · Azure Resource Graph*

Columns: Private cloud, Sku, Mgmt Cluster Hosts, Network Block, Internet, Availability, Provisioning, Resource Group, Location.

When there is nothing to show: *No AVS private clouds found.*

> AVS requires **25% vSAN slack space** to stay within SLA — keep datastore usage below 75%.

#### Key metrics (over time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.avs/privateclouds`: CPU % (average); Memory % (average); vSAN used % (average); Datastore used (average); Datastore capacity (average).

#### CPU % by cluster

*Chart · Azure Monitor metrics* of `microsoft.avs/privateclouds`: EffectiveCpuAverage (average, split by clustername).

#### Memory % by cluster

*Chart · Azure Monitor metrics* of `microsoft.avs/privateclouds`: UsageAverage (average, split by clustername).

#### vSAN datastore used % by datastore

*Chart · Azure Monitor metrics* of `microsoft.avs/privateclouds`: DiskUsedPercentage (average, split by dsname).

## Tab: AVD

#### Host pools

*Table · Azure Resource Graph*

Columns: Host pool, Pool Type, Load Balancing, Max Sessions, App Group Type, Start Vm On Connect, Validation, Managed By, Resource Group, Location.

When there is nothing to show: *No AVD host pools found.*

> Select the **Log Analytics workspace** that receives AVD diagnostics to see session host health, sessions, errors and connection quality.

#### Session host status

*Tiles · Log Analytics* · reads `WVDAgentHealthStatus`

#### Session hosts (latest heartbeat)

*Table · Log Analytics* · reads `WVDAgentHealthStatus`

Columns: Session Host, Host Pool, Status, Last Heartbeat, Active Sessions, Inactive Sessions, Agent Version.

When there is nothing to show: *No AVD agent health data in this workspace.*

#### Connected sessions and users

*Time chart · Log Analytics* · reads `WVDConnections`

#### Connection round-trip time (ms)

*Time chart · Log Analytics* · reads `WVDConnectionNetworkData`

#### Connection success rate %

*Time chart · Log Analytics* · reads `WVDConnections`

#### Time to sign in, new sessions (seconds)

*Time chart · Log Analytics* · reads `WVDConnections`, `WVDCheckpoints`

#### Logon time by stage (seconds)

*Table · Log Analytics* · reads `WVDCheckpoints`

When there is nothing to show: *No logon stage data in the time range.*

#### Sessions by host pool (hosts reporting now)

*Table · Log Analytics* · reads `WVDAgentHealthStatus`

When there is nothing to show: *No session hosts are reporting.*

> Compare *Sessions on busiest host* with the pool's *MaxSessions* in the host pools table at the top: a host at its limit takes no more users. The slowest logon stages are usually profile load (FSLogix), group policy and logon scripts.

#### Top connection errors

*Table · Log Analytics* · reads `WVDErrors`

When there is nothing to show: *No AVD errors in the time range.*

#### Session host disk space (fullest first)

*Table · Log Analytics* · reads `WVDAgentHealthStatus`, `Perf`, `InsightsMetrics`, `Event`

Columns: Host, Volume, Kind, Free % (latest), Lowest free %, Free GB (latest), Low disk warnings, Last warning, Last report.

When there is nothing to show: *No disk counters from the session hosts (LogicalDisk in Perf, or VM insights).*

> A *mounted virtual disk* is a user's FSLogix profile or Office container (or an app attach package): when one fills, the user gets a low disk space warning in their session even though C: is fine. Grow it with FSLogix's *SizeInMBs* (new containers) or by expanding the VHDX. AVD Insights collects only `LogicalDisk(C:)`: add `LogicalDisk(*)` to the data collection rule to see the mounted disks, and the System event log (warnings) for the low disk warnings.

### Nerdio Manager

> For host pools run by **Nerdio Manager for Enterprise**. Its own resources are found by the *Nerdio Manager name pattern* and the hosts it manages by the *Nerdio tag prefix* (both at the top). Auto-scale runs as Nerdio's app registration, so its work shows in the activity log as automation starting, deallocating, draining and logging users off session hosts. Put Nerdio's application (client) id in *Nerdio Manager app id* to tell it apart from scaling plans and runbooks; *Who acts on the session hosts* shows the ids to choose from.

#### Nerdio Manager resources

*Table · Azure Resource Graph* · reads `healthresources`

Columns: Resource, Type, State, Resource Group, Location.

When there is nothing to show: *No resources match the Nerdio Manager name pattern in the selected subscriptions.*

#### Nerdio tiles

*Tiles · Azure Resource Graph*

When there is nothing to show: *No session hosts carry Nerdio's tags.*

#### Virtual machines managed by Nerdio

*Table · Azure Resource Graph*

Columns: Virtual machine, Nerdio object, Power, Auto-scale restriction, Scale-in restriction, Size, Resource Group, Location.

When there is nothing to show: *No virtual machines carry Nerdio's tags. Check the tag prefix at the top.*

#### Automated actions on session hosts

*Time chart · Log Analytics* · reads `WVDAgentHealthStatus`, `AzureActivity`

When there is nothing to show: *No automated actions on session hosts in the time range (needs AzureActivity).*

#### Who acts on the session hosts

*Table · Log Analytics* · reads `WVDAgentHealthStatus`, `AzureActivity`

When there is nothing to show: *No activity on session hosts in the time range.*

#### Failed scaling and session host actions

*Table · Log Analytics* · reads `WVDAgentHealthStatus`, `AzureActivity`

Columns: Time, Host, Action, Error, Message, Kind, Caller, Correlation id.

When there is nothing to show: *No failed actions on session hosts in the time range.*

> *AllocationFailed*, *ZonalAllocationFailed* and *SkuNotAvailable* mean Azure had no capacity for that size: scale-out stalls and users queue or fail with *no healthy session host*. *OperationNotAllowed* is usually a vCPU quota (see the Capacity tab).

#### Nerdio Manager application errors

*Table · Log Analytics* · reads `AppExceptions`, `AppRequests`

When there is nothing to show: *No errors from Nerdio Manager's Application Insights in this workspace (it must be workspace-based, and its workspace selected at the top).*

## Tab: Storage

#### Key metrics (over time range)

*Table, one row per resource · Azure Monitor metrics* of `microsoft.storage/storageaccounts`: Availability % (average); E2E latency (ms) (average); Server latency (ms) (average); Transactions (sum); Used capacity (average).

#### Availability %

*Chart · Azure Monitor metrics* of `microsoft.storage/storageaccounts`: Availability (average).

#### End-to-end latency (ms)

*Chart · Azure Monitor metrics* of `microsoft.storage/storageaccounts`: SuccessE2ELatency (average).

#### Transactions by response type (watch for throttling)

*Chart · Azure Monitor metrics* of `microsoft.storage/storageaccounts`: Transactions (sum, split by ResponseType).

#### Azure Files transactions by response type (FSLogix)

*Chart · Azure Monitor metrics* of `microsoft.storage/storageaccounts`: Transactions (sum, split by ResponseType).

> Azure Files capacity is reported hourly, so the two charts below need a time range of at least a few hours. A share whose used capacity is close to its quota stops FSLogix profiles from growing.

#### Azure Files used capacity by share

*Chart · Azure Monitor metrics* of `microsoft.storage/storageaccounts`: FileCapacity (average, split by FileShare).

#### Azure Files share quota by share

*Chart · Azure Monitor metrics* of `microsoft.storage/storageaccounts`: FileShareCapacityQuota (average, split by FileShare).

#### Storage accounts

*Table · Azure Resource Graph*

Columns: Storage account, Kind, Sku, Primary, Secondary, Public Network, Private Endpoints, Min Tls, Resource Group, Location.

## Tab: Governance

### Expiry & retirement

#### Service retirements affecting your resources (Azure Advisor)

*Table · Azure Resource Graph* · reads `advisorresources`

Columns: Retiring, Retirement date, Days left, Resources, Impact, Action.

When there is nothing to show: *Advisor reports no service retirements for the selected subscriptions.*

#### Planned maintenance and retirement notices (Azure Service Health)

*Table · Azure Resource Graph* · reads `servicehealthresources`

When there is nothing to show: *No active planned maintenance or retirement notices.*

#### AVD host pool registration tokens

*Table · Azure Resource Graph*

Columns: Host pool, Token, Expires, Resource Group, Location.

When there is nothing to show: *No AVD host pools found.*

> Select a **Log Analytics workspace** at the top to see Key Vault certificates, secrets and keys that are near expiry or expired.

#### Key Vault certificates, secrets and keys near expiry or expired

*Table · Log Analytics* · reads `AzureDiagnostics`, `AZKVAuditLogs`

When there is nothing to show: *No expiry events in the time range. Key Vault reports near-expiry once, about 30 days ahead, so use a 30-day time range; vaults must send audit logs to this workspace.*

#### Policy exemptions

*Table · Azure Resource Graph* · reads `policyresources`

Columns: Exemption, Status, Expires, Category, Assignment, Scope.

When there is nothing to show: *No policy exemptions in the selected subscriptions.*

> An expired exemption no longer applies, so the resources it covered count as non-compliant again. One with no expiry hides them from the compliance figure for good. *Waiver* means the non-compliance is accepted; *Mitigated* means the intent is met another way.

### Azure Policy

#### Compliance by subscription

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: Subscription, Compliant %, Non Compliant, Total.

#### Top non-compliant policies

*Table · Azure Resource Graph* · reads `policyresources`

Columns: Policy, Resources, Assignments.

When there is nothing to show: *No non-compliant resources.*

### Landing zone hygiene

#### Subscriptions by management group

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Subscription, Placement, Management group, Depth, State.

#### Platform resources protected by a lock, by service

*Table · Azure Resource Graph*

Columns: Service, Resources, Locked, Not locked, Locked %.

#### Orphaned resources

*Table · Azure Resource Graph*

Columns: Resource, Kind, Detail, Resource Group, Location.

When there is nothing to show: *No unattached disks, unused public IPs or unattached network interfaces.*

#### Empty resource groups

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Resource group, Subscription, Location.

When there is nothing to show: *No empty resource groups.*

> A lock at the resource, its resource group or its subscription counts. A resource group is *empty* when Resource Graph sees no resources in it; a few resource types are not indexed, so check before deleting one.

### Patch compliance (Azure Update Manager)

> Covers virtual machines and Arc-enabled servers in the selected subscriptions: AVD session hosts, domain controllers and build agents on Flexible scale sets. Update Manager does not assess Uniform scale set instances. Machines show as *Not assessed* until periodic assessment is turned on.

#### Patch tiles

*Tiles · Azure Resource Graph* · reads `patchassessmentresources`

#### Pending patches by machine

*Table · Azure Resource Graph* · reads `patchassessmentresources`

Columns: Machine, OS, Assessment, Assessed, Critical, Security, Other, Reboot pending, Patch mode, Resource Group.

When there is nothing to show: *No virtual machines or Arc-enabled servers found.*

### Azure Advisor

#### High & medium impact recommendations

*Table · Azure Resource Graph* · reads `advisorresources`

Columns: Category, Impact, Problem, Resource, Updated.

## Tab: Security

### Microsoft Defender for Cloud

#### Secure score by subscription

*Table · Azure Resource Graph* · reads `securityresources`, `resourcecontainers`

Columns: Subscription, Score %, Current, Max.

#### Security controls with unhealthy resources

*Table · Azure Resource Graph* · reads `securityresources`

#### Active security alerts

*Table · Azure Resource Graph* · reads `securityresources`

Columns: Severity, Alert, Entity, Started, Tactics.

When there is nothing to show: *No active security alerts.*

#### Unhealthy recommendations (high & medium)

*Table · Azure Resource Graph* · reads `securityresources`

#### Defender plans by subscription

*Table · Azure Resource Graph* · reads `securityresources`, `resourcecontainers`

Columns: Subscription, Plans on, Plans off, Plans on %.

#### Defender plans switched off

*Table · Azure Resource Graph* · reads `securityresources`, `resourcecontainers`

Columns: Subscription, Plan.

When there is nothing to show: *Every Defender plan is on in every selected subscription.*

### Privileged access

#### Privileged tiles

*Tiles · Azure Resource Graph* · reads `authorizationresources`

#### Owner and access administrator assignments at subscription scope or above

*Table · Azure Resource Graph* · reads `authorizationresources`, `resourcecontainers`

Columns: Scope level, Scope, Role, Users (direct), Groups, Service principals.

When there is nothing to show: *No Owner or access administrator assignments at subscription scope or above.*

> Counts role assignments that are active now, for Owner, User Access Administrator and Role Based Access Control Administrator. Eligible assignments in Privileged Identity Management are not role assignments until activated, so they are not counted. Resource Graph holds principal IDs only: it cannot name the principals or tell whether one has been deleted.

### Microsoft Sentinel

#### Workspaces with Sentinel enabled

*Table · Azure Resource Graph*

Columns: Workspace, Provisioning, Resource Group, Location.

When there is nothing to show: *No workspace with the Sentinel solution found in the selected subscriptions.*

> Select the **Sentinel workspace** as the Log Analytics workspace at the top to see incidents and Sentinel health.

#### Open incidents by severity

*Tiles · Log Analytics* · reads `SecurityIncident`

When there is nothing to show: *No open incidents that changed in the time range.*

#### Open incidents

*Table · Log Analytics* · reads `SecurityIncident`

Columns: Incident, Title, Severity, Status, Owner, Created, Age (hours), Provider, Link.

When there is nothing to show: *No open incidents that changed in the time range.*

#### Incidents created and closed per day

*Bar chart · Log Analytics* · reads `SecurityIncident`

#### Closed incidents: time to close and classification

*Table · Log Analytics* · reads `SecurityIncident`

When there is nothing to show: *No incidents were closed in the time range.*

#### Data connectors, analytics rules and automation that are failing

*Table · Log Analytics* · reads `SentinelHealth`

When there is nothing to show: *No failures recorded (or Sentinel health monitoring is not turned on for this workspace).*

> Incidents are read from the selected workspace for the time range, so an incident that has not changed within it is not listed: use a longer range to see old open incidents.

## Tab: Monitoring

### Log Analytics

#### Workspaces

*Table · Azure Resource Graph*

Columns: Workspace, Sku, Retention Days, Daily Cap GB, Ingestion, Public Ingestion, Resource Group, Location.

> Select a **Log Analytics workspace** at the top to see ingestion, workspace errors and agent heartbeats.

#### Billable ingestion by table (GB)

*Bar chart · Log Analytics* · reads `Usage`

#### Top tables (GB)

*Table · Log Analytics* · reads `Usage`

#### Workspace health issues (Operation table)

*Table · Log Analytics* · reads `Operation`

When there is nothing to show: *No workspace warnings or errors.*

#### Agent heartbeats

*Table · Log Analytics* · reads `Heartbeat`

### Agents and data collection

#### Azure Monitor Agent and data collection rules by machine

*Table · Azure Resource Graph* · reads `insightsresources`

Columns: Machine, Status, Kind, OS, Agent, Agent version, Data collection rules, Rule names, Resource Group.

When there is nothing to show: *No virtual machines, scale sets or Arc-enabled servers found.*

#### Data collection rules

*Table · Azure Resource Graph* · reads `insightsresources`

Columns: Rule, Kind, Associations, Data flows, First workspace, Workspaces, Provisioning, Resource Group.

When there is nothing to show: *No data collection rules found.*

> Scale sets show whether the agent is in the scale set model; their instances are not listed individually. A rule with no associations collects nothing, which is expected only for workspace transformation and direct-ingestion rules.

### Log sources

> Shows whether each platform resource is actually writing to the selected workspace. *No logs* means nothing arrived in the time range: the diagnostic setting is missing, points at another workspace, or the resource stopped sending. *Stale* means nothing in the last day. The inventory covers every subscription you can read (up to 1,000 resources), not only the ones selected at the top, and both queries scan every table, so they are slow on long time ranges.

#### Platform resources by last record in the workspace

*Table · Log Analytics*

Columns: Resource, Status, Last record, Tables, Type, Resource Group.

#### Ingestion delay by table (last 24 hours at most)

*Table · Log Analytics*

### Alerting coverage

> *Fired alerts* on the Overview only shows rules that exist. This shows where nothing would fire. A resource is covered **directly** by an enabled metric or log search rule scoped to it, or by **inheritance** from a metric rule scoped to its resource group or subscription that targets its type. Log search rules scoped to a workspace and activity log (Resource Health, Service Health) alerts scoped to a subscription can't be tied to one resource, so they aren't counted; *Notification path* below shows which subscriptions have them. A rule with no action group may still notify through an alert processing rule.

#### Platform resources by alert rule coverage

*Table · Azure Resource Graph*

Columns: Resource, Service, Coverage, Direct rules, Inherited rules, Resource Group.

When there is nothing to show: *No platform resources found in the selected subscriptions.*

#### Alert rules that are disabled or have no action group

*Table · Azure Resource Graph*

Columns: Alert rule, Kind, Problem, Severity, Scopes, Resource Group.

When there is nothing to show: *Every alert rule is enabled and has an action group.*

#### Alerts fired per day by severity (time range, up to 30 days)

*Bar chart · Azure Resource Graph* · reads `alertsmanagementresources`

When there is nothing to show: *No alerts fired on platform resources in the time range.*

#### Alert rules that fire most

*Table · Azure Resource Graph* · reads `alertsmanagementresources`

When there is nothing to show: *No alerts fired on platform resources in the time range.*

### Notification path

#### Action groups

*Table · Azure Resource Graph*

Columns: Action group, Status, Alert rules using it, Email, SMS / voice / push, ARM role, Webhook, Automation (Logic App, Function, runbook, Event Hub, ITSM), Resource Group.

When there is nothing to show: *No action groups found.*

#### Service Health and Resource Health alerts by subscription

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Subscription, Status, Service Health alerts, Resource Health alerts.

### Backup & Site Recovery

#### Recovery Services vaults

*Table · Azure Resource Graph*

Columns: Vault, Redundancy, Cross Region Restore, Soft Delete, Immutability, Public Network, Provisioning, Resource Group, Location.

When there is nothing to show: *No Recovery Services vaults found.*

#### Backup jobs not completed (time range)

*Table · Azure Resource Graph* · reads `recoveryservicesresources`

Columns: Vault, Item, Operation, Status, Started, Error.

When there is nothing to show: *All backup jobs in the time range completed.*

#### Protected items

*Table · Azure Resource Graph* · reads `recoveryservicesresources`

Columns: Vault, Item, Workload Type, Health, Last Backup, Last Backup Time, Protection.

When there is nothing to show: *No protected items.*

#### Virtual machines by backup protection

*Table · Azure Resource Graph* · reads `recoveryservicesresources`

Columns: Virtual machine, Protection, Vault, Last backup, OS, Power, Resource Group, Location.

When there is nothing to show: *No virtual machines found.*

> Pooled AVD session hosts and scale set build agents are normally rebuilt from an image, so *Not protected* is expected for them.

#### Site Recovery replicated items

*Table · Azure Resource Graph* · reads `recoveryservicesresources`

Columns: Vault, Item, Health, State, Active Location.

When there is nothing to show: *No Site Recovery replicated items.*

## Tab: Capacity

> Headroom against limits that stop a deployment or a scale-out when they are reached. Capacity of the services themselves is on their own tabs: hub routing units (Virtual WAN), SNAT ports (Firewall), circuit utilisation (ExpressRoute), Private DNS zone limits (Shared), vSAN (AVS) and Azure Files share quota (Storage).

### Compute quotas

#### vCPU and compute quotas in use, by subscription and region

*Table · Azure Resource Graph* · reads `quotaresources`, `resourcecontainers`

Columns: Subscription, Region, Quota, Used, Limit, Used %.

When there is nothing to show: *No compute quota is in use in the selected subscriptions.*

### Network quotas

> Network usage is not in Resource Graph, so this reads it from Azure Resource Manager for one subscription and region at a time.

#### Network quotas (public IPs, VNets, route tables, private endpoints...)

*Table · Azure Resource Manager*: `GET {QuotaSubscription}/providers/Microsoft.Network/locations/{QuotaRegion}/usages`

Columns: Quota, Used, Limit.

When there is nothing to show: *No network usage returned for this subscription and region.*

### Cost

> Month-to-date spend for the subscription selected under *Network quotas*, read from Cost Management. It covers everything in that subscription, so it is platform cost only when the subscription holds only platform resources.

#### Cost by service, month to date

*Table · Azure Resource Manager*: `POST {QuotaSubscription}/providers/Microsoft.CostManagement/query`

Columns: Service, Cost, Currency.

When there is nothing to show: *Cost Management returned no cost for this subscription this month.*

#### Budgets

*Table · Azure Resource Manager*: `GET {QuotaSubscription}/providers/Microsoft.Consumption/budgets`

Columns: Budget, Amount, Spent, Forecast, Currency, Period.

When there is nothing to show: *No budgets are defined on this subscription.*

### Subnet address space

> *Used* counts the IP configurations attached to each subnet (NICs, private endpoints, load balancer front ends). Application Gateway instances and delegated services such as SQL Managed Instance take addresses that are not counted, and Virtual WAN hubs do not expose their address usage at all.

#### Subnets by address utilisation

*Table · Azure Resource Graph*

Columns: Virtual network, Subnet, Prefix, Used, Usable, Used %, Delegation, Resource Group.

When there is nothing to show: *No virtual network subnets found.*

## Tab: Throughput

> Traffic across the platform's network edge and data services for the selected time range.

#### Azure Firewall data processed

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: DataProcessed (sum).

#### Azure Firewall throughput

*Chart · Azure Monitor metrics* of `microsoft.network/azurefirewalls`: Throughput (average).

#### ExpressRoute circuits (bits/s in & out)

*Chart · Azure Monitor metrics* of `microsoft.network/expressroutecircuits`: BitsInPerSecond (average); BitsOutPerSecond (average).

#### ExpressRoute gateway throughput (bits/s)

*Chart · Azure Monitor metrics* of `microsoft.network/expressroutegateways`: ExpressRouteGatewayBitsPerSecond (average).

#### VPN gateway S2S bandwidth

*Chart · Azure Monitor metrics* of `microsoft.network/vpngateways`: AverageBandwidth (average).

#### VPN tunnel bandwidth by connection

*Chart · Azure Monitor metrics* of `microsoft.network/vpngateways`: TunnelAverageBandwidth (average, split by ConnectionName).

#### P2S VPN bandwidth

*Chart · Azure Monitor metrics* of `microsoft.network/p2svpngateways`: P2SBandwidth (average).

#### Storage ingress / egress

*Chart · Azure Monitor metrics* of `microsoft.storage/storageaccounts`: Ingress (sum); Egress (sum).

#### AVD available bandwidth (KBps)

*Time chart · Log Analytics* · reads `WVDConnectionNetworkData`
