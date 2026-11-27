"""Generates the public IP addresses workbook.

Run:  python src/build_public_ip.py
Out:  workbook/public-ip.workbook.json

Every public IP address and public IP prefix in the estate: what each one is attached to, which addresses are
paid for but unused, which are on the retired Basic SKU or pinned to one zone, whether DDoS Protection covers
them, how much traffic they carry, and who changed them. A *Find an IP* tab answers "whose address is this?"
for an IP address or DNS name, including the addresses Azure manages for you (App Service outbound addresses,
secured virtual hub firewalls, Virtual WAN VPN gateways) that are not public IP resources. From Resource Graph,
Azure Monitor metrics and, for DDoS mitigation logs, Log Analytics. Built from the helpers in build_workbook.py so
the workbooks look alike.
"""

import pathlib

from build_workbook import (AVG, DAY_MS, MAX, ONE_TILE, PROVISIONING, SUBSCRIPTION_NAMES, SUM, WORKSPACE_UNSET,
                            arg, big_number_tiles, free_text_param, gid, group, la, m, metric_grid, metrics,
                            notebook, params, resource_link, resource_param, status_fmt, subscription_param, text,
                            time_param, when_set, workspace_param, write_workbook)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "public-ip.workbook.json"

P = "pip"

PNS = "microsoft.network/publicipaddresses"

TABS = [
    ("overview", "Overview"),
    ("inventory", "Inventory"),
    ("find", "Find an IP"),
    ("cleanup", "Clean-up & cost"),
    ("ddos", "DDoS protection"),
    ("traffic", "Traffic"),
    ("changes", "Changes"),
]

# ---------------------------------------------------------------------------
# What each public IP is attached to (Resource Graph)
# ---------------------------------------------------------------------------

# A public IP records the IP configuration that uses it, or the NAT gateway. The owning resource is that
# configuration's id cut after the resource's own name; a NIC is then replaced by its virtual machine below. An
# AKS cluster's load balancer is always called kubernetes, in the cluster's node resource group.
CLASSIFY = r"""
| extend config = tolower(tostring(properties.ipConfiguration.id)), nat = tolower(tostring(properties.natGateway.id))
| extend Owner = iff(isnotempty(nat), nat,
        extract(@'^(/subscriptions/[^/]+/resourcegroups/[^/]+/providers/[^/]+/[^/]+/[^/]+)', 1, config)),
    AttachedTo = case(
        isnotempty(nat), 'NAT gateway',
        config contains '/virtualmachinescalesets/', 'VM scale set',
        config contains '/networkinterfaces/', 'Virtual machine',
        config contains '/loadbalancers/kubernetes/', 'AKS load balancer',
        config contains '/loadbalancers/', 'Load balancer',
        config contains '/applicationgateways/', 'Application gateway',
        config contains '/azurefirewalls/', 'Azure Firewall',
        config contains '/bastionhosts/', 'Bastion',
        config contains '/virtualnetworkgateways/', 'VPN or ExpressRoute gateway',
        config contains '/virtualhubs/', 'Virtual hub (route server)',
        isnotempty(config), 'Other',
        'Not attached')"""

# The NIC's virtual machine, or 'NIC with no VM' for a NIC left behind when its VM was deleted (still billed).
NIC_TO_VM = r"""
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/networkinterfaces'
    | project Owner = tolower(id), vm = tolower(tostring(properties.virtualMachine.id))
  ) on Owner
| extend AttachedTo = iff(AttachedTo == 'Virtual machine' and isempty(vm), 'NIC with no VM', AttachedTo),
    Owner = iff(isnotempty(vm), vm, Owner)"""

PIP_COLUMNS = r"""
| extend IP = tostring(properties.ipAddress),
    Version = tostring(properties.publicIPAddressVersion),
    Sku = tostring(sku.name),
    Tier = tostring(sku.tier),
    Allocation = tostring(properties.publicIPAllocationMethod),
    Zones = case(array_length(zones) >= 2, 'Zone-redundant', array_length(zones) == 1, strcat('Zone ', tostring(zones[0])),
        'No zone set'),
    Ddos = iff(sku.name =~ 'Basic', 'n/a (Basic)', coalesce(tostring(properties.ddosSettings.protectionMode), 'VirtualNetworkInherited')),
    DnsName = tostring(properties.dnsSettings.fqdn),
    Prefix = tostring(properties.publicIPPrefix.id),
    IpTags = replace_string(replace_string(replace_regex(tostring(properties.ipTags), @'[\[\]{}"]', ''), 'ipTagType:', ''),
        ',tag:', '='),
    IdleMinutes = toint(properties.idleTimeoutInMinutes),
    Provisioning = tostring(properties.provisioningState)"""

PIP_BASE = "resources\n| where type =~ 'microsoft.network/publicipaddresses'" + CLASSIFY
PIPS = PIP_BASE + NIC_TO_VM + PIP_COLUMNS + SUBSCRIPTION_NAMES

UNUSED = "AttachedTo in ('Not attached', 'NIC with no VM')"

