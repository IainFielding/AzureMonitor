"""Generates the DNS workbook.

Run:  python src/build_dns.py
Out:  workbook/dns.workbook.json

The state of DNS across the estate, where the DNS and private endpoints troubleshooter answers for one name. Azure
Firewall DNS proxy (which firewalls proxy, where they forward, which networks use them, FQDN network rules that
depend on them, and how the proxy is answering), private DNS zones and their links, DNS Private Resolvers,
forwarding rulesets and DNS security policies, the DNS servers every virtual network hands out, and what the DNS
servers are answering. From Resource Graph, Resource Manager (forwarding rules), Azure Monitor metrics (zone query
volume) and Log Analytics (Azure Firewall DNS proxy, DNS security policy and Windows DNS server logs). Built from the
helpers in build_workbook.py so the workbooks look alike.
"""

import pathlib

from build_dns_troubleshoot import RESOLVERS_Q, RULESET_PICK_Q, RULESETS_Q, SERVERS
from build_workbook import (DAY_MS, MAX, ONE_TILE, PROVISIONING, SUBSCRIPTION_NAMES, SUM, WORKSPACE_UNSET, arg, arm,
                            big_number_tiles, free_text_param, gid, group, la, low_is_good, m, metrics, notebook,
                            params, resource_link, resource_param, status_fmt, subscription_param, text, time_param,
                            when_set, workspace_param, write_workbook)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "dns.workbook.json"

P = "dnsh"

ZNS = "microsoft.network/privatednszones"

TABS = [
    ("overview", "Overview"),
    ("proxy", "Firewall DNS proxy"),
    ("zones", "Private DNS zones"),
    ("resolvers", "Resolvers & policies"),
    ("vnets", "VNet DNS settings"),
    ("queries", "Queries"),
]

VNET_OF = r"tolower(extract(@'(?i)^(.*/virtualnetworks/[^/]+)/subnets/', 1, SUBNET))"


def vnet_of(subnet_expr):
    return VNET_OF.replace("SUBNET", subnet_expr)


# ---------------------------------------------------------------------------
# Azure Firewall DNS proxy (Resource Graph)
# ---------------------------------------------------------------------------

# Network rules that name FQDNs, per firewall policy. The firewall resolves them through its DNS proxy, so they only
# work, and only match what clients reach, when the proxy is on and the clients use it.
FQDN_RULES = r"""
    resources
    | where type =~ 'microsoft.network/firewallpolicies/rulecollectiongroups'
    | mv-expand rc = properties.ruleCollections
    | mv-expand rule = rc.rules
    | where tostring(rule.ruleType) =~ 'NetworkRule' and array_length(rule.destinationFqdns) > 0
    | summarize FqdnRules = count() by KEY = tostring(split(tolower(id), '/rulecollectiongroups/')[0])"""

# Every firewall: the address clients use as their DNS server (a secured hub's private address, or the firewall's
# own), whether its policy (or, for a firewall with classic rules, its own settings) has DNS proxy on, where it
# forwards, how many VNets hand it out as their DNS server, and how many FQDN network rules depend on it, including
# rules inherited from a parent policy.
FW_BASE = r"""
resources
| where type =~ 'microsoft.network/azurefirewalls'
| extend hubIp = tostring(properties.hubIPAddresses.privateIPAddress)
| extend ProxyIp = iff(isnotempty(hubIp), hubIp, tostring(properties.ipConfigurations[0].properties.privateIPAddress)),
    Deployment = iff(isnotempty(tostring(properties.virtualHub.id)), 'Secured virtual hub', 'Hub VNet'),
    Network = iff(isnotempty(tostring(properties.virtualHub.id)), tolower(tostring(properties.virtualHub.id)),
        """ + vnet_of("tostring(properties.ipConfigurations[0].properties.subnet.id)") + r"""),
    policy = tolower(tostring(properties.firewallPolicy.id)),
    classicProxy = tostring(properties.additionalProperties['Network.DNS.EnableProxy']),
    classicServers = tostring(properties.additionalProperties['Network.DNS.Servers'])
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/firewallpolicies'
    | project policy = tolower(id), ownDns = isnotnull(properties.dnsSettings.enableProxy),
        policyProxy = tostring(properties.dnsSettings.enableProxy), policyServers = strcat_array(properties.dnsSettings.servers, ', '),
        Parent = tolower(tostring(properties.basePolicy.id))
  ) on policy
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/firewallpolicies'
    | project Parent = tolower(id), parentProxy = tostring(properties.dnsSettings.enableProxy),
        parentServers = strcat_array(properties.dnsSettings.servers, ', ')
  ) on Parent
| extend policyProxy = iff(ownDns or isempty(Parent), policyProxy, parentProxy),
    policyServers = iff(ownDns or isempty(Parent), policyServers, parentServers)
| extend Proxy = iff(isnotempty(policy), policyProxy =~ 'true', classicProxy =~ 'true'),
    Forwarders = iff(isnotempty(policy), policyServers, replace_string(classicServers, ',', ', '))
| extend Forwarding = iff(isempty(Forwarders), 'Azure DNS', Forwarders),
    Rules = iff(isnotempty(policy), 'Firewall policy', 'Classic rules')"""

# Resource Graph allows six joins in a query, so the counts are added only where they are shown.
FIREWALLS = FW_BASE + r"""
| join kind=leftouter (""" + FQDN_RULES.replace("KEY", "policy") + r"""
  ) on policy
| join kind=leftouter (""" + FQDN_RULES.replace("KEY", "Parent").replace("FqdnRules", "ParentFqdnRules") + r"""
  ) on Parent
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/virtualnetworks'
    | mv-expand s = properties.dhcpOptions.dnsServers to typeof(string)
    | where isnotempty(s)
    | summarize Clients = dcount(id) by ProxyIp = s
  ) on ProxyIp
| extend FqdnRules = coalesce(FqdnRules, 0) + coalesce(ParentFqdnRules, 0), Clients = coalesce(Clients, 0)
| extend Findings = array_concat(
    iff(Clients > 0 and not(Proxy), dynamic(['VNets use it as DNS server, but DNS proxy is off']), dynamic([])),
    iff(FqdnRules > 0 and not(Proxy), dynamic(['FQDN network rules need DNS proxy, which is off']), dynamic([])),
    iff(FqdnRules > 0 and Proxy and Clients == 0, dynamic(['FQDN network rules, but no VNet uses the proxy']), dynamic([])),
    iff(Proxy and Deployment == 'Secured virtual hub' and isempty(Forwarders),
        dynamic(['Secured hub forwards to Azure DNS: private DNS zones will not resolve']), dynamic([])))
| extend State = case(array_length(Findings) == 0 and Proxy, 'OK', array_length(Findings) == 0, 'Proxy off (not used)',
    tostring(Findings[0]) has 'is off', 'Problem', 'Check')"""

