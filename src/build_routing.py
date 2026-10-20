"""Generates the routing path workbook.

Run:  python src/build_routing.py
Out:  workbook/routing.workbook.json

Answers "what path does traffic from A to B take?" from configuration in Resource Graph: where each address lives
(virtual network, subnet, network interface, VM, or a VPN site), the route each side picks for the other (user
routes, the network's own address space, peerings and Azure's default routes, longest prefix first), what the next
hop is (an Azure Firewall, an appliance, a load balancer), whether the reply comes back the same way, and what each
network security group on the way decides. For a network attached to a Virtual WAN hub, the hub's routing intent,
connections and route tables come from Resource Manager. Built from the helpers in build_workbook.py so the
workbooks look alike.

Resource Graph holds configuration, not the routes a network has learned over BGP (from ExpressRoute, VPN, Virtual
WAN or Route Server), so where those apply the answer is an approximation: each network interface links to its
effective routes and security rules in the portal for the definitive view.
"""

import pathlib

from build_workbook import (arg, arm, choice_param, free_text_param, gid, hidden_arg_param, notebook, params,
                            resource_link, status_fmt, subscription_param, text, when_set, write_workbook)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "routing.workbook.json"

P = "rt"

SRC = r"trim(@'\s+', @'{SourceIp}')"
DST = r"trim(@'\s+', @'{DestinationIp}')"

# ---------------------------------------------------------------------------
# Where each address is (hidden parameters, so every panel can use them)
# ---------------------------------------------------------------------------

SUBNETS = """resources
| where type =~ 'microsoft.network/virtualnetworks'
| mv-expand s = properties.subnets limit 2000
| extend prefixes = iff(array_length(s.properties.addressPrefixes) > 0, s.properties.addressPrefixes, pack_array(s.properties.addressPrefix))"""


def subnet_param(name, ip, field):
    """The subnet holding `ip`, reduced to one field; 'none' when the address is not in any network. A parameter
    with no value would hold back every panel that uses it, hence the placeholder."""
    return hidden_arg_param(P, name, f"""{SUBNETS}
| where ipv4_is_in_any_range({ip}, prefixes)
| summarize v = take_any({field})
| project value = iff(isempty(v), 'none', v)""")


def nic_param(name, ip, field):
    return hidden_arg_param(P, name, f"""resources
| where type =~ 'microsoft.network/networkinterfaces'
| mv-expand c = properties.ipConfigurations
| where tostring(c.properties.privateIPAddress) == {ip}
| summarize v = take_any({field})
| project value = iff(isempty(v), 'none', v)""")


def hidden_params():
    return params(f"{P}-hidden", [
        subnet_param("SrcVnet", SRC, "tolower(id)"),
        subnet_param("SrcRouteTable", SRC, "tolower(tostring(s.properties.routeTable.id))"),
        subnet_param("SrcSubnetNsg", SRC, "tolower(tostring(s.properties.networkSecurityGroup.id))"),
        nic_param("SrcNicNsg", SRC, "tolower(tostring(properties.networkSecurityGroup.id))"),
        subnet_param("DstVnet", DST, "tolower(id)"),
        subnet_param("DstRouteTable", DST, "tolower(tostring(s.properties.routeTable.id))"),
        subnet_param("DstSubnetNsg", DST, "tolower(tostring(s.properties.networkSecurityGroup.id))"),
        nic_param("DstNicNsg", DST, "tolower(tostring(properties.networkSecurityGroup.id))"),
    ])


ROLES = f"pack_array(pack('Role', 'Source', 'Ip', {SRC}), pack('Role', 'Destination', 'Ip', {DST}))"