PREFIXES = r"""
resources
| where type =~ 'microsoft.network/publicipprefixes'
| extend Length = toint(properties.prefixLength), Version = tostring(properties.publicIPAddressVersion)
| extend Size = iff(Version =~ 'IPv6', real(null), pow(2, 32 - Length)), Used = array_length(properties.publicIPAddresses)
| project id, Prefix = tostring(properties.ipPrefix), Version, Size = toint(Size), Used,
    Free = toint(Size - Used), UsedPct = iff(Size > 0, round(100.0 * Used / Size, 0), real(null)),
    Zones = case(array_length(zones) >= 2, 'Zone-redundant', array_length(zones) == 1, strcat('Zone ', tostring(zones[0])),
        'No zone set'),
    Custom = iff(isnotempty(tostring(properties.customIPPrefix.id)), 'Your own range (BYOIP)', 'Microsoft'),
    Provisioning = tostring(properties.provisioningState), subscriptionId, ResourceGroup = resourceGroup,
    Location = location"""

# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

TILES_Q = PIPS + r"""
| summarize Total = count(), V6 = countif(Version =~ 'IPv6'), Regions = dcount(location),
    Unused = countif(""" + UNUSED + r"""), Basic = countif(Sku =~ 'Basic'),
    Zonal = countif(Zones startswith 'Zone '), Disabled = countif(Ddos =~ 'Disabled'),
    OnVms = countif(AttachedTo == 'Virtual machine')
| extend Price = todouble(trim(@'\s+', '{Price}'))
| extend rows = pack_array(
    pack('Order', 1, 'Signal', 'Public IP addresses', 'Value', Total, 'State', 'Unknown',
        'Detail', strcat(Total - V6, ' IPv4 · ', V6, ' IPv6 · ', Regions, ' regions')),
    pack('Order', 2, 'Signal', 'Not in use', 'Value', Unused, 'State', iff(Unused > 0, 'Degraded', 'Available'),
        'Detail', iff(isnull(Price), 'set a price at the top', strcat('about ', toint(round(Unused * Price, 0)), ' a month'))),
    pack('Order', 3, 'Signal', 'Basic SKU (retired)', 'Value', Basic, 'State', iff(Basic > 0, 'Unavailable', 'Available'),
        'Detail', 'upgrade to Standard'),
    pack('Order', 4, 'Signal', 'Pinned to one zone', 'Value', Zonal, 'State', iff(Zonal > 0, 'Degraded', 'Available'),
        'Detail', 'lost if that zone fails'),
    pack('Order', 5, 'Signal', 'DDoS protection disabled', 'Value', Disabled, 'State', iff(Disabled > 0, 'Degraded', 'Available'),
        'Detail', 'turned off on the IP itself'),
    pack('Order', 6, 'Signal', 'On virtual machines', 'Value', OnVms, 'State', 'Unknown',
        'Detail', 'reachable from the internet if an NSG allows'))
| mv-expand r = rows
| project Order = toint(r.Order), Signal = tostring(r.Signal), Value = toint(r.Value), State = tostring(r.State),
    Detail = tostring(r.Detail)
| order by Order asc
"""

PREFIX_TILE_Q = PREFIXES + r"""
| summarize Prefixes = count(), Free = sum(Free), Unused = countif(Used == 0)
| project Signal = 'Free addresses in prefixes', Value = Free,
    State = iff(Unused > 0, 'Degraded', 'Unknown'),
    Detail = strcat('in ', Prefixes, ' prefixes · ', Unused, ' wholly unused')
"""

BY_ATTACHED_Q = PIPS + "\n| summarize PublicIPs = count() by AttachedTo\n| order by PublicIPs desc"
BY_REGION_Q = PIPS + "\n| summarize PublicIPs = count() by Region = location\n| order by PublicIPs desc"

# One row per problem per public IP, worst first.
ATTENTION_Q = PIPS + r"""
| extend Issues = array_concat(
    iff(AttachedTo == 'Not attached', dynamic(['Not attached']), dynamic([])),
    iff(AttachedTo == 'NIC with no VM', dynamic(['On a NIC with no VM']), dynamic([])),
    iff(Sku =~ 'Basic', dynamic(['Basic SKU']), dynamic([])),
    iff(Zones startswith 'Zone ', dynamic(['Pinned to one zone']), dynamic([])),
    iff(Ddos =~ 'Disabled', dynamic(['DDoS protection disabled']), dynamic([])),
    iff(Provisioning !~ 'Succeeded', dynamic(['Provisioning failed']), dynamic([])))
| mv-expand Issue = Issues to typeof(string)
| where isnotempty(Issue)
| extend Fix = case(
    Issue == 'Not attached', 'Delete it, unless the address is kept on purpose (allow-listed by a partner, a DNS record)',
    Issue == 'On a NIC with no VM', 'Delete the NIC left behind by a deleted VM, then the IP',
    Issue == 'Basic SKU', 'Upgrade to Standard (Basic was retired on 30 September 2025); the address is kept if it is static',
    Issue == 'Pinned to one zone', 'Replace with a zone-redundant IP when the service is next rebuilt',
    Issue == 'DDoS protection disabled', 'Set DDoS protection to Inherited from virtual network, or enable IP Protection',
    'See the resource')
| project Issue, id, IP, AttachedTo, Owner, Sku, Zones, Fix, Subscription, ResourceGroup = resourceGroup
| order by case(Issue == 'Basic SKU', 0, Issue == 'Provisioning failed', 1, Issue in ('Not attached', 'On a NIC with no VM'), 2, 3) asc, Issue asc
"""