FIREWALLS_Q = FIREWALLS + SUBSCRIPTION_NAMES + r"""
| project State, id, Proxy = iff(Proxy, 'On', 'Off'), ProxyIp, Deployment, Network, Forwarding, Clients, FqdnRules,
    Findings = strcat_array(Findings, ' · '), Rules, Policy = policy, Parent, Subscription, ResourceGroup = resourceGroup
| order by case(State == 'Problem', 0, State == 'Check', 1, 2) asc
"""

PROXY_STATE = status_fmt("State", good=["OK"], warn=["Check"], bad=["Problem"], neutral=["Proxy off (not used)"])

# Where each proxy forwards, matched against the DNS servers in Azure (resolver inbound endpoints, other firewalls,
# VMs). A custom server that is none of them is on-premises or a third party, so the proxy depends on the WAN.
FORWARDERS_Q = FW_BASE + r"""
| where Proxy and isnotempty(Forwarders)
| mv-expand Server = split(Forwarders, ', ') to typeof(string)
| join kind=leftouter (""" + SERVERS + r"""
  ) on $left.Server == $right.Ip
| project Firewall = id, Server, Kind = coalesce(Kind, 'Not in Azure (on-premises or third party)'), Owner,
    Lookup = Lookup, Then
"""

FORWARD_KIND = status_fmt("Kind", good=["DNS Private Resolver inbound endpoint"],
                          warn=["Not in Azure (on-premises or third party)"],
                          neutral=["Virtual machine (custom DNS server)", "Azure Firewall (DNS proxy)"])

PROXY_NOTE = """\
**How DNS proxy works.** With DNS proxy on, the firewall listens on port 53 at its private address and forwards
lookups to Azure DNS or to the custom servers in its policy. VNets use it by setting the firewall's private address
(a secured hub's *private IP*) as their DNS server. It matters for two things:
- **FQDN network rules.** A network rule that names an FQDN is resolved by the firewall itself, and only works with
  DNS proxy on. Clients must use the proxy too, or they may get a different address from the one the rule allows
  (common with CDN-backed names), and the connection is denied.
- **Private DNS zones in Virtual WAN.** A Virtual WAN hub cannot be linked to a private DNS zone, so a secured hub
  firewall that forwards to Azure DNS cannot resolve `privatelink` names. Forward to a **DNS Private Resolver inbound
  endpoint** in a VNet linked to the zones instead.

*Clients* counts VNets whose DNS servers include the firewall's address. FQDN rules include those inherited from
a parent policy, and a child policy with no DNS settings of its own is shown with its parent's."""

# ---------------------------------------------------------------------------
# Azure Firewall DNS proxy (Log Analytics)
# ---------------------------------------------------------------------------

# Resource-specific firewall logs, category AZFWDnsQuery. RequestDurationSecs is the time the proxy took to answer.
FW_DNS = r"""let FwDns = union isfuzzy=true
    (datatable(TimeGenerated: datetime, Firewall: string, SourceIp: string, QueryName: string, QueryType: string,
        ResponseCode: string, Ms: real, Protocol: string, ErrorMessage: string)[]),
    (AZFWDnsQuery
    | where TimeGenerated {TimeRange}
    | project TimeGenerated, Firewall = tostring(split(tostring(column_ifexists('_ResourceId', '')), '/')[-1]),
        SourceIp = tostring(column_ifexists('SourceIp', '')), QueryName = tolower(trim_end(@'\.', tostring(column_ifexists('QueryName', '')))),
        QueryType = tostring(column_ifexists('QueryType', '')), ResponseCode = toupper(tostring(column_ifexists('ResponseCode', ''))),
        Ms = 1000.0 * todouble(column_ifexists('RequestDurationSecs', real(null))), Protocol = tostring(column_ifexists('Protocol', '')),
        ErrorMessage = tostring(column_ifexists('ErrorMessage', '')))
    | where isempty(@'{Name}') or QueryName contains tolower(trim(@'[\s.]+', @'{Name}'))
    | where isempty(@'{ClientIp}') or SourceIp == trim(@'\s+', @'{ClientIp}');
"""

FW_TILES_Q = FW_DNS + r"""FwDns
| summarize Queries = count(), Failed = countif(ResponseCode != 'NOERROR'), ServFail = countif(ResponseCode == 'SERVFAIL'),
    P95 = percentile(Ms, 95), Clients = dcount(SourceIp), Errors = countif(isnotempty(ErrorMessage))
| extend FailPct = iff(Queries > 0, round(100.0 * Failed / Queries, 1), 0.0)
| extend rows = pack_array(
    pack('Order', 1, 'Signal', 'Proxy lookups', 'Value', Queries, 'State', 'Unknown', 'Detail', strcat('from ', Clients, ' clients')),
    pack('Order', 2, 'Signal', 'Not NOERROR', 'Value', FailPct, 'State', case(FailPct >= 20, 'Unavailable', FailPct >= 5, 'Degraded', 'Available'),
        'Detail', strcat('% · ', Failed, ' lookups')),
    pack('Order', 3, 'Signal', 'SERVFAIL', 'Value', ServFail, 'State', iff(ServFail > 0, 'Degraded', 'Available'),
        'Detail', 'the upstream server failed'),
    pack('Order', 4, 'Signal', 'Answer time (p95)', 'Value', round(P95, 0), 'State', case(P95 >= 1000, 'Unavailable', P95 >= 200, 'Degraded', 'Available'),
        'Detail', 'milliseconds'),
    pack('Order', 5, 'Signal', 'Proxy errors', 'Value', Errors, 'State', iff(Errors > 0, 'Degraded', 'Available'),
        'Detail', 'timeouts, upstream unreachable'))
| mv-expand r = rows
| project Order = toint(r.Order), Signal = tostring(r.Signal), Value = toreal(r.Value), State = tostring(r.State),
    Detail = tostring(r.Detail)
| order by Order asc
"""

FW_TREND_Q = FW_DNS + "FwDns\n| summarize Lookups = count() by bin(TimeGenerated, {TimeRange:grain}), ResponseCode\n"

FW_LATENCY_Q = FW_DNS + "FwDns\n| summarize P95 = percentile(Ms, 95) by bin(TimeGenerated, {TimeRange:grain}), Firewall\n"

FW_BY_FIREWALL_Q = FW_DNS + r"""FwDns
| summarize Lookups = count(), Clients = dcount(SourceIp), Failed = countif(ResponseCode != 'NOERROR'),
    ServFail = countif(ResponseCode == 'SERVFAIL'), P50 = round(percentile(Ms, 50), 1), P95 = round(percentile(Ms, 95), 1),
    Tcp = countif(Protocol =~ 'TCP'), Last = max(TimeGenerated) by Firewall
| extend FailPct = round(100.0 * Failed / Lookups, 1), TcpPct = round(100.0 * Tcp / Lookups, 1)
| project Firewall, Lookups, Clients, FailPct, ServFail, P50, P95, TcpPct, Last
| order by Lookups desc
"""