# Both addresses: the subnet and network they are in (if any), the network interface and VM that hold them, or the
# VPN site or local network gateway whose address space covers them. Two networks can overlap; each match shows.
ENDPOINTS_Q = f"""
resourcecontainers
| where type =~ 'microsoft.resources/subscriptions'
| take 1
| mv-expand e = {ROLES}
| project Role = tostring(e.Role), Ip = tostring(e.Ip)
| join kind=leftouter (
    {SUBNETS.replace(chr(10), chr(10) + '    ')}
    | mv-expand e = {ROLES}
    | where ipv4_is_in_any_range(tostring(e.Ip), prefixes)
    | project Role = tostring(e.Role), vnet = tolower(id), Subnet = tostring(s.name), Prefix = strcat_array(prefixes, ', '),
        RouteTable = tolower(tostring(s.properties.routeTable.id)), SubnetNsg = tolower(tostring(s.properties.networkSecurityGroup.id))
  ) on Role
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/networkinterfaces'
    | mv-expand c = properties.ipConfigurations
    | mv-expand e = {ROLES}
    | where tostring(c.properties.privateIPAddress) == tostring(e.Ip)
    | project Role = tostring(e.Role), nic = tolower(id), Vm = tolower(tostring(properties.virtualMachine.id)),
        NicNsg = tolower(tostring(properties.networkSecurityGroup.id)), IpForwarding = tostring(properties.enableIPForwarding)
  ) on Role
| join kind=leftouter (
    resources
    | where type in~ ('microsoft.network/vpnsites', 'microsoft.network/localnetworkgateways')
    | extend space = iff(type =~ 'microsoft.network/vpnsites', properties.addressSpace.addressPrefixes,
        properties.localNetworkAddressSpace.addressPrefixes)
    | mv-expand e = {ROLES}
    | where ipv4_is_in_any_range(tostring(e.Ip), space)
    | summarize Site = strcat_array(make_set(name), ', ') by Role = tostring(e.Role)
  ) on Role
| project Role, Ip, Where = case(isempty(Ip), 'Not given', isnotempty(vnet), 'Azure virtual network',
        isnotempty(Site), strcat('On-premises (', Site, ')'),
        ipv4_is_private(Ip), 'Private, but not in any network here: on-premises, or another subscription', 'Internet'),
    vnet, Subnet, Prefix, RouteTable, SubnetNsg, nic, NicNsg, Vm, IpForwarding,
    EffectiveRoutes = iff(isnotempty(nic), strcat('https://portal.azure.com/#@/resource', nic, '/effectiveRoutes'), ''),
    EffectiveRules = iff(isnotempty(nic), strcat('https://portal.azure.com/#@/resource', nic, '/effectiveSecurityRules'), '')
| order by Role desc
"""

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

# For each direction, every route that covers the other address. Forward is the source subnet's view of the
# destination; Return is the destination subnet's view of the source.
#
# User routes come from the subnet's route table. System routes come from the network itself: its address space
# (VnetLocal), each peering's remote address space (a peering to HV_... is a Virtual WAN hub), Azure's default route
# to the Internet, and the private ranges Azure drops (next hop None) unless something more specific covers them.
# A user route whose prefix is a service tag cannot be checked here and is listed with Len -1, so it never wins.
DIRECTIONS = """| mv-expand d = pack_array(
    iff(tolower(id) == '{SrcKEY}', pack('Direction', 'Forward', 'Target', DST), dynamic(null)),
    iff(tolower(id) == '{DstKEY}', pack('Direction', 'Return', 'Target', SRC), dynamic(null)))
| where isnotnull(d)
| extend Direction = tostring(d.Direction), Target = tostring(d.Target)""".replace("DST", DST).replace("SRC", SRC)

DEFAULT_ROUTES = ('dynamic([{"name": "Azure default route", "kind": "Internet", "remote": ["0.0.0.0/0"]}, '
                  '{"name": "Azure default: private range not in any connected network", "kind": "None", '
                  '"remote": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10"]}])')