ISSUE = status_fmt("Issue", warn=["Not attached", "On a NIC with no VM", "Pinned to one zone", "DDoS protection disabled"],
                   bad=["Basic SKU", "Provisioning failed"])
ZONES = status_fmt("Zones", good=["Zone-redundant"], warn=["Zone 1", "Zone 2", "Zone 3"], neutral=["No zone set"])
ATTACHED = status_fmt("AttachedTo", warn=["Not attached", "NIC with no VM"])
SKU = status_fmt("Sku", good=["Standard"], bad=["Basic"])
PIP_LABELS = {"id": "Public IP", "IP": "Address", "AttachedTo": "Attached to", "Owner": "Used by", "Sku": "SKU",
              "Ddos": "DDoS protection", "DnsName": "DNS name", "Prefix": "From prefix", "IpTags": "IP tags",
              "IdleMinutes": "Idle timeout (min)", "ResourceGroup": "Resource group"}

ZONES_NOTE = """\
**Zones.** *Zone-redundant* survives the loss of a zone; *Zone 1/2/3* is pinned to that zone and goes down
with it. *No zone set* is either a region without availability zones or an IP created without a zone: Microsoft
has been making Standard IPs created without a zone zone-redundant in regions that have zones, but Resource Graph
still shows no zones for them, so check the IP's *Overview* blade before replacing it. A zone cannot be changed on
an existing IP: it has to be recreated, which changes the address."""

# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

INVENTORY_Q = PIPS + r"""
| project id, IP, AttachedTo, Owner, DnsName, Sku, Tier, Allocation, Version, Zones, Ddos, Prefix, IpTags,
    IdleMinutes, Provisioning, Subscription, ResourceGroup = resourceGroup, Location = location
| order by AttachedTo asc, tostring(id) asc
"""

# ---------------------------------------------------------------------------
# Find an IP
# ---------------------------------------------------------------------------

# Matches an address (or a DNS name) against public IP resources and prefixes, and against the addresses Azure
# manages itself, which are not public IP resources: App Service outbound addresses (every address the app may use,
# shared with other apps on the same scale unit), the public addresses of a secured virtual hub's firewall, and
# Virtual WAN VPN gateways. Resource Graph has no `let`, so the search value is trimmed in each comparison.
FIND_Q = r"""
resources
| where type in~ ('microsoft.network/publicipaddresses', 'microsoft.network/publicipprefixes', 'microsoft.web/sites',
    'microsoft.network/azurefirewalls', 'microsoft.network/vpngateways')
| extend q = tolower(trim(@'[\s.]+', '{Search}'))
| extend fqdn = tolower(trim_end(@'\.', tostring(properties.dnsSettings.fqdn)))
| extend Match = case(
    type =~ 'microsoft.network/publicipaddresses' and (tostring(properties.ipAddress) == q or fqdn == q), 'Public IP address',
    type =~ 'microsoft.network/publicipprefixes' and isnotnull(parse_ipv4(q))
        and ipv4_is_in_range(q, tostring(properties.ipPrefix)), strcat('Inside public IP prefix ', tostring(properties.ipPrefix)),
    type =~ 'microsoft.web/sites' and strcat(',', tostring(properties.possibleOutboundIpAddresses), ',') contains strcat(',', q, ','),
        'App Service outbound address (may be shared with other apps)',
    type =~ 'microsoft.network/azurefirewalls' and tostring(properties.hubIPAddresses.publicIPs.addresses) contains strcat('"', q, '"'),
        'Secured virtual hub firewall',
    type =~ 'microsoft.network/vpngateways' and tostring(properties.ipConfigurations) contains strcat('"', q, '"'),
        'Virtual WAN VPN gateway',
    '')
| where isnotempty(Match)
| extend config = tolower(tostring(properties.ipConfiguration.id)), nat = tolower(tostring(properties.natGateway.id))
| extend UsedBy = case(type !~ 'microsoft.network/publicipaddresses', '', isnotempty(nat), nat,
    extract(@'^(/subscriptions/[^/]+/resourcegroups/[^/]+/providers/[^/]+/[^/]+/[^/]+)', 1, config))
| extend UsedBy = iff(type =~ 'microsoft.network/publicipaddresses' and isempty(UsedBy), 'Not attached', UsedBy)
| project Match, id, Address = coalesce(tostring(properties.ipAddress), tostring(properties.ipPrefix), q), UsedBy,
    DnsName = tostring(properties.dnsSettings.fqdn), subscriptionId, ResourceGroup = resourceGroup, Location = location
""" + SUBSCRIPTION_NAMES + r"""
| project-away subscriptionId, subscriptionId1
"""