FW_FAILING_Q = FW_DNS + r"""FwDns
| where ResponseCode != 'NOERROR'
| summarize Lookups = count(), Clients = dcount(SourceIp), Firewalls = strcat_array(make_set(Firewall, 3), ', '),
    Last = max(TimeGenerated) by QueryName, QueryType, ResponseCode
| top 100 by Lookups desc
"""

FW_SLOW_Q = FW_DNS + r"""FwDns
| summarize Lookups = count(), P95 = round(percentile(Ms, 95), 0), Max = round(max(Ms), 0) by QueryName
| where Lookups >= 5 and P95 >= 500
| top 50 by P95 desc
"""

FW_CLIENTS_Q = FW_DNS + r"""FwDns
| summarize Lookups = count(), Names = dcount(QueryName), Failed = countif(ResponseCode != 'NOERROR'),
    Top = strcat_array(make_set(QueryName, 3), ', ') by SourceIp
| extend FailPct = round(100.0 * Failed / Lookups, 1)
| top 50 by Lookups desc
"""

FW_ERRORS_Q = FW_DNS + r"""FwDns
| where isnotempty(ErrorMessage)
| summarize Count = count(), Names = strcat_array(make_set(QueryName, 5), ', '), Last = max(TimeGenerated) by Firewall, ErrorMessage
| order by Count desc
"""

# The firewall failing to resolve an FQDN in a network rule (resource-specific category AZFWFqdnResolveFailure,
# written to the AZFWInternalFqdnResolutionFailure table). The rule matches nothing while this goes on.
FQDN_FAIL_Q = r"""
union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (AZFWInternalFqdnResolutionFailure)
| where TimeGenerated {TimeRange}
| extend Fqdn = tostring(column_ifexists('Fqdn', '')), ServerIp = tostring(column_ifexists('ServerIp', '')),
    Error = tostring(column_ifexists('Error', '')), Policy = tostring(column_ifexists('Policy', '')),
    Rule = strcat_delim(' / ', tostring(column_ifexists('RuleCollectionGroup', '')), tostring(column_ifexists('RuleCollection', '')),
        tostring(column_ifexists('Rule', ''))),
    Firewall = tostring(split(tostring(column_ifexists('_ResourceId', '')), '/')[-1])
| summarize Failures = count(), Last = max(TimeGenerated) by Firewall, Fqdn, ServerIp, Error, Policy, Rule
| order by Failures desc
| take 200
"""

FW_LOG_NOTE = """\
From each firewall's diagnostic setting in **resource-specific** mode: *Azure Firewall DNS query* (`AZFWDnsQuery`) for
every lookup the proxy answers, and *Azure Firewall FQDN Resolution Failure* (`AZFWInternalFqdnResolutionFailure`)
for FQDN network rules it cannot resolve. *Not NOERROR* includes NXDOMAIN, which is normal in small numbers (a client
trying its DNS suffixes, an AAAA lookup for a name with no IPv6 address). SERVFAIL and proxy errors mean the server
the proxy forwards to did not answer: check it is up and that the firewall can reach it on port 53. A high share of
TCP lookups is usually large answers being truncated over UDP."""

# ---------------------------------------------------------------------------
# Private DNS zones (Resource Graph)
# ---------------------------------------------------------------------------

# The subscription that holds most privatelink zones is taken as the central one; a privatelink zone anywhere else
# splits resolution, since only one copy of each zone can be linked to the networks that resolve it.
ZONES = r"""
resources
| where type =~ 'microsoft.network/privatednszones'
| extend Zone = tolower(name), Kind = iff(name startswith 'privatelink.' or name has '.privatelink.', 'Private Link', 'Custom'),
    RecordSets = toint(properties.numberOfRecordSets), MaxRecordSets = toint(properties.maxNumberOfRecordSets),
    Links = toint(properties.numberOfVirtualNetworkLinks), MaxLinks = toint(properties.maxNumberOfVirtualNetworkLinks),
    RegistrationLinks = toint(properties.numberOfVirtualNetworkLinksWithRegistration)
| extend RecordSetPct = round(100.0 * RecordSets / MaxRecordSets, 1), LinkPct = round(100.0 * Links / MaxLinks, 1)
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/privatednszones'
    | summarize Copies = count() by Zone = tolower(name)
  ) on Zone
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/privatednszones'
    | where name startswith 'privatelink.' or name has '.privatelink.'
    | summarize Zones = count() by subscriptionId
    | top 1 by Zones desc
    | project subscriptionId, Central = true
  ) on subscriptionId
| extend Findings = array_concat(
    iff(Links == 0, dynamic(['Not linked to any VNet']), dynamic([])),
    iff(Copies > 1, dynamic(['Exists more than once']), dynamic([])),
    iff(Kind == 'Private Link' and Central != true, dynamic(['Private Link zone outside the central subscription']), dynamic([])),
    iff(RecordSetPct >= 80, dynamic(['Record sets near the limit']), dynamic([])),
    iff(LinkPct >= 80, dynamic(['VNet links near the limit']), dynamic([])),
    iff(Kind == 'Private Link' and RegistrationLinks > 0, dynamic(['Auto-registration on a Private Link zone']), dynamic([])))
"""

ZONES_Q = ZONES + SUBSCRIPTION_NAMES + r"""
| project id, Kind, RecordSets, RecordSetPct, Links, LinkPct, RegistrationLinks, Copies,
    Findings = strcat_array(Findings, ' · '), Subscription, ResourceGroup = resourceGroup
| order by case(isnotempty(Findings), 0, 1) asc, Kind asc, tostring(id) asc
"""

ZONE_FINDINGS_Q = ZONES + SUBSCRIPTION_NAMES + r"""
| mv-expand Finding = Findings to typeof(string)
| where isnotempty(Finding)
| project Finding, id, Kind, Copies, RecordSetPct, LinkPct, Subscription, ResourceGroup = resourceGroup
| order by Finding asc
"""

ZONE_FINDING = status_fmt("Finding", warn=["Not linked to any VNet", "Record sets near the limit", "VNet links near the limit",
                                           "Auto-registration on a Private Link zone"],
                          bad=["Exists more than once", "Private Link zone outside the central subscription"])

# Every VNet link, flagged when it is not in service, points at a VNet that no longer exists (or is in a
# subscription not selected), or falls back to the internet for names the zone does not hold.
LINKS_Q = r"""
resources
| where type =~ 'microsoft.network/privatednszones/virtualnetworklinks'
| extend Vnet = tolower(tostring(properties.virtualNetwork.id))
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/virtualnetworks'
    | project Vnet = tolower(id), Exists = true
  ) on Vnet
| project Zone = tostring(split(id, '/')[8]), Link = name, Vnet,
    State = tostring(properties.virtualNetworkLinkState),
    Registration = iff(tobool(properties.registrationEnabled), 'Yes', 'No'),
    Fallback = iff(tostring(properties.resolutionPolicy) =~ 'NxDomainRedirect', 'Internet fallback', 'Default'),
    Problem = case(tostring(properties.virtualNetworkLinkState) !~ 'Completed', 'Link not completed',
        Exists != true, 'VNet not found (deleted, or not in the selected subscriptions)', ''),
    Provisioning = tostring(properties.provisioningState), id = tostring(split(tolower(id), '/virtualnetworklinks/')[0])
| order by case(isnotempty(Problem), 0, 1) asc, Zone asc
"""