ROUTES = f"""
resources
| where type =~ 'microsoft.network/routetables' and tolower(id) in ('{{SrcRouteTable}}', '{{DstRouteTable}}')
{DIRECTIONS.replace('KEY', 'RouteTable')}
| mv-expand r = properties.routes limit 2000
| extend Prefix = tostring(r.properties.addressPrefix)
| extend Match = ipv4_is_in_range(Target, Prefix)
| where Match == true or isnull(Match)
| project Direction, Target, Prefix, Len = toint(iff(isnull(Match), -1, toint(split(Prefix, '/')[1]))), Origin = 'User route',
    NextHop = tostring(r.properties.nextHopType), NextHopIp = tostring(r.properties.nextHopIpAddress),
    Via = strcat(tostring(r.name), ' in ', name),
    Note = case(isnull(Match), 'Service tag prefix: not checked here',
        tobool(properties.disableBgpRoutePropagation), 'Gateway route propagation off', '')
| union (
    resources
    | where type =~ 'microsoft.network/virtualnetworks' and tolower(id) in ('{{SrcVnet}}', '{{DstVnet}}')
    {DIRECTIONS.replace('KEY', 'Vnet').replace(chr(10), chr(10) + '    ')}
    | mv-expand p = array_concat(
        pack_array(pack('name', 'Address space of this network', 'kind', 'VnetLocal', 'remote', properties.addressSpace.addressPrefixes)),
        iff(array_length(properties.virtualNetworkPeerings) > 0, properties.virtualNetworkPeerings, dynamic([])),
        {DEFAULT_ROUTES}) limit 2000
    | extend remoteVnet = tolower(tostring(p.properties.remoteVirtualNetwork.id))
    | extend NextHop = coalesce(tostring(p.kind), iff(remoteVnet contains '/virtualnetworks/hv_', 'Virtual WAN hub', 'VNetPeering')),
        Remote = iff(isnotnull(p.remote), p.remote, p.properties.remoteAddressSpace.addressPrefixes),
        Via = iff(isnotnull(p.remote), tostring(p.name), strcat('Peering ', tostring(p.name), ' to ', tostring(split(remoteVnet, '/')[8]))),
        Note = iff(isnotnull(p.remote), '', strcat('Peering ', tostring(p.properties.peeringState),
            iff(tobool(p.properties.allowForwardedTraffic), '', ', forwarded traffic not allowed'),
            iff(tobool(p.properties.useRemoteGateways), ', uses the remote gateway', '')))
    | mv-expand prefix = Remote limit 2000
    | extend Prefix = tostring(prefix)
    | where ipv4_is_in_range(Target, Prefix)
    | project Direction, Target, Prefix, Len = toint(split(Prefix, '/')[1]), Origin = 'System route', NextHop, NextHopIp = '', Via, Note)
// Longest prefix wins; on a tie a user route beats a system route.
| extend Score = Len * 10 + iff(Origin == 'User route', 2, 1)
"""

ROUTES_Q = ROUTES + """| order by Direction asc, Score desc
| project Direction, Target, Prefix, Origin, NextHop, NextHopIp, Via, Note
"""

# Every address a next hop can be: Azure Firewall (in a network or a Virtual WAN hub), an appliance's network
# interface, or an internal load balancer in front of appliances.
NEXT_HOP_OWNERS = """
    resources
    | where type =~ 'microsoft.network/azurefirewalls'
    | extend hubIp = tostring(properties.hubIPAddresses.privateIPAddress)
    | mv-expand c = iff(isnotempty(hubIp), pack_array(hubIp), properties.ipConfigurations)
    | project NextHopIp = iff(isnotempty(hubIp), hubIp, tostring(c.properties.privateIPAddress)), Appliance = tolower(id), Kind = 'Azure Firewall'
    | union (
        resources
        | where type =~ 'microsoft.network/networkinterfaces'
        | mv-expand c = properties.ipConfigurations
        | project NextHopIp = tostring(c.properties.privateIPAddress), Appliance = tolower(coalesce(tostring(properties.virtualMachine.id), id)),
            Kind = iff(tobool(properties.enableIPForwarding), 'Appliance (IP forwarding on)', 'VM with IP forwarding OFF: it drops forwarded traffic'))
    | union (
        resources
        | where type =~ 'microsoft.network/loadbalancers'
        | mv-expand f = properties.frontendIPConfigurations
        | where isnotempty(tostring(f.properties.privateIPAddress))
        | project NextHopIp = tostring(f.properties.privateIPAddress), Appliance = tolower(id), Kind = 'Internal load balancer (in front of appliances)')
    | where isnotempty(NextHopIp)"""