FIND_HOWTO = """\
Type an **IP address** or a public IP's **DNS name** (for example `myapp.westeurope.cloudapp.azure.com`) in
*Find* at the top. The search covers public IP addresses and prefixes in the selected subscriptions, and also the
addresses Azure manages for you that are not public IP resources: App Service outbound addresses, the public
addresses of secured virtual hub firewalls (Virtual WAN), and Virtual WAN VPN gateways."""

FIND_NOT_FOUND = ("The address is not in the selected subscriptions. It may belong to a subscription you cannot "
                  "read, be a Microsoft-owned address shared by a platform service (check the Azure IP ranges and "
                  "service tags download), or not be an Azure address at all.")

FIND_NOTE = """\
**Not covered:** addresses Azure assigns to a service without a public IP resource, other than those above:
default outbound access of VMs with no public IP, NAT gateway or load balancer (a Microsoft-owned address that can
change, retired for new VNets from 30 September 2025), Azure Front Door and API Management's shared addresses,
and the ExpressRoute and VPN gateways' own management addresses."""

# ---------------------------------------------------------------------------
# Clean-up and cost
# ---------------------------------------------------------------------------

UNUSED_Q = PIPS + r"""
| where """ + UNUSED + r"""
| extend Price = todouble(trim(@'\s+', '{Price}'))
| project id, IP, AttachedTo, Owner, Sku, Allocation, DnsName, Prefix,
    PerMonth = iff(Sku =~ 'Basic' and Allocation =~ 'Dynamic', 0.0, Price),
    Kept = iff(isnotempty(tostring(tags)) and tostring(tags) has_any ('keep', 'reserved', 'allowlist', 'whitelist', 'dr'), 'Tagged as kept', ''),
    Subscription, ResourceGroup = resourceGroup, Location = location
| order by Kept asc, Subscription asc
"""

BASIC_Q = PIPS + r"""
| where Sku =~ 'Basic'
| project id, IP, AttachedTo, Owner, Allocation, DnsName, Subscription, ResourceGroup = resourceGroup, Location = location
| order by AttachedTo asc
"""

UNUSED_PREFIXES_Q = PREFIXES + "\n| where Used == 0 or UsedPct < 50\n| order by Used asc, Free desc"

ADVISOR_Q = r"""
advisorresources
| where type =~ 'microsoft.advisor/recommendations'
| extend rid = tolower(tostring(properties.resourceMetadata.resourceId))
| where rid contains '/microsoft.network/publicipaddresses/' or rid contains '/microsoft.network/publicipprefixes/'
| project id = rid, Category = tostring(properties.category), Impact = tostring(properties.impact),
    Problem = tostring(properties.shortDescription.problem), Solution = tostring(properties.shortDescription.solution),
    Updated = todatetime(properties.lastUpdated)
| order by case(Impact =~ 'High', 0, Impact =~ 'Medium', 1, 2) asc
"""

COST_NOTE = """\
**What an unused address costs.** A Standard public IP is billed by the hour whether or not it is attached,
about 3.65 a month in US dollars at list price (set *Price per IP a month* at the top to your own rate). A
dynamic Basic IP is free while unattached, but Basic is retired. An IP taken from a **public IP prefix** is paid
for through the prefix, which bills for every address in it whether used or not, so deleting the IP alone saves
nothing: reuse it, or shrink the prefix.

Before deleting, check the address is not kept on purpose: allow-listed by a partner or a SaaS provider, held for
disaster recovery, or behind a DNS record (a deleted address left in DNS is a subdomain takeover risk). Rows tagged
with *keep*, *reserved*, *allowlist* or *dr* are listed last."""

BASIC_NOTE = """\
Basic SKU public IPs were retired on **30 September 2025**: they no longer have an SLA or support, and Microsoft
may stop them working. Upgrade a static Basic IP to Standard in place (the address is kept); a dynamic one must be
made static first, and a Basic IP on a Basic load balancer or VPN gateway is upgraded with that resource. Standard
IPs are closed to inbound traffic unless an NSG allows it, so add the NSG rules the service needs before upgrading
an IP on a VM."""

# ---------------------------------------------------------------------------
# DDoS protection
# ---------------------------------------------------------------------------