# Endpoints with no private DNS zone group: nothing registers their address in the central zones.
PE_NO_GROUP_Q = r"""
resources
| where type =~ 'microsoft.network/privateendpoints'
| where array_length(properties.customDnsConfigs) > 0
| extend conns = iff(array_length(properties.privateLinkServiceConnections) > 0,
    properties.privateLinkServiceConnections, properties.manualPrivateLinkServiceConnections)
| project id, Target = tostring(conns[0].properties.privateLinkServiceId), SubResource = tostring(conns[0].properties.groupIds[0]),
    Names = strcat_array(properties.customDnsConfigs, ''), subscriptionId, ResourceGroup = resourceGroup
| extend Names = strcat_array(extract_all(@'"fqdn":"([^"]+)"', Names), ', ')
""" + SUBSCRIPTION_NAMES + "| project-away subscriptionId, subscriptionId1"

ZONES_NOTE = """\
In a landing zone, each Private Link zone (`privatelink.blob.core.windows.net` and so on) should exist **once**, in
the connectivity subscription, linked to the VNet of the DNS Private Resolver (and any other VNet that resolves with
Azure DNS directly), with records added by each private endpoint's DNS zone group (usually through Azure Policy). A
second copy of a zone, or one in a landing zone subscription, answers only the VNets linked to it, and those VNets
then cannot see the records in the central copy. The central subscription is taken to be the one with the most
Private Link zones. *Internet fallback* on a link (resolution policy *NxDomainRedirect*) sends names the zone does not
hold to public DNS, which avoids failures for resources without a private endpoint."""

# ---------------------------------------------------------------------------
# Resolvers, rulesets and DNS security policies (Resource Graph and Resource Manager)
# ---------------------------------------------------------------------------

POLICIES_Q = r"""
resources
| where type in~ ('microsoft.network/dnsresolverpolicies', 'microsoft.network/dnsresolverdomainlists')
| extend Kind = iff(type =~ 'microsoft.network/dnsresolverpolicies', 'DNS security policy', 'Domain list')
| project Kind, id, Domains = array_length(properties.domains), Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup, Location = location
| order by Kind desc, tostring(id) asc
"""

BLOCKED_Q = r"""
union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (DNSQueryLogs)
| where TimeGenerated {TimeRange}
| extend Action = tostring(column_ifexists('ResolverPolicyRuleAction', ''))
| where isnotempty(Action) and Action !~ 'Allow'
| extend QueryName = tolower(trim_end(@'\.', tostring(column_ifexists('QueryName', '')))),
    Client = tostring(column_ifexists('SourceIpAddress', '')),
    Vnet = tostring(split(tostring(column_ifexists('VirtualNetworkId', '')), '/')[-1]),
    List = tostring(split(tostring(column_ifexists('ResolverPolicyDomainListId', '')), '/')[-1])
| summarize Lookups = count(), Clients = dcount(Client), TopClients = strcat_array(make_set(Client, 3), ', '), Last = max(TimeGenerated)
    by QueryName, Action, List, Vnet
| top 100 by Lookups desc
"""

RESOLVERS_NOTE = """\
**DNS Private Resolver** answers on its *inbound endpoints* (the address on-premises conditional forwarders and
secured hub firewalls forward to) with Azure DNS from its own VNet, so it sees the private DNS zones linked there.
*Outbound endpoints* with a **forwarding ruleset** send chosen domains elsewhere, usually on-premises domain
controllers; a ruleset acts for every VNet linked to it. A **DNS security policy** filters lookups made through Azure
DNS in the VNets linked to it, against domain lists, and logs them to `DNSQueryLogs`."""

# ---------------------------------------------------------------------------
# DNS servers each VNet hands out (Resource Graph)
# ---------------------------------------------------------------------------

VNET_SERVERS = r"""
resources
| where type =~ 'microsoft.network/virtualnetworks'
| extend Custom = array_length(properties.dhcpOptions.dnsServers) > 0
| mv-expand Server = iff(Custom, properties.dhcpOptions.dnsServers, pack_array('168.63.129.16')) to typeof(string)
| join kind=leftouter (""" + SERVERS + r"""
  ) on $left.Server == $right.Ip
| extend Kind = case(Server == '168.63.129.16', 'Azure-provided DNS', isnotempty(Kind), Kind,
    'Not in Azure (on-premises or third party)')
| summarize Servers = strcat_array(make_list(Server), ', '), Kinds = make_set(Kind), ServerCount = count(),
    VmServers = countif(Kind startswith 'Virtual machine') by id, subscriptionId, resourceGroup
| extend Kind = iff(array_length(Kinds) == 1, tostring(Kinds[0]), 'Mixed'),
    Finding = case(
        set_has_element(Kinds, 'Azure Firewall (DNS proxy is off)'), 'Points at a firewall whose DNS proxy is off',
        array_length(Kinds) > 1, 'Mixed kinds of server: clients may get different answers',
        Kinds[0] == 'Not in Azure (on-premises or third party)', 'Resolves through servers outside Azure',
        VmServers == 1 and ServerCount == 1, 'One DNS server VM, no second',
        '')"""

VNETS_Q = VNET_SERVERS + SUBSCRIPTION_NAMES + r"""
| project Finding, id, Kind, Servers, Subscription, ResourceGroup = resourceGroup
| order by case(isnotempty(Finding), 0, 1) asc, Kind asc
"""

VNET_PIE_Q = VNET_SERVERS + "\n| summarize VNets = count() by Kind\n| order by VNets desc"

VNET_KIND = status_fmt("Kind", good=["DNS Private Resolver inbound endpoint", "Azure Firewall (DNS proxy)"],
                       warn=["Mixed", "Not in Azure (on-premises or third party)", "Azure Firewall (DNS proxy is off)"],
                       neutral=["Azure-provided DNS", "Virtual machine (custom DNS server)"])

NIC_OVERRIDES_Q = r"""
resources
| where type =~ 'microsoft.network/networkinterfaces'
| where array_length(properties.dnsSettings.dnsServers) > 0
| project id = tolower(coalesce(tostring(properties.virtualMachine.id), id)), Nic = name,
    Servers = strcat_array(properties.dnsSettings.dnsServers, ', '),
    Vnet = """ + vnet_of("tostring(properties.ipConfigurations[0].properties.subnet.id)") + r""",
    subscriptionId, ResourceGroup = resourceGroup
""" + SUBSCRIPTION_NAMES + "| project-away subscriptionId, subscriptionId1"