CHOSEN = ROUTES + f"""| where Len >= 0
| summarize arg_max(Score, Prefix, Origin, NextHop, NextHopIp, Via, Note, Target) by Direction
| join kind=leftouter ({NEXT_HOP_OWNERS}
  ) on NextHopIp
"""

CHOSEN_Q = CHOSEN + """| project Direction, Target, Prefix, Origin, NextHop, NextHopIp, Appliance, Kind, Via, Note
| order by Direction asc
"""

# Both directions side by side, and what that means. A stateful firewall that sees only one direction of a
# session drops the rest, so the reply must come back through the same appliance.
VERDICT_Q = CHOSEN + """| extend Hop = case(NextHop =~ 'VirtualAppliance', strcat('appliance ', NextHopIp), NextHop =~ 'None', 'dropped', NextHop)
| summarize Forward = take_anyif(Hop, Direction == 'Forward'), Return = take_anyif(Hop, Direction == 'Return'),
    FwdIp = take_anyif(NextHopIp, Direction == 'Forward'), RetIp = take_anyif(NextHopIp, Direction == 'Return'),
    FwdType = take_anyif(NextHop, Direction == 'Forward'), RetType = take_anyif(NextHop, Direction == 'Return')
| extend Verdict = case(
    FwdType =~ 'None', 'No route to the destination in configuration: dropped, unless a gateway or Virtual WAN hub supplies one',
    RetType =~ 'None', 'No route back to the source in configuration: the reply is dropped, unless a gateway or Virtual WAN hub supplies one',
    isempty(RetType), 'Return path not in Azure here (on-premises, internet or another subscription): check the other side',
    FwdType =~ 'VirtualAppliance' and RetType =~ 'VirtualAppliance' and FwdIp == RetIp, 'Symmetric: both ways through the same appliance',
    FwdType =~ 'VirtualAppliance' and RetType =~ 'VirtualAppliance', 'Through different appliance addresses each way: fine only if they are one cluster behind a load balancer',
    FwdType =~ 'VirtualAppliance' or RetType =~ 'VirtualAppliance', 'Asymmetric: one direction skips the appliance, so a stateful firewall drops the session',
    FwdType has 'Virtual WAN hub' or RetType has 'Virtual WAN hub', 'Through the Virtual WAN hub: see its routing intent below',
    'Direct: no appliance in the path')
| project Forward, Return, Verdict
"""

VERDICT_FMT = status_fmt("Verdict", good=["Symmetric: both ways through the same appliance", "Direct: no appliance in the path"],
                         warn=["Through different appliance addresses each way: fine only if they are one cluster behind a load balancer",
                               "Through the Virtual WAN hub: see its routing intent below",
                               "Return path not in Azure here (on-premises, internet or another subscription): check the other side"],
                         bad=["No route to the destination in configuration: dropped, unless a gateway or Virtual WAN hub supplies one", "No route back to the source in configuration: the reply is dropped, unless a gateway or Virtual WAN hub supplies one",
                              "Asymmetric: one direction skips the appliance, so a stateful firewall drops the session"])

# ---------------------------------------------------------------------------
# Network security groups
# ---------------------------------------------------------------------------

# How well one address prefix in a rule covers an address: 3 yes, 2 probably, 1 cannot tell (a service tag), 0 no.
# VirtualNetwork is certain for an address found in a virtual network here and likely for any other private one;
# Internet is the reverse.
def prefix_score(p, ip, vnet_param):
    in_vnet = f"'{{{vnet_param}}}' != 'none'"
    return f"""case({p} in ('*', '0.0.0.0/0') or {p} =~ 'any', 3,
        isnotnull(ipv4_is_in_range({ip}, {p})), iff(ipv4_is_in_range({ip}, {p}), 3, 0),
        {p} =~ 'VirtualNetwork', case({in_vnet}, 3, ipv4_is_private({ip}), 2, 0),
        {p} =~ 'Internet', case({in_vnet}, 0, ipv4_is_private({ip}), 0, 3),
        {p} =~ 'AzureLoadBalancer', iff({ip} == '168.63.129.16', 3, 0),
        1)"""