# A public IP's effective protection: IP Protection on the IP itself, or (by default) whatever its VNet has. The VNet
# is found from the subnet of the resource using the IP. A load balancer's public frontend takes the protection of
# its backend's VNet, which is not resolved here.
# Resource Graph allows three joins in a query, so the NIC's virtual machine is read in the same join as the VNet.
DDOS_Q = PIP_BASE + r"""
| join kind=leftouter (
    resources
    | where type in~ ('microsoft.network/networkinterfaces', 'microsoft.network/azurefirewalls', 'microsoft.network/bastionhosts',
        'microsoft.network/virtualnetworkgateways', 'microsoft.network/applicationgateways')
    | extend cfgs = iff(type =~ 'microsoft.network/applicationgateways', properties.gatewayIPConfigurations, properties.ipConfigurations)
    | mv-expand cfg = cfgs
    | extend Vnet = tolower(extract(@'(?i)^(.*/virtualnetworks/[^/]+)/subnets/', 1, tostring(cfg.properties.subnet.id)))
    | summarize Vnet = take_anyif(Vnet, isnotempty(Vnet)), vm = take_any(tolower(tostring(properties.virtualMachine.id))) by Owner = tolower(id)
  ) on Owner
| extend AttachedTo = iff(AttachedTo == 'Virtual machine' and isempty(vm), 'NIC with no VM', AttachedTo),
    Owner = iff(isnotempty(vm), vm, Owner)""" + PIP_COLUMNS + r"""
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/virtualnetworks'
    | project Vnet = tolower(id), VnetDdos = tobool(properties.enableDdosProtection), Plan = tolower(tostring(properties.ddosProtectionPlan.id))
  ) on Vnet""" + SUBSCRIPTION_NAMES + r"""| extend Protection = case(
    Sku =~ 'Basic', 'Basic SKU: platform default only',
    Ddos =~ 'Enabled', 'IP Protection',
    Ddos =~ 'Disabled', 'Disabled on the IP',
    VnetDdos == true, 'Network Protection (VNet plan)',
    AttachedTo in ('Not attached', 'NIC with no VM'), 'Not in use',
    AttachedTo in ('Load balancer', 'AKS load balancer'), 'Follows the backend VNet',
    isnotempty(Vnet), 'Platform default only (VNet has no plan)',
    'Unknown')
| project id, IP, Protection, AttachedTo, Owner, Vnet, Plan, Ddos, Subscription, ResourceGroup = resourceGroup
"""

DDOS_PIE_Q = DDOS_Q + "| summarize PublicIPs = count() by Protection\n| order by PublicIPs desc"

PROTECTION = status_fmt("Protection", good=["IP Protection", "Network Protection (VNet plan)"],
                        warn=["Platform default only (VNet has no plan)", "Disabled on the IP", "Basic SKU: platform default only"],
                        neutral=["Not in use", "Follows the backend VNet", "Unknown"])
PROTECTION_COLORS = {"seriesLabelSettings": [
    {"seriesName": "IP Protection", "color": "green"},
    {"seriesName": "Network Protection (VNet plan)", "color": "greenDark"},
    {"seriesName": "Platform default only (VNet has no plan)", "color": "orange"},
    {"seriesName": "Disabled on the IP", "color": "redBright"},
    {"seriesName": "Basic SKU: platform default only", "color": "redBright"},
    {"seriesName": "Not in use", "color": "gray"},
    {"seriesName": "Follows the backend VNet", "color": "blue"}]}

PLANS_Q = r"""
resources
| where type =~ 'microsoft.network/ddosprotectionplans'
| project id, ProtectedVnets = array_length(properties.virtualNetworks), Provisioning = tostring(properties.provisioningState),
    subscriptionId, ResourceGroup = resourceGroup, Location = location
""" + SUBSCRIPTION_NAMES + "| project-away subscriptionId, subscriptionId1"

DDOS_NOTE = """\
Every public IP gets Azure's **platform default** protection against large volumetric attacks, tuned to protect
Azure rather than your service. **DDoS Network Protection** (a plan linked to the VNet) and **DDoS IP Protection**
(per IP) add mitigation tuned to each IP's normal traffic, attack alerts and logs, and cost protection. A public
IP's *DDoS protection* setting is *Inherited from virtual network* by default, so it is covered when the VNet of
the resource using it is linked to a plan. *Follows the backend VNet* is a load balancer frontend: it is covered
when the backend VNet is."""

# DDoS logs go to AzureDiagnostics from each public IP's diagnostic setting (categories DDoSProtectionNotifications,
# DDoSMitigationReports and DDoSMitigationFlowLogs). Columns are read with column_ifexists, since a workspace only has
# those it has received.
DDOS_EVENTS_Q = r"""
union isfuzzy=true (datatable(TimeGenerated: datetime, Category: string, ResourceId: string)[]), (AzureDiagnostics
    | where Category in ('DDoSProtectionNotifications', 'DDoSMitigationReports'))
| where TimeGenerated {TimeRange}
| extend Event = coalesce(tostring(column_ifexists('type_s', '')), tostring(column_ifexists('ReportType_s', ''))),
    Address = tostring(column_ifexists('publicIpAddress_s', '')),
    Detail = coalesce(tostring(column_ifexists('Message', '')), tostring(column_ifexists('message_s', '')),
        tostring(column_ifexists('AttackVectors_s', '')), tostring(column_ifexists('attackVectors_s', '')))
| project TimeGenerated, Category, Event, Address, id = tolower(ResourceId), Detail
| order by TimeGenerated desc
| take 500
"""

DDOS_FLOWS_Q = r"""
union isfuzzy=true (datatable(TimeGenerated: datetime, Category: string, ResourceId: string)[]), (AzureDiagnostics
    | where Category == 'DDoSMitigationFlowLogs')
| where TimeGenerated {TimeRange}
| extend Source = tostring(column_ifexists('sourcePublicIpAddress_s', '')),
    Target = tostring(column_ifexists('publicIpAddress_s', column_ifexists('destPublicIpAddress_s', ''))),
    Protocol = tostring(column_ifexists('protocol_s', '')), Action = tostring(column_ifexists('action_s', ''))
| summarize Flows = count(), First = min(TimeGenerated), Last = max(TimeGenerated) by Source, Target, Protocol, Action
| top 100 by Flows desc
"""