VNETS_NOTE = """\
Every VM gets its DNS servers from its VNet (or its NIC, which overrides the VNet) when it starts or renews its
lease, so a change reaches running VMs only after a restart or `ipconfig /renew`. In a landing zone, spokes usually
point at the central resolution service: the secured hub firewall's DNS proxy, or a DNS Private Resolver inbound
endpoint. *Azure-provided DNS* (168.63.129.16) resolves only the private DNS zones linked to that VNet itself.
*Mixed* servers (say a firewall and an on-premises server) are used in no fixed order, so clients can get different
answers for the same name."""

# ---------------------------------------------------------------------------
# Lookups from every DNS log (Log Analytics)
# ---------------------------------------------------------------------------

# Each source in one shape. Tables exist only once something has written to them, so each is read through an empty
# placeholder table and column_ifexists. DNS security policy and the Windows DNS Analytics log record the DNS
# response code as a number.
LOOKUPS = r"""let Rcode = (code: string) { case(code == '0', 'NOERROR', code == '1', 'FORMERR', code == '2', 'SERVFAIL',
    code == '3', 'NXDOMAIN', code == '4', 'NOTIMP', code == '5', 'REFUSED', toupper(code)) };
let Lookups = union isfuzzy=true
    (datatable(TimeGenerated: datetime, Log: string, Server: string, ClientIp: string, Query: string, QueryType: string,
        Result: string, Answer: string)[]),
    (union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (AZFWDnsQuery)
    | where TimeGenerated {TimeRange}
    | project TimeGenerated, Log = 'Azure Firewall DNS proxy', Server = tostring(split(tostring(column_ifexists('_ResourceId', '')), '/')[-1]),
        ClientIp = tostring(column_ifexists('SourceIp', '')), Query = tostring(column_ifexists('QueryName', '')),
        QueryType = tostring(column_ifexists('QueryType', '')), Result = Rcode(tostring(column_ifexists('ResponseCode', ''))), Answer = ''),
    (union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (DNSQueryLogs)
    | where TimeGenerated {TimeRange}
    | project TimeGenerated, Log = 'DNS security policy', Server = tostring(split(tostring(column_ifexists('VirtualNetworkId', '')), '/')[-1]),
        ClientIp = tostring(column_ifexists('SourceIpAddress', '')), Query = tostring(column_ifexists('QueryName', '')),
        QueryType = tostring(column_ifexists('QueryType', '')), Result = Rcode(tostring(column_ifexists('ResponseCode', ''))),
        Answer = tostring(column_ifexists('Answer', ''))),
    (union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (DnsEvents)
    | where TimeGenerated {TimeRange}
    | where tostring(column_ifexists('SubType', '')) == 'LookupQuery'
    | project TimeGenerated, Log = 'Windows DNS server', Server = tostring(column_ifexists('Computer', '')),
        ClientIp = tostring(column_ifexists('ClientIP', '')), Query = tostring(column_ifexists('Name', '')),
        QueryType = tostring(column_ifexists('QueryType', '')), Result = Rcode(tostring(column_ifexists('ResultCode', ''))),
        Answer = tostring(column_ifexists('IPAddresses', ''))),
    (union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (ASimDnsActivityLogs)
    | where TimeGenerated {TimeRange}
    | project TimeGenerated, Log = 'DNS server (ASIM)', Server = tostring(column_ifexists('Dvc', '')),
        ClientIp = tostring(column_ifexists('SrcIpAddr', '')), Query = tostring(column_ifexists('DnsQuery', '')),
        QueryType = tostring(column_ifexists('DnsQueryTypeName', '')), Result = toupper(tostring(column_ifexists('DnsResponseCodeName', ''))),
        Answer = tostring(column_ifexists('DnsResponseName', '')))
    | extend Query = tolower(trim_end(@'\.', Query))
    | where isempty(@'{Name}') or Query contains tolower(trim(@'[\s.]+', @'{Name}'))
    | where isempty(@'{ClientIp}') or ClientIp == trim(@'\s+', @'{ClientIp}');
"""

LOOKUP_TILES_Q = LOOKUPS + r"""Lookups
| summarize Lookups = count(), NxDomain = countif(Result == 'NXDOMAIN'), ServFail = countif(Result in ('SERVFAIL', 'REFUSED')),
    PrivateLinkMissing = countif(Result == 'NXDOMAIN' and Query has '.privatelink.'), Clients = dcount(ClientIp), Logs = dcount(Log)
| extend rows = pack_array(
    pack('Order', 1, 'Signal', 'DNS lookups logged', 'Value', Lookups, 'State', 'Unknown', 'Detail', strcat('from ', Clients, ' clients, ', Logs, ' kinds of log')),
    pack('Order', 2, 'Signal', 'NXDOMAIN', 'Value', NxDomain, 'State', 'Unknown',
        'Detail', iff(Lookups > 0, strcat(round(100.0 * NxDomain / Lookups, 1), '% of lookups'), '')),
    pack('Order', 3, 'Signal', 'SERVFAIL or REFUSED', 'Value', ServFail, 'State', iff(ServFail > 0, 'Degraded', 'Available'),
        'Detail', 'a server could not answer'),
    pack('Order', 4, 'Signal', 'Private Link names missing', 'Value', PrivateLinkMissing,
        'State', iff(PrivateLinkMissing > 0, 'Unavailable', 'Available'), 'Detail', 'NXDOMAIN for a privatelink name'))
| mv-expand r = rows
| project Order = toint(r.Order), Signal = tostring(r.Signal), Value = toint(r.Value), State = tostring(r.State),
    Detail = tostring(r.Detail)
| order by Order asc
"""

LOOKUP_TREND_Q = LOOKUPS + "Lookups\n| summarize Lookups = count() by bin(TimeGenerated, {TimeRange:grain}), Result\n"

LOOKUP_BY_SERVER_Q = LOOKUPS + r"""Lookups
| summarize Lookups = count(), Clients = dcount(ClientIp), NxDomain = countif(Result == 'NXDOMAIN'),
    ServFail = countif(Result in ('SERVFAIL', 'REFUSED')), Last = max(TimeGenerated) by Log, Server
| extend FailPct = round(100.0 * (NxDomain + ServFail) / Lookups, 1)
| order by Lookups desc
"""

# A privatelink name that does not exist: the endpoint's record is missing from the zone (no DNS zone group), the
# zone is not linked where the lookup is made, or the endpoint was deleted and a client still uses the name.
PRIVATELINK_MISSING_Q = LOOKUPS + r"""Lookups
| where Result == 'NXDOMAIN' and Query has '.privatelink.'
| summarize Lookups = count(), Clients = dcount(ClientIp), TopClients = strcat_array(make_set(ClientIp, 3), ', '),
    Servers = strcat_array(make_set(strcat(Log, ': ', Server), 3), ', '), Last = max(TimeGenerated)
    by Query, Zone = substring(Query, indexof(Query, 'privatelink.'))
| order by Lookups desc
| take 200
"""

LOOKUP_FAILING_Q = LOOKUPS + r"""Lookups
| where Result !in ('NOERROR', '')
| summarize Lookups = count(), Clients = dcount(ClientIp), Servers = strcat_array(make_set(Server, 3), ', '),
    Last = max(TimeGenerated) by Query, QueryType, Result
| top 100 by Lookups desc
"""