# Every rule (custom and default) of the NSGs on the path, in the order Azure applies them: outbound at the source
# NIC then the source subnet, inbound at the destination subnet then the destination NIC. Each rule's source,
# destination, ports and protocol are scored against the flow; the rule's match is the weakest of the four.
NSG_RULES = r"""
resources
| where type =~ 'microsoft.network/networksecuritygroups'
| where tolower(id) in ('{SrcNicNsg}', '{SrcSubnetNsg}', '{DstSubnetNsg}', '{DstNicNsg}')
| mv-expand pos = pack_array(
    iff(tolower(id) == '{SrcNicNsg}', pack('Order', 1, 'Position', '1. Source NIC (outbound)', 'Direction', 'Outbound'), dynamic(null)),
    iff(tolower(id) == '{SrcSubnetNsg}', pack('Order', 2, 'Position', '2. Source subnet (outbound)', 'Direction', 'Outbound'), dynamic(null)),
    iff(tolower(id) == '{DstSubnetNsg}', pack('Order', 3, 'Position', '3. Destination subnet (inbound)', 'Direction', 'Inbound'), dynamic(null)),
    iff(tolower(id) == '{DstNicNsg}', pack('Order', 4, 'Position', '4. Destination NIC (inbound)', 'Direction', 'Inbound'), dynamic(null)))
| where isnotnull(pos)
| mv-expand r = array_concat(properties.securityRules, properties.defaultSecurityRules) limit 2000
| where tostring(r.properties.direction) =~ tostring(pos.Direction)
| extend rp = r.properties
| extend SrcList = iff(array_length(rp.sourceAddressPrefixes) > 0, rp.sourceAddressPrefixes, pack_array(rp.sourceAddressPrefix)),
    DstList = iff(array_length(rp.destinationAddressPrefixes) > 0, rp.destinationAddressPrefixes, pack_array(rp.destinationAddressPrefix)),
    PortList = iff(array_length(rp.destinationPortRanges) > 0, rp.destinationPortRanges, pack_array(rp.destinationPortRange))
| mv-expand sp = SrcList limit 400
| mv-expand dp = DstList limit 400
| mv-expand pp = PortList limit 400
| extend sp = tostring(sp), dp = tostring(dp), pp = tostring(pp)
| extend lo = toint(extract('^([0-9]+)', 1, pp)), hi = toint(extract('-([0-9]+)$', 1, pp)), Port = toint(trim(@'\s+', '{Port}'))
| extend SrcS = iff(array_length(rp.sourceApplicationSecurityGroups) > 0, 1, SRC_SCORE),
    DstS = iff(array_length(rp.destinationApplicationSecurityGroups) > 0, 1, DST_SCORE),
    PortS = case(pp == '*', 3, isnull(Port), 2, Port >= lo and Port <= coalesce(hi, lo), 3, 0),
    ProtoS = case(tostring(rp.protocol) == '*', 3, '{Protocol}' == 'Any', 2, tostring(rp.protocol) =~ '{Protocol}', 3, 0)
| summarize SrcS = max(SrcS), DstS = max(DstS), PortS = max(PortS), ProtoS = max(ProtoS)
    by Order = toint(pos.Order), Position = tostring(pos.Position), Nsg = tolower(id), Rule = tostring(r.name),
    Priority = toint(rp.priority), Access = tostring(rp.access), Protocol = tostring(rp.protocol),
    Source = strcat_array(SrcList, ', '), Destination = strcat_array(DstList, ', '), Ports = strcat_array(PortList, ', ')
| extend Score = min_of(SrcS, DstS, PortS, ProtoS)
| where Score > 0
""".replace("SRC_SCORE", prefix_score("sp", SRC, "SrcVnet")).replace("DST_SCORE", prefix_score("dp", DST, "DstVnet"))