# ---------------------------------------------------------------------------
# Changes (Resource Graph change history, 14 days)
# ---------------------------------------------------------------------------

CHANGES_Q = r"""
resourcechanges
| extend Type = tolower(tostring(properties.targetResourceType))
| where Type in ('microsoft.network/publicipaddresses', 'microsoft.network/publicipprefixes')
| extend Time = todatetime(properties.changeAttributes.timestamp)
| where Time >= todatetime('{TimeRange:startISO}')
| extend changes = properties.changes
| project Time, ChangeType = tostring(properties.changeType), id = tolower(tostring(properties.targetResourceId)),
    What = strcat_array(bag_keys(changes), ', '),
    ChangedBy = tostring(properties.changeAttributes.changedBy), Client = tostring(properties.changeAttributes.clientType),
    Operation = tostring(properties.changeAttributes.operation), Kind = iff(Type endswith 'prefixes', 'Prefix', 'Public IP')
| order by Time desc
| take 1000
"""

# Attaching or detaching an IP changes the resource that holds the IP configuration (NIC, load balancer, gateway),
# and the IP's own ipConfiguration property only when Resource Graph next reads it, so both are listed.
ASSOCIATION_Q = r"""
resourcechanges
| extend Time = todatetime(properties.changeAttributes.timestamp)
| where Time >= todatetime('{TimeRange:startISO}')
| extend changes = properties.changes
| mv-expand key = bag_keys(changes) to typeof(string)
| where key contains 'publicIPAddress' or key contains 'ipConfiguration.id' or key contains 'natGateway.id'
    or key contains 'publicIpAddresses'
| extend c = changes[key]
| project Time, id = tolower(tostring(properties.targetResourceId)), Property = key,
    Before = tostring(c.previousValue), After = tostring(c.newValue),
    ChangedBy = tostring(properties.changeAttributes.changedBy), Client = tostring(properties.changeAttributes.clientType)
| order by Time desc
| take 500
"""

CHANGE_TYPE = status_fmt("ChangeType", good=["Create"], warn=["Update"], bad=["Delete"])

# ---------------------------------------------------------------------------
# Parameters, tabs and layout
# ---------------------------------------------------------------------------

Q_PICKER = """resources
| where type =~ 'microsoft.network/publicipaddresses'
| where isnotempty(tostring(properties.ipConfiguration.id)) or isnotempty(tostring(properties.natGateway.id))"""


def global_params():
    return params(f"{P}-params", [
        subscription_param(P),
        time_param(P, 7 * DAY_MS, [d * DAY_MS for d in (1, 3, 7, 14, 30)],
                   "For the traffic charts, DDoS logs and changes. Resource Graph keeps 14 days of changes."),
        free_text_param(P, "Search", "Find",
                        "An IP address or DNS name, for the Find an IP tab."),
        free_text_param(P, "Price", "Price per IP a month",
                        "What one Standard public IP costs you a month, in your currency, for the cost estimates.",
                        value="3.65"),
        workspace_param(P, "Optional. The workspace that receives the public IPs' DDoS diagnostic logs."),
        {"id": gid(f"{P}-param-selectedTab"), "version": "KqlParameterItem/1.0", "name": "selectedTab", "type": 1,
         "value": "overview", "isHiddenWhenLocked": True},
    ])


def tabs():
    return {"type": 11, "content": {"version": "LinkItem/1.0", "style": "tabs", "links": [
        {"id": gid(f"{P}-tab-" + key), "cellValue": "selectedTab", "linkTarget": "parameter",
         "linkLabel": label, "subTarget": key, "style": "link"} for key, label in TABS
    ]}, "name": f"{P}-tabs"}


TILES = big_number_tiles("Signal", "State", "Value", "Detail")


def overview_tab():
    return group(f"{P}-tab-overview", [
        arg(f"{P}-tiles", "", TILES_Q, vis="tiles", tiles=TILES, fixed_px=1150),
        arg(f"{P}-tile-prefixes", "", PREFIX_TILE_Q, vis="tiles", tiles=TILES, fixed_px=ONE_TILE),
        arg(f"{P}-by-attached", "Public IPs by what uses them", BY_ATTACHED_Q, vis="piechart", width=50,
            chart={"seriesLabelSettings": [{"seriesName": "Not attached", "color": "orange"},
                                           {"seriesName": "NIC with no VM", "color": "orange"}]}),
        arg(f"{P}-by-region", "Public IPs by region", BY_REGION_Q, vis="piechart", width=50),
        arg(f"{P}-attention", "Needs attention", ATTENTION_Q,
            formatters=[ISSUE, resource_link(), resource_link("Owner"), SKU, ZONES], labels=PIP_LABELS,
            group_by="Issue", no_data="Every public IP is in use, Standard SKU, not pinned to one zone and has DDoS "
                                      "protection left on."),
        text(f"{P}-zones-note", ZONES_NOTE, "info"),
    ], tab="overview")