LOOKUP_CLIENTS_Q = LOOKUPS + r"""Lookups
| summarize Lookups = count(), Names = dcount(Query), Failed = countif(Result !in ('NOERROR', '')),
    Top = strcat_array(make_set(Query, 3), ', '), Logs = strcat_array(make_set(Log), ', ') by ClientIp
| extend FailPct = round(100.0 * Failed / Lookups, 1)
| top 50 by Lookups desc
"""

QUERIES_NOTE = """\
Lookups from every DNS log in the workspace, in one shape: Azure Firewall DNS proxy (`AZFWDnsQuery`), DNS security
policy (`DNSQueryLogs`), and Windows DNS servers (`DnsEvents` from DNS Analytics, or `ASimDnsActivityLogs`). Lookups
made straight to Azure DNS from a VNet with no DNS security policy are not logged anywhere. Filter with **Name** and
**Client IP** at the top. For one name, the **DNS and private endpoints** workbook works out which zone, record and
server should answer it."""

RESULT = status_fmt("Result", good=["NOERROR"], warn=["NXDOMAIN"], bad=["SERVFAIL", "REFUSED", "FORMERR", "NOTIMP"])
FAIL_PCT = low_is_good("FailPct", 5, 20)

# ---------------------------------------------------------------------------
# Overview tiles (Resource Graph)
# ---------------------------------------------------------------------------

PROXY_TILE_Q = FIREWALLS + r"""
| summarize Firewalls = count(), On = countif(Proxy), Problems = countif(State == 'Problem'), Checks = countif(State == 'Check')
| project Signal = 'Firewalls with DNS proxy', Value = On, State = case(Problems > 0, 'Unavailable', Checks > 0, 'Degraded', 'Available'),
    Detail = strcat('of ', Firewalls, ' · ', Problems + Checks, ' with findings')
"""

ZONES_TILE_Q = ZONES + r"""
| summarize Zones = count(), PrivateLink = countif(Kind == 'Private Link'), WithFindings = countif(array_length(Findings) > 0)
| project Signal = 'Private DNS zones', Value = Zones, State = iff(WithFindings > 0, 'Degraded', 'Available'),
    Detail = strcat(PrivateLink, ' Private Link · ', WithFindings, ' with findings')
"""

VNETS_TILE_Q = VNET_SERVERS + r"""
| summarize VNets = count(), WithFindings = countif(isnotempty(Finding)), Central = countif(Kind in ('DNS Private Resolver inbound endpoint', 'Azure Firewall (DNS proxy)'))
| project Signal = 'VNets with DNS findings', Value = WithFindings, State = iff(WithFindings > 0, 'Degraded', 'Available'),
    Detail = strcat('of ', VNets, ' · ', Central, ' use a resolver or firewall')
"""

RESOLVERS_TILE_Q = r"""
resources
| where type =~ 'microsoft.network/dnsresolvers'
| summarize Resolvers = count(), Down = countif(tostring(properties.dnsResolverState) !~ 'Connected' or tostring(properties.provisioningState) !~ 'Succeeded')
| project Signal = 'DNS Private Resolvers', Value = Resolvers, State = iff(Down > 0, 'Unavailable', iff(Resolvers == 0, 'Unknown', 'Available')),
    Detail = strcat(Down, ' disconnected or failed')
"""

PE_TILE_Q = r"""
resources
| where type =~ 'microsoft.network/privateendpoints'
| summarize Endpoints = count(), NoGroup = countif(array_length(properties.customDnsConfigs) > 0)
| project Signal = 'Endpoints without a zone group', Value = NoGroup, State = iff(NoGroup > 0, 'Degraded', 'Available'),
    Detail = strcat('of ', Endpoints, ' private endpoints')
"""

# ---------------------------------------------------------------------------
# Parameters, tabs and layout
# ---------------------------------------------------------------------------

Q_ZONES = "resources\n| where type =~ 'microsoft.network/privatednszones'"


def global_params():
    return params(f"{P}-params", [
        subscription_param(P),
        workspace_param(P, "The workspace that receives the firewall, DNS security policy and DNS server logs."),
        time_param(P, DAY_MS, [h * 3600000 for h in (1, 4, 12)] + [d * DAY_MS for d in (1, 3, 7, 14, 30)],
                   "For the DNS logs and zone metrics."),
        free_text_param(P, "Name", "Name contains", "Optional. Only lookups for names containing this."),
        free_text_param(P, "ClientIp", "Client IP", "Optional. Only lookups from this address."),
        {"id": gid(f"{P}-param-selectedTab"), "version": "KqlParameterItem/1.0", "name": "selectedTab", "type": 1,
         "value": "overview", "isHiddenWhenLocked": True},
    ])


def tabs():
    return {"type": 11, "content": {"version": "LinkItem/1.0", "style": "tabs", "links": [
        {"id": gid(f"{P}-tab-" + key), "cellValue": "selectedTab", "linkTarget": "parameter",
         "linkLabel": label, "subTarget": key, "style": "link"} for key, label in TABS
    ]}, "name": f"{P}-tabs"}


TILES = big_number_tiles("Signal", "State", "Value", "Detail")
WORKSPACE_HINT = ("Select a **Log Analytics workspace** at the top for what the DNS servers are answering: Azure "
                  "Firewall DNS proxy, DNS security policy and Windows DNS server logs.")
FIREWALL_LABELS = {"id": "Firewall", "ProxyIp": "DNS proxy address", "Forwarding": "Forwards to",
                   "Clients": "VNets using it", "FqdnRules": "FQDN network rules", "Rules": "Rules from",
                   "ResourceGroup": "Resource group"}


def firewall_table(name, title, query):
    return arg(name, title, query,
               formatters=[PROXY_STATE, resource_link(), resource_link("Network"), resource_link("Policy"),
                           resource_link("Parent"), status_fmt("Proxy", good=["On"], neutral=["Off"])],
               labels=FIREWALL_LABELS, no_data="No Azure Firewalls in the selected subscriptions.")


def overview_tab():
    return group(f"{P}-tab-overview", [
        arg(f"{P}-tile-proxy", "", PROXY_TILE_Q, vis="tiles", tiles=TILES, fixed_px=ONE_TILE),
        arg(f"{P}-tile-zones", "", ZONES_TILE_Q, vis="tiles", tiles=TILES, fixed_px=ONE_TILE),
        arg(f"{P}-tile-vnets", "", VNETS_TILE_Q, vis="tiles", tiles=TILES, fixed_px=ONE_TILE),
        arg(f"{P}-tile-resolvers", "", RESOLVERS_TILE_Q, vis="tiles", tiles=TILES, fixed_px=ONE_TILE),
        arg(f"{P}-tile-pe", "", PE_TILE_Q, vis="tiles", tiles=TILES, fixed_px=ONE_TILE),
        text(f"{P}-hint", WORKSPACE_HINT, "info", visible_when=WORKSPACE_UNSET),
        la(f"{P}-lookup-tiles", "", LOOKUP_TILES_Q, vis="tiles", tiles=TILES),
        firewall_table(f"{P}-overview-firewalls", "Azure Firewall DNS proxy", FIREWALLS_Q),
        arg(f"{P}-overview-zones", "Private DNS zone findings", ZONE_FINDINGS_Q, width=50,
            formatters=[ZONE_FINDING, resource_link()], labels={"id": "Zone", "RecordSetPct": "Record sets %",
                                                               "LinkPct": "Links %", "ResourceGroup": "Resource group"},
            no_data="No findings on the private DNS zones."),
        arg(f"{P}-overview-vnets", "VNets by kind of DNS server", VNET_PIE_Q, vis="piechart", width=50),
        la(f"{P}-overview-trend", "DNS lookups by result", LOOKUP_TREND_Q, vis="timechart"),
    ], tab="overview")