NSG_RULES_Q = NSG_RULES + """| project Position, Priority, Rule, Access, Match = case(Score == 3, 'Matches', Score == 2, 'Probably matches',
    'Cannot tell (service tag or application security group)'), Source, Destination, Ports, Protocol, Nsg, Order
| order by Order asc, Priority asc
"""

# Per NSG on the path: the first rule that matches (or probably matches) decides; a rule before it that cannot be
# judged here is counted, since it could decide first. A position with no NSG lets everything through.
NSG_VERDICT_Q = f"""
resourcecontainers
| where type =~ 'microsoft.resources/subscriptions'
| take 1
| mv-expand pos = pack_array(
    pack('Order', 1, 'Position', '1. Source NIC (outbound)', 'Nsg', '{{SrcNicNsg}}'),
    pack('Order', 2, 'Position', '2. Source subnet (outbound)', 'Nsg', '{{SrcSubnetNsg}}'),
    pack('Order', 3, 'Position', '3. Destination subnet (inbound)', 'Nsg', '{{DstSubnetNsg}}'),
    pack('Order', 4, 'Position', '4. Destination NIC (inbound)', 'Nsg', '{{DstNicNsg}}'))
| project Order = toint(pos.Order), Position = tostring(pos.Position), Nsg = tostring(pos.Nsg)
| join kind=leftouter ({NSG_RULES.replace(chr(10), chr(10) + '    ')}
    | where Score >= 2
    | summarize arg_min(Priority, Rule, Access, Score) by Order
  ) on Order
| join kind=leftouter ({NSG_RULES.replace(chr(10), chr(10) + '    ')}
    | where Score == 1
    | project Order, Before = Priority
  ) on Order
| summarize Uncertain = countif(isnotnull(Before) and Before < coalesce(Priority, 100000))
    by Order, Position, Nsg, Rule, Priority, Access, Score
| project Position, Nsg = iff(Nsg == 'none', '', Nsg),
    Decision = case(Order <= 2 and '{{SrcVnet}}' == 'none', 'Source not in a network here',
        Order >= 3 and '{{DstVnet}}' == 'none', 'Destination not in a network here',
        Nsg == 'none', 'No NSG: allowed', isempty(Access), 'No rule matched',
        Score == 2, iff(Access =~ 'Allow', 'Probably allowed', 'Probably denied'), iff(Access =~ 'Allow', 'Allowed', 'Denied')),
    Rule, Priority, CheckFirst = iff(Uncertain > 0, strcat(Uncertain, ' rule(s) before it might match'), '')
| order by Position asc
"""

# ---------------------------------------------------------------------------
# Virtual WAN
# ---------------------------------------------------------------------------

# Hubs, the ones the two networks are connected to first. A network connected to a hub peers with a hidden
# network named HV_<hub>_<guid>.
HUB_PICK_Q = r"""
resources
| where type =~ 'microsoft.network/virtualhubs'
| project id, hub = tolower(name)
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/virtualnetworks' and tolower(id) in ('{SrcVnet}', '{DstVnet}')
    | mv-expand p = properties.virtualNetworkPeerings
    | extend hub = tolower(extract(@'(?i)/virtualnetworks/HV_(.+)_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', 1,
        tostring(p.properties.remoteVirtualNetwork.id)))
    | where isnotempty(hub)
    | summarize Connected = count() by hub
  ) on hub
| order by Connected desc, hub asc
| project id
"""

HOW_TO = """\
Enter a source and a destination IP (a port and protocol make the NSG check exact). This works from configuration
in Resource Graph, so it answers instantly and needs no logs or Network Watcher, but see the note on learned routes.

**Reading it, top to bottom.**
1. **Where the addresses are.** A *Private, but not in any network here* address is on-premises or in a
   subscription you have not selected.
2. **The route each side picks.** Longest prefix wins; on a tie a user route beats a system route. *Forward* is the
   source subnet's route to the destination, *Return* the destination subnet's route back.
3. **The verdict.** The usual failure is **asymmetric** routing: the request goes through a firewall and the reply
   does not (or the other way round), and the firewall drops the half-session it sees.
4. **The NSGs.** Outbound at the source, inbound at the destination. A flow must be allowed at every NSG.

**Learned routes are not visible here.** Routes a network learns over BGP (from ExpressRoute, VPN, a Virtual WAN
hub or Route Server) are not in Resource Graph. If a network uses a gateway or is connected to a Virtual WAN hub,
open *Effective routes* on the network interface for the definitive answer, and check the hub's routing intent
below. Once the route is right, use the firewall workbook to see what the firewall decided."""