def inventory_tab():
    return group(f"{P}-tab-inventory", [
        arg(f"{P}-inventory", "Public IP addresses", INVENTORY_Q,
            formatters=[resource_link(), resource_link("Owner"), resource_link("Prefix"), ATTACHED, SKU, ZONES, PROVISIONING,
                        status_fmt("Ddos", good=["Enabled"], warn=["Disabled"], neutral=["n/a (Basic)"])],
            labels=PIP_LABELS, group_by="AttachedTo", no_data="No public IP addresses in the selected subscriptions."),
        text(f"{P}-inventory-note", "*Used by* is the resource the address is attached to: a virtual machine (rather "
             "than its NIC), load balancer, gateway, firewall, Bastion or NAT gateway. *NIC with no VM* is an address "
             "on a network interface whose VM was deleted. *IP tags* show a routing preference "
             "(`RoutingPreference=Internet` sends traffic over the public internet rather than Microsoft's network) "
             "or a first-party service tag.", "info"),
        arg(f"{P}-prefixes", "Public IP prefixes", PREFIXES + "\n| order by UsedPct asc",
            formatters=[resource_link(), PROVISIONING, ZONES,
                        {"columnMatch": "UsedPct", "formatter": 4, "formatOptions": {"min": 0, "max": 100, "palette": "blue"}}],
            labels={"id": "Prefix", "Prefix": "Range", "Size": "Addresses", "UsedPct": "Used %", "Custom": "Range owner",
                    "ResourceGroup": "Resource group"},
            no_data="No public IP prefixes in the selected subscriptions."),
    ], tab="inventory")


def find_tab():
    return group(f"{P}-tab-find", [
        text(f"{P}-find-howto", FIND_HOWTO, "info"),
        when_set(arg(f"{P}-find", "Who has {Search}?", FIND_Q,
                     formatters=[resource_link(), resource_link("UsedBy")],
                     labels={"id": "Resource", "UsedBy": "Used by", "DnsName": "DNS name", "ResourceGroup": "Resource group"},
                     no_data=FIND_NOT_FOUND), "Search"),
        text(f"{P}-find-note", FIND_NOTE, "info"),
    ], tab="find")


def cleanup_tab():
    return group(f"{P}-tab-cleanup", [
        text(f"{P}-unused-h", "### Paid for but not in use"),
        arg(f"{P}-unused", "Public IPs not attached to anything", UNUSED_Q,
            formatters=[resource_link(), resource_link("Owner"), resource_link("Prefix"), ATTACHED, SKU,
                        status_fmt("Kept", neutral=["Tagged as kept"])],
            labels={**PIP_LABELS, "Owner": "NIC", "PerMonth": "Est. per month", "Kept": "Kept on purpose?"},
            no_data="Every public IP is attached to something."),
        text(f"{P}-cost-note", COST_NOTE, "info"),
        arg(f"{P}-unused-prefixes", "Public IP prefixes less than half used", UNUSED_PREFIXES_Q,
            formatters=[resource_link(), {"columnMatch": "UsedPct", "formatter": 4,
                                          "formatOptions": {"min": 0, "max": 100, "palette": "blue"}}],
            labels={"id": "Prefix", "Prefix": "Range", "Size": "Addresses", "UsedPct": "Used %", "Custom": "Range owner",
                    "ResourceGroup": "Resource group"},
            no_data="Every public IP prefix is at least half used."),
        text(f"{P}-basic-h", "### Basic SKU (retired)"),
        arg(f"{P}-basic", "Basic SKU public IPs", BASIC_Q,
            formatters=[resource_link(), resource_link("Owner"), ATTACHED], labels=PIP_LABELS,
            no_data="No Basic SKU public IPs."),
        text(f"{P}-basic-note", BASIC_NOTE, "warning"),
        text(f"{P}-advisor-h", "### Azure Advisor"),
        arg(f"{P}-advisor", "Advisor recommendations for public IPs and prefixes", ADVISOR_Q,
            formatters=[resource_link(), status_fmt("Impact", warn=["Medium"], bad=["High"])],
            labels={"id": "Resource"}, no_data="Advisor has no recommendations for public IPs."),
    ], tab="cleanup")