def proxy_tab():
    return group(f"{P}-tab-proxy", [
        firewall_table(f"{P}-firewalls", "Firewalls and their DNS proxy", FIREWALLS_Q),
        text(f"{P}-proxy-note", PROXY_NOTE, "info"),
        arg(f"{P}-forwarders", "Where each DNS proxy forwards", FORWARDERS_Q,
            formatters=[resource_link("Firewall"), FORWARD_KIND, resource_link("Owner"), resource_link("Lookup")],
            labels={"Lookup": "Looks up from", "Then": "And then"},
            no_data="No firewall with DNS proxy on forwards to custom servers: they all use Azure DNS."),
        text(f"{P}-proxy-logs-h", "### What the proxy is answering"),
        text(f"{P}-proxy-hint", "Select a **Log Analytics workspace** at the top for the firewalls' DNS query logs.",
             "info", visible_when=WORKSPACE_UNSET),
        la(f"{P}-fw-tiles", "", FW_TILES_Q, vis="tiles", tiles=TILES),
        la(f"{P}-fw-trend", "Proxy lookups by response code", FW_TREND_Q, vis="timechart", width=50),
        la(f"{P}-fw-latency", "Answer time, milliseconds (p95 by firewall)", FW_LATENCY_Q,
           vis="timechart", width=50),
        la(f"{P}-fw-by-firewall", "By firewall", FW_BY_FIREWALL_Q,
           formatters=[FAIL_PCT, low_is_good("P95", 200, 1000), low_is_good("ServFail", 1, 100)],
           labels={"FailPct": "Not NOERROR %", "ServFail": "SERVFAIL", "P50": "p50 ms", "P95": "p95 ms", "TcpPct": "TCP %"},
           no_data="No DNS proxy logs in the time range. Turn on the AZFWDnsQuery category (resource-specific) on the "
                   "firewalls' diagnostic settings."),
        la(f"{P}-fw-failing", "Names the proxy did not resolve", FW_FAILING_Q, width=50,
           formatters=[status_fmt("ResponseCode", warn=["NXDOMAIN"], bad=["SERVFAIL", "REFUSED"])],
           labels={"QueryName": "Name", "QueryType": "Type", "ResponseCode": "Response"},
           no_data="Every proxy lookup returned NOERROR."),
        la(f"{P}-fw-clients", "Busiest clients", FW_CLIENTS_Q, width=50, formatters=[FAIL_PCT],
           labels={"SourceIp": "Client", "Names": "Distinct names", "FailPct": "Not NOERROR %", "Top": "Example names"},
           no_data="No proxy lookups."),
        la(f"{P}-fw-slow", "Slow names (p95 of 500 ms or more)", FW_SLOW_Q, width=50,
           labels={"QueryName": "Name", "P95": "p95 ms", "Max": "Slowest ms"},
           no_data="No name took 500 ms or more at the 95th percentile."),
        la(f"{P}-fw-errors", "Proxy errors", FW_ERRORS_Q, width=50, labels={"ErrorMessage": "Error", "Names": "Example names"},
           no_data="The proxy reported no errors."),
        la(f"{P}-fqdn-failures", "FQDN network rules the firewall cannot resolve", FQDN_FAIL_Q,
           labels={"ServerIp": "DNS server", "Rule": "Rule (group / collection / rule)"},
           no_data="No FQDN resolution failures, or the AZFWFqdnResolveFailure category is not collected."),
        text(f"{P}-fw-log-note", FW_LOG_NOTE, "info"),
    ], tab="proxy")


def zones_tab():
    return group(f"{P}-tab-zones", [
        arg(f"{P}-zones", "Private DNS zones", ZONES_Q,
            formatters=[resource_link(), low_is_good("RecordSetPct", 70, 90), low_is_good("LinkPct", 70, 90),
                        low_is_good("Copies", 2, 2), status_fmt("Kind", neutral=["Private Link", "Custom"])],
            labels={"id": "Zone", "RecordSets": "Record sets", "RecordSetPct": "Record sets % of limit",
                    "LinkPct": "Links % of limit", "RegistrationLinks": "Auto-registration links",
                    "ResourceGroup": "Resource group"},
            group_by="Kind", no_data="No private DNS zones in the selected subscriptions."),
        text(f"{P}-zones-note", ZONES_NOTE, "info"),
        arg(f"{P}-links", "Virtual network links", LINKS_Q,
            formatters=[resource_link(), resource_link("Vnet"), PROVISIONING,
                        status_fmt("State", good=["Completed"], warn=["InProgress"]),
                        status_fmt("Problem", bad=["Link not completed", "VNet not found (deleted, or not in the selected subscriptions)"]),
                        status_fmt("Fallback", neutral=["Internet fallback"])],
            labels={"id": "Zone resource", "Vnet": "VNet", "Fallback": "Names the zone does not hold"},
            no_data="No virtual network links."),
        arg(f"{P}-pe-no-group", "Private endpoints with no DNS zone group", PE_NO_GROUP_Q,
            formatters=[resource_link(), resource_link("Target")],
            labels={"id": "Private endpoint", "SubResource": "Sub-resource", "Names": "Names it needs",
                    "ResourceGroup": "Resource group"},
            no_data="Every private endpoint has a DNS zone group."),
        text(f"{P}-pe-note", "Nothing registers these endpoints' addresses in the central zones, so their names "
             "resolve to the public address unless someone keeps the records by hand. Add a zone group (or let the "
             "landing zone's *Deploy-Private-DNS-Zones* policies do it).", "info"),
        params(f"{P}-zone-params", [resource_param("Zones", "Zones to chart", Q_ZONES, first=10)]),
        metrics(f"{P}-zone-queries", "Queries answered per zone", ZNS, "Zones", [m(ZNS, "QueryVolume", SUM)], width=50),
        metrics(f"{P}-zone-capacity", "Record sets, % of limit", ZNS, "Zones", [m(ZNS, "RecordSetCapacityUtilization", MAX)],
                width=50),
    ], tab="zones")