ENDPOINT_LABELS = {"Ip": "IP", "vnet": "Virtual network", "Prefix": "Subnet range", "RouteTable": "Route table",
                   "SubnetNsg": "Subnet NSG", "nic": "Network interface", "NicNsg": "NIC NSG", "Vm": "VM",
                   "IpForwarding": "IP forwarding", "EffectiveRoutes": "Effective routes",
                   "EffectiveRules": "Effective security rules"}


def parameters():
    return params(f"{P}-params", [
        subscription_param(P),
        free_text_param(P, "SourceIp", "Source IP", "The address the traffic comes from."),
        free_text_param(P, "DestinationIp", "Destination IP", "The address it is going to."),
        free_text_param(P, "Port", "Destination port", "Optional. Makes the NSG check exact."),
        choice_param(P, "Protocol", "Protocol", [("Tcp", "TCP"), ("Udp", "UDP"), ("Icmp", "ICMP"), ("Any", "Any")], "Tcp",
                     "For the NSG check."),
    ])


def both(item):
    return when_set(item, "SourceIp", "DestinationIp")


def workbook():
    hub_picker = params(f"{P}-hub-params", [{
        "id": gid(f"{P}-param-Hub"), "version": "KqlParameterItem/1.0", "name": "Hub", "label": "Virtual WAN hub",
        "type": 5, "isRequired": False, "multiSelect": False, "query": HUB_PICK_Q.strip(),
        "crossComponentResources": ["{Subscription}"],
        "typeSettings": {"additionalResourceOptions": ["value::1"], "showDefault": False},
        "defaultValue": "value::1", "queryType": 1, "resourceType": "microsoft.resourcegraph/resources",
        "description": "Starts with a hub the source or destination network is connected to, if any.",
    }])
    intent_cols = [("Policy", "$.name", None), ("Traffic", "$.destinations", None), ("Next hop", "$.nextHop", None)]
    conn_cols = [("Connection", "$.name", None), ("Network", "$.properties.remoteVirtualNetwork.id", None),
                 ("Associated route table", "$.properties.routingConfiguration.associatedRouteTable.id", None),
                 ("Propagates to", "$.properties.routingConfiguration.propagatedRouteTables.ids[*].id", None),
                 ("Internet via hub", "$.properties.enableInternetSecurity", None),
                 ("State", "$.properties.provisioningState", None)]
    table_cols = [("Route table", "$.name", None), ("Labels", "$.properties.labels", None),
                  ("Routes", "$.properties.routes", None),
                  ("Associated connections", "$.properties.associatedConnections", None),
                  ("Propagating connections", "$.properties.propagatingConnections", None)]
    return notebook([
        text(f"{P}-header", "# Routing: what path does traffic take?\n"
             "From one IP to another: where each address lives, the route each side picks, the next hop, whether the "
             "reply comes back the same way, and what every network security group on the way decides."),
        parameters(),
        hidden_params(),
        text(f"{P}-howto", HOW_TO, "info"),
        both(arg(f"{P}-endpoints", "Where the two addresses are", ENDPOINTS_Q,
                 formatters=[resource_link("vnet"), resource_link("RouteTable"), resource_link("SubnetNsg"),
                             resource_link("nic"), resource_link("NicNsg"), resource_link("Vm"),
                             status_fmt("Where", good=["Azure virtual network"], neutral=["Internet"],
                                        warn=["Private, but not in any network here: on-premises, or another subscription"]),
                             {"columnMatch": "EffectiveRoutes", "formatter": 7, "formatOptions": {"linkTarget": "Url", "linkLabel": "Open"}},
                             {"columnMatch": "EffectiveRules", "formatter": 7, "formatOptions": {"linkTarget": "Url", "linkLabel": "Open"}}],
                 labels=ENDPOINT_LABELS)),
        both(arg(f"{P}-verdict", "The path", VERDICT_Q, formatters=[VERDICT_FMT],
                 no_data="Neither address is in a virtual network in the selected subscriptions.")),
        both(arg(f"{P}-chosen", "The route each side picks", CHOSEN_Q,
                 formatters=[resource_link("Appliance"),
                             status_fmt("NextHop", good=["VnetLocal", "VNetPeering"], warn=["VirtualAppliance", "Virtual WAN hub",
                                                                                           "VirtualNetworkGateway", "Internet"],
                                        bad=["None"]),
                             status_fmt("Kind", good=["Azure Firewall", "Appliance (IP forwarding on)",
                                                      "Internal load balancer (in front of appliances)"],
                                        bad=["VM with IP forwarding OFF: it drops forwarded traffic"])],
                 labels={"Target": "Towards", "NextHop": "Next hop", "NextHopIp": "Next hop IP", "Kind": "Next hop is"},
                 no_data="Neither address is in a virtual network in the selected subscriptions.")),
        both(arg(f"{P}-routes", "Every route that covers the other address", ROUTES_Q,
                 labels={"Target": "Towards", "NextHop": "Next hop", "NextHopIp": "Next hop IP"},
                 no_data="No routes: neither address is in a virtual network in the selected subscriptions.")),
        text(f"{P}-nsg-h", "### Network security groups"),
        both(arg(f"{P}-nsg-verdict", "Decision at each NSG on the path", NSG_VERDICT_Q,
                 formatters=[resource_link("Nsg"), status_fmt("Decision", good=["Allowed", "No NSG: allowed"], bad=["Denied"],
                                                               warn=["Probably allowed", "Probably denied", "No rule matched"],
                                        neutral=["Source not in a network here", "Destination not in a network here"])],
                 labels={"Nsg": "NSG", "CheckFirst": "Check first"})),
        both(arg(f"{P}-nsg-rules", "Rules that match, or might, in the order they apply", NSG_RULES_Q,
                 formatters=[resource_link("Nsg"), status_fmt("Access", good=["Allow"], bad=["Deny"]),
                             status_fmt("Match", good=["Matches"], warn=["Probably matches"],
                                        neutral=["Cannot tell (service tag or application security group)"]),
                             {"columnMatch": "Order", "formatter": 5}],
                 labels={"Nsg": "NSG"}, no_data="No NSG on the path.")),
        text(f"{P}-nsg-note", "*Probably matches*: the rule uses the **VirtualNetwork** or **Internet** tag for an address "
             "that is not in a network here, judged by whether it is private (VirtualNetwork also covers peered and "
             "on-premises ranges). *Cannot tell*: "
             "another service tag or an application security group, which only the effective security rules can resolve. "
             "Without a port, a rule limited to certain ports shows as *Probably matches*.", "info"),
        text(f"{P}-vwan-h", "### Virtual WAN hub"),
        text(f"{P}-vwan-note", "A network connected to a Virtual WAN hub learns its routes from the hub. With **routing "
             "intent**, private traffic (and internet traffic, if set) goes to the hub firewall in both directions. "
             "Without it, the connection's associated and propagated route tables decide.", "info"),
        hub_picker,
        when_set(arm(f"{P}-intent", "Routing intent", "{Hub}/routingIntent", "2023-09-01", intent_cols,
                     table="$.value[*].properties.routingPolicies[*]", width=40,
                     no_data="No routing intent on this hub."), "Hub"),
        when_set(arm(f"{P}-connections", "Network connections", "{Hub}/hubVirtualNetworkConnections", "2023-09-01",
                     conn_cols, width=60, no_data="No networks connected to this hub."), "Hub"),
        when_set(arm(f"{P}-hub-tables", "Hub route tables", "{Hub}/hubRouteTables", "2023-09-01", table_cols,
                     no_data="No route tables on this hub."), "Hub"),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