def ddos_tab():
    return group(f"{P}-tab-ddos", [
        arg(f"{P}-ddos-pie", "Effective DDoS protection", DDOS_PIE_Q, vis="piechart", width=40, chart=PROTECTION_COLORS),
        arg(f"{P}-ddos-plans", "DDoS protection plans", PLANS_Q, formatters=[resource_link(), PROVISIONING],
            labels={"id": "Plan", "ProtectedVnets": "VNets linked", "ResourceGroup": "Resource group"},
            no_data="No DDoS protection plans: public IPs have platform default protection only, unless IP Protection "
                    "is enabled on them.", width=60),
        text(f"{P}-ddos-note", DDOS_NOTE, "info"),
        arg(f"{P}-ddos", "Protection of each public IP", DDOS_Q + "| order by Protection asc",
            formatters=[PROTECTION, resource_link(), resource_link("Owner"), resource_link("Vnet"), resource_link("Plan")],
            labels={**PIP_LABELS, "Vnet": "VNet", "Ddos": "Setting on the IP"}, group_by="Protection",
            no_data="No public IP addresses in the selected subscriptions."),
        text(f"{P}-ddos-logs-h", "### Attacks and mitigations"),
        text(f"{P}-ddos-hint", "Select a **Log Analytics workspace** at the top for the DDoS notifications, mitigation "
             "reports and flow logs. The attack charts on the *Traffic* tab need no workspace.", "info",
             visible_when=WORKSPACE_UNSET),
        la(f"{P}-ddos-events", "Mitigation notifications and reports", DDOS_EVENTS_Q,
           formatters=[resource_link(), status_fmt("Event", bad=["MitigationStarted"], good=["MitigationStopped"])],
           labels={"TimeGenerated": "Time", "id": "Public IP"},
           no_data="No DDoS mitigations in the time range. These logs exist only for IPs with Network or IP Protection "
                   "whose diagnostic settings send DDoSProtectionNotifications and DDoSMitigationReports here."),
        la(f"{P}-ddos-flows", "Traffic dropped or forwarded during mitigation, busiest sources", DDOS_FLOWS_Q,
           labels={"Target": "Public IP"},
           no_data="No DDoS mitigation flow logs in the time range."),
    ], tab="ddos")


def traffic_tab():
    split = "Direction"
    return group(f"{P}-tab-traffic", [
        params(f"{P}-traffic-params", [resource_param("PublicIps", "Public IPs", Q_PICKER, first=10)]),
        text(f"{P}-traffic-note", "Charts start with the first 10 attached public IPs; choose others, or **All**, "
             "in the picker. *Data path availability* is Azure's probe of the address from inside its own network.",
             "info"),
        metric_grid(f"{P}-traffic-grid", "Public IP metrics (over time range)", PNS, "PublicIps", [
            ("VipAvailability", AVG, "Data path availability %", ("high", 99.9, 99)),
            ("ByteCount", SUM, "Bytes", None),
            ("PacketCount", SUM, "Packets", None),
            ("SynCount", SUM, "SYN packets", None),
            ("IfUnderDDoSAttack", MAX, "Under DDoS attack", ("low", 1, 1)),
        ]),
        metrics(f"{P}-bytes", "Bytes", PNS, "PublicIps", [m(PNS, "ByteCount", SUM, split=split)], width=50),
        metrics(f"{P}-packets", "Packets", PNS, "PublicIps", [m(PNS, "PacketCount", SUM, split=split)], width=50),
        metrics(f"{P}-syn", "SYN packets (new TCP connections)", PNS, "PublicIps", [m(PNS, "SynCount", SUM, split=split)],
                width=50),
        metrics(f"{P}-availability", "Data path availability", PNS, "PublicIps", [m(PNS, "VipAvailability", AVG)],
                width=50),
        metrics(f"{P}-attack", "Under DDoS attack (1 = yes)", PNS, "PublicIps", [m(PNS, "IfUnderDDoSAttack", MAX)],
                width=50),
        metrics(f"{P}-dropped", "Inbound packets dropped by DDoS mitigation", PNS, "PublicIps",
                [m(PNS, "PacketsDroppedDDoS", MAX)], width=50),
    ], tab="traffic")


def changes_tab():
    return group(f"{P}-tab-changes", [
        arg(f"{P}-changes", "Public IPs and prefixes created, changed and deleted", CHANGES_Q,
            formatters=[CHANGE_TYPE, resource_link()],
            labels={"ChangeType": "Change", "id": "Resource", "What": "Properties changed", "ChangedBy": "Changed by"},
            no_data="No public IPs or prefixes changed in the time range (Resource Graph keeps 14 days)."),
        arg(f"{P}-associations", "Public IPs attached, detached or moved", ASSOCIATION_Q,
            formatters=[resource_link(), resource_link("Before"), resource_link("After")],
            labels={"id": "Resource", "ChangedBy": "Changed by"},
            no_data="No public IP was attached or detached in the time range."),
        text(f"{P}-changes-note", "From Resource Graph's change history, which keeps 14 days. *Changed by* is filled "
             "in for changes made through Azure Resource Manager; a change made by the platform (an AKS cluster "
             "adding a load balancer IP) shows the service's identity. For older changes, use the **What changed?** "
             "workbook with the Activity log in a workspace.", "info"),
    ], tab="changes")


def workbook():
    return notebook([
        text(f"{P}-header", "# Public IP addresses\n"
             "Every public IP address and prefix: what uses it, which are paid for but unused or on the retired Basic "
             "SKU, whether DDoS Protection covers them, how much traffic they carry, who changed them, and whose an "
             "address is."),
        global_params(),
        tabs(),
        overview_tab(),
        inventory_tab(),
        find_tab(),
        cleanup_tab(),
        ddos_tab(),
        traffic_tab(),
        changes_tab(),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