def resolvers_tab():
    rule_cols = [("Rule", "$.name", None), ("Domain", "$.properties.domainName", None),
                 ("Targets", "$.properties.targetDnsServers", None), ("State", "$.properties.forwardingRuleState", None)]
    link_cols = [("Link", "$.name", None), ("VNet", "$.properties.virtualNetwork.id", None),
                 ("Provisioning", "$.properties.provisioningState", None)]
    return group(f"{P}-tab-resolvers", [
        arg(f"{P}-resolvers", "DNS Private Resolvers", RESOLVERS_Q,
            formatters=[resource_link("resolver"), resource_link("Vnet"), PROVISIONING,
                        status_fmt("State", good=["Connected"], bad=["Disconnected"])],
            labels={"resolver": "Resolver", "Vnet": "VNet", "Inbound": "Inbound endpoint addresses",
                    "Outbound": "Outbound endpoints"},
            no_data="No DNS Private Resolvers in the selected subscriptions."),
        text(f"{P}-resolvers-note", RESOLVERS_NOTE, "info"),
        arg(f"{P}-rulesets", "Forwarding rulesets", RULESETS_Q, formatters=[resource_link(), PROVISIONING],
            labels={"id": "Ruleset", "Resolvers": "Resolvers (outbound endpoints)"},
            no_data="No forwarding rulesets."),
        params(f"{P}-ruleset-params", [{
            "id": gid(f"{P}-param-Ruleset"), "version": "KqlParameterItem/1.0", "name": "Ruleset",
            "label": "Ruleset", "type": 5, "isRequired": False, "multiSelect": False, "query": RULESET_PICK_Q,
            "crossComponentResources": ["{Subscription}"],
            "typeSettings": {"additionalResourceOptions": [], "showDefault": False},
            "queryType": 1, "resourceType": "microsoft.resourcegraph/resources",
            "description": "Pick a ruleset to see its rules and the VNets linked to it."}]),
        when_set(arm(f"{P}-rules", "Forwarding rules", "{Ruleset}/forwardingRules", "2022-07-01", rule_cols,
                     url_params=[("$top", "1000")], no_data="The ruleset has no rules.", width=60,
                     formatters=[status_fmt("State", good=["Enabled"], warn=["Disabled"])]), "Ruleset"),
        when_set(arm(f"{P}-ruleset-links", "VNets linked to the ruleset", "{Ruleset}/virtualNetworkLinks", "2022-07-01",
                     link_cols, no_data="No VNets are linked to this ruleset.", width=40,
                     formatters=[resource_link("VNet")]), "Ruleset"),
        text(f"{P}-policies-h", "### DNS security policies"),
        arg(f"{P}-policies", "DNS security policies and domain lists", POLICIES_Q,
            formatters=[resource_link(), PROVISIONING], labels={"id": "Resource", "ResourceGroup": "Resource group"},
            no_data="No DNS security policies or domain lists."),
        la(f"{P}-blocked", "Lookups a DNS security policy blocked or alerted on", BLOCKED_Q,
           labels={"QueryName": "Name", "List": "Domain list", "Vnet": "VNet", "TopClients": "Example clients"},
           no_data="No lookups blocked or alerted on in the time range, or no DNS security policy logs here."),
    ], tab="resolvers")


def vnets_tab():
    return group(f"{P}-tab-vnets", [
        arg(f"{P}-vnet-pie", "VNets by kind of DNS server", VNET_PIE_Q, vis="piechart", width=35),
        text(f"{P}-vnets-note", VNETS_NOTE, "info"),
        arg(f"{P}-vnets", "DNS servers each VNet hands out", VNETS_Q,
            formatters=[status_fmt("Finding", warn=["Mixed kinds of server: clients may get different answers",
                                                    "Resolves through servers outside Azure",
                                                    "One DNS server VM, no second"],
                                   bad=["Points at a firewall whose DNS proxy is off"]),
                        resource_link(), VNET_KIND],
            labels={"id": "VNet", "Kind": "Kind of server", "Servers": "DNS servers", "ResourceGroup": "Resource group"},
            no_data="No VNets in the selected subscriptions."),
        arg(f"{P}-nic-overrides", "NICs with their own DNS servers (overriding the VNet)", NIC_OVERRIDES_Q,
            formatters=[resource_link(), resource_link("Vnet")],
            labels={"id": "VM (or NIC)", "Nic": "NIC", "Servers": "DNS servers", "Vnet": "VNet",
                    "ResourceGroup": "Resource group"},
            no_data="No NIC overrides its VNet's DNS servers."),
    ], tab="vnets")


def queries_tab():
    return group(f"{P}-tab-queries", [
        text(f"{P}-queries-hint", WORKSPACE_HINT, "info", visible_when=WORKSPACE_UNSET),
        text(f"{P}-queries-note", QUERIES_NOTE, "info"),
        la(f"{P}-q-tiles", "", LOOKUP_TILES_Q, vis="tiles", tiles=TILES),
        la(f"{P}-q-trend", "Lookups by result", LOOKUP_TREND_Q, vis="timechart"),
        la(f"{P}-q-servers", "By log and server", LOOKUP_BY_SERVER_Q, formatters=[FAIL_PCT],
           labels={"FailPct": "Failed %", "NxDomain": "NXDOMAIN", "ServFail": "SERVFAIL or REFUSED"},
           no_data="No DNS logs in the time range."),
        la(f"{P}-q-privatelink", "Private Link names that do not exist (NXDOMAIN)", PRIVATELINK_MISSING_Q,
           labels={"Query": "Name", "TopClients": "Example clients", "Servers": "Answered by"},
           no_data="No privatelink name returned NXDOMAIN."),
        text(f"{P}-q-privatelink-note", "An NXDOMAIN for a `privatelink` name means the zone exists but holds no "
             "record for it: the private endpoint has no DNS zone group, the record was deleted, or the endpoint is "
             "gone and something still uses the name. Look the name up in the **DNS and private endpoints** "
             "workbook.", "info"),
        la(f"{P}-q-failing", "Names that failed", LOOKUP_FAILING_Q, width=50, formatters=[RESULT],
           labels={"Query": "Name", "QueryType": "Type"}, no_data="Every lookup returned NOERROR."),
        la(f"{P}-q-clients", "Busiest clients", LOOKUP_CLIENTS_Q, width=50, formatters=[FAIL_PCT],
           labels={"ClientIp": "Client", "Names": "Distinct names", "FailPct": "Failed %", "Top": "Example names"},
           no_data="No lookups."),
    ], tab="queries")


def workbook():
    return notebook([
        text(f"{P}-header", "# DNS\n"
             "DNS across the estate: Azure Firewall DNS proxy, private DNS zones and their links, DNS Private "
             "Resolvers, forwarding rulesets and DNS security policies, the DNS servers each VNet uses, and what the "
             "DNS servers are answering. To follow one name, use the **DNS and private endpoints** workbook."),
        global_params(),
        tabs(),
        overview_tab(),
        proxy_tab(),
        zones_tab(),
        resolvers_tab(),
        vnets_tab(),
        queries_tab(),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
