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
    ("windns", "Windows DNS servers"),
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
# Windows DNS servers: internal, forwarded, and what goes to the watched forwarders (Log Analytics)
# ---------------------------------------------------------------------------

# Every query event a Windows DNS server (an AD domain controller) logs, in one shape. Three ways the events reach a
# workspace: Sentinel's "Windows DNS Events via AMA" connector (ASimDnsActivityLogs), Microsoft-Windows-DNSServer
# events in the Event or WindowsEvent table, and the retired DNS Analytics solution (DnsEvents, lookups only, with
# nothing on forwarding). The analytical log's event IDs: 256 query received, 257 response sent, 258 failure sent,
# 259 query ignored, 260 query forwarded or recursed out (Peer is where it went), 261 answer back from there,
# 262 no answer from there. Internal means a server answered from a zone it holds (the AA flag, or a zone name on
# the response), or the name ends in one of the Internal suffixes.
WINDNS = r"""let RcodeName = (code: string) { case(code == '0', 'NOERROR', code == '1', 'FORMERR', code == '2', 'SERVFAIL',
    code == '3', 'NXDOMAIN', code == '4', 'NOTIMP', code == '5', 'REFUSED', toupper(code)) };
let QtypeName = (t: string) { case(t == '1', 'A', t == '2', 'NS', t == '5', 'CNAME', t == '6', 'SOA', t == '12', 'PTR',
    t == '15', 'MX', t == '16', 'TXT', t == '28', 'AAAA', t == '33', 'SRV', t == '64', 'SVCB', t == '65', 'HTTPS',
    t == '255', 'ANY', t) };
let DomainOf = (q: string) { let l = split(q, '.'); let n = array_length(l);
    iff(n <= 2, q, iff(strlen(tostring(l[n - 1])) == 2 and strlen(tostring(l[n - 2])) <= 3,
        strcat_array(array_slice(l, n - 3, n - 1), '.'), strcat_array(array_slice(l, n - 2, n - 1), '.'))) };
let Watch = set_difference(split(replace_regex(trim(@'[\s,;]+', @'{Forwarders}'), @'[\s,;]+', ','), ','), dynamic(['']));
let Suffixes = set_difference(split(replace_regex(trim(@'[\s,;.]+', tolower(@'{InternalSuffixes}')), @'[\s,;]+', ','), ','),
    dynamic(['']));
let WinDns = union isfuzzy=true
    (datatable(TimeGenerated: datetime, Log: string, Server: string, ServerIp: string, EventId: int, Client: string,
        Peer: string, Query: string, QueryType: string, Rcode: string, Zone: string, Authoritative: bool)[]),
    (union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (ASimDnsActivityLogs)
    | where TimeGenerated {TimeRange}
    | extend EventId = toint(column_ifexists('EventOriginalType', '')), Src = tostring(column_ifexists('SrcIpAddr', '')),
        Dst = tostring(column_ifexists('DstIpAddr', ''))
    | where EventId between (256 .. 262)
    | project TimeGenerated, Log = 'ASimDnsActivityLogs',
        Server = coalesce(tostring(column_ifexists('DvcHostname', '')), tostring(column_ifexists('Dvc', ''))),
        ServerIp = tostring(column_ifexists('DvcIpAddr', '')), EventId,
        Client = iff(EventId between (256 .. 259), Src, ''), Peer = case(EventId in (260, 262), Dst, EventId == 261, Src, ''),
        Query = tostring(column_ifexists('DnsQuery', '')), QueryType = tostring(column_ifexists('DnsQueryTypeName', '')),
        Rcode = toupper(tostring(column_ifexists('DnsResponseCodeName', ''))), Zone = '',
        Authoritative = tostring(column_ifexists('DnsFlagsAuthoritative', '')) in~ ('true', '1')),
    (union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (Event)
    | where TimeGenerated {TimeRange}
    | where tostring(column_ifexists('Source', '')) == 'Microsoft-Windows-DNSServer'
    | extend EventId = toint(column_ifexists('EventID', 0))
    | where EventId between (256 .. 262)
    | extend X = parse_xml(tostring(column_ifexists('EventData', '')))
    | extend D = iff(isnotempty(X.DataItem), X.DataItem.EventData.Data, X.EventData.Data)
    | mv-apply D on (summarize F = make_bag(bag_pack(tostring(D['@Name']), tostring(D['#text']))))
    | project TimeGenerated, Log = 'Event', Server = tostring(column_ifexists('Computer', '')),
        ServerIp = tostring(F.InterfaceIP), EventId,
        Client = case(EventId == 256, tostring(F.Source), EventId between (257 .. 259), tostring(F.Destination), ''),
        Peer = case(EventId in (260, 262), tostring(F.Destination), EventId == 261, tostring(F.Source), ''),
        Query = tostring(F.QNAME), QueryType = tostring(F.QTYPE), Rcode = tostring(F.RCODE), Zone = tostring(F.Zone),
        Authoritative = tostring(F.AA) == '1'),
    (union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (WindowsEvent)
    | where TimeGenerated {TimeRange}
    | where tostring(column_ifexists('Provider', '')) == 'Microsoft-Windows-DNSServer'
    | extend EventId = toint(column_ifexists('EventID', 0)), F = todynamic(column_ifexists('EventData', dynamic(null)))
    | where EventId between (256 .. 262)
    | project TimeGenerated, Log = 'WindowsEvent', Server = tostring(column_ifexists('Computer', '')),
        ServerIp = tostring(F.InterfaceIP), EventId,
        Client = case(EventId == 256, tostring(F.Source), EventId between (257 .. 259), tostring(F.Destination), ''),
        Peer = case(EventId in (260, 262), tostring(F.Destination), EventId == 261, tostring(F.Source), ''),
        Query = tostring(F.QNAME), QueryType = tostring(F.QTYPE), Rcode = tostring(F.RCODE), Zone = tostring(F.Zone),
        Authoritative = tostring(F.AA) == '1'),
    (union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (DnsEvents)
    | where TimeGenerated {TimeRange}
    | where tostring(column_ifexists('SubType', '')) == 'LookupQuery'
    | project TimeGenerated, Log = 'DnsEvents', Server = tostring(column_ifexists('Computer', '')), ServerIp = '',
        EventId = toint(256), Client = tostring(column_ifexists('ClientIP', '')), Peer = '',
        Query = tostring(column_ifexists('Name', '')), QueryType = tostring(column_ifexists('QueryType', '')),
        Rcode = tostring(column_ifexists('ResultCode', '')), Zone = '', Authoritative = false)
    | extend Query = tolower(trim_end(@'\.', Query)), QueryType = QtypeName(QueryType), Rcode = RcodeName(Rcode)
    | where isempty(@'{Name}') or Query contains tolower(trim(@'[\s.]+', @'{Name}'))
    | extend Internal = Authoritative or (isnotempty(Zone) and Zone !startswith '..')
        or (array_length(Suffixes) > 0 and Query has_any (Suffixes)),
        PeerKind = case(isempty(Peer), '', set_has_element(Watch, Peer), 'Watched forwarder',
            Peer == '168.63.129.16', 'Azure DNS (168.63.129.16)', ipv4_is_private(Peer), 'Private address',
            'Other public DNS');
"""

# Each lookup a client made (event 256), with how its server got the answer: from a zone it holds, by forwarding
# the name (to which kind of server, the watched forwarders first), or neither, which is the cache.
ANSWERED = WINDNS + r"""let Forwarded = WinDns
    | where EventId == 260
    | summarize Rank = min(case(PeerKind == 'Watched forwarder', 1, PeerKind startswith 'Azure', 2,
        PeerKind == 'Private address', 3, 4)) by Server, Query;
let Own = WinDns
    | where Internal
    | summarize Own = true, OwnZone = take_anyif(Zone, isnotempty(Zone) and Zone !startswith '..') by Query;
let Received = WinDns
    | where EventId == 256
    | lookup kind=leftouter Forwarded on Server, Query
    | lookup kind=leftouter Own on Query
    | extend Answer = case(Own == true, 'Own zone (internal)', Rank == 1, 'Forwarded to a watched forwarder',
        Rank == 2, 'Forwarded to Azure DNS', Rank == 3, 'Forwarded to a private DNS server',
        Rank == 4, 'Forwarded to other public DNS', 'From cache, or the forward was not logged');
"""

WINDNS_SOURCES_Q = WINDNS + r"""let Found = WinDns
    | summarize Events = count(), Servers = dcount(Server), Last = max(TimeGenerated) by Table = Log, EventId
    | extend Detail = case(EventId == 256, '256 query received', EventId == 257, '257 response sent',
        EventId == 258, '258 failure sent', EventId == 259, '259 query ignored', EventId == 260, '260 forwarded or recursed out',
        EventId == 261, '261 answer from forwarder', EventId == 262, '262 forwarder timed out', tostring(EventId))
    | extend Detail = iff(Table == 'DnsEvents', 'Lookups (DNS Analytics, no forwarding detail)', Detail);
let OtherDnsEvents = union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (Event)
    | where TimeGenerated {TimeRange}
    | where tostring(column_ifexists('Source', '')) has 'DNS' or tostring(column_ifexists('EventLog', '')) has 'DNS'
    | where not(tostring(column_ifexists('Source', '')) == 'Microsoft-Windows-DNSServer'
        and toint(column_ifexists('EventID', 0)) between (256 .. 262))
    | summarize Events = count(), Servers = dcount(tostring(column_ifexists('Computer', ''))), Last = max(TimeGenerated)
        by Detail = strcat(tostring(column_ifexists('EventLog', '')), ' (not query events)')
    | extend Table = 'Event', EventId = toint(0);
let CustomTables = union isfuzzy=true (datatable(TimeGenerated: datetime, DataType: string, Quantity: real)[]), (Usage)
    | where TimeGenerated {TimeRange}
    | where DataType has 'dns' and DataType !in ('ASimDnsActivityLogs', 'DnsEvents', 'AZFWDnsQuery', 'DNSQueryLogs')
    | summarize MB = sum(Quantity), Last = max(TimeGenerated) by Table = DataType
    | extend Events = long(null), Servers = long(null), EventId = toint(0), Detail = strcat(round(MB, 1), ' MB: not read here');
union Found, OtherDnsEvents, (CustomTables | project-away MB)
| project Table, Detail, Events, Servers, Last, EventId
| order by Table asc, EventId asc
| project-away EventId
"""

WINDNS_TILES_Q = ANSWERED + r"""let Out = WinDns
    | summarize Watched = countif(EventId == 260 and PeerKind == 'Watched forwarder'),
        WatchedNames = dcountif(Query, EventId == 260 and PeerKind == 'Watched forwarder'),
        Timeouts = countif(EventId == 262);
Received
| summarize Lookups = count(), Internal = countif(Answer startswith 'Own'), Forwarded = countif(Answer startswith 'Forwarded'),
    Clients = dcount(Client), Servers = dcount(Server)
| extend placeholder = 1
| join kind=inner (Out | extend placeholder = 1) on placeholder
| extend rows = pack_array(
    pack('Order', 1, 'Signal', 'Lookups received', 'Value', Lookups, 'State', 'Unknown',
        'Detail', strcat('from ', Clients, ' clients on ', Servers, ' DNS servers')),
    pack('Order', 2, 'Signal', 'Answered from own zones', 'Value', Internal, 'State', 'Unknown',
        'Detail', iff(Lookups > 0, strcat(round(100.0 * Internal / Lookups, 1), '% internal'), '')),
    pack('Order', 3, 'Signal', 'Forwarded', 'Value', Forwarded, 'State', 'Unknown',
        'Detail', iff(Lookups > 0, strcat(round(100.0 * Forwarded / Lookups, 1), '% external'), '')),
    pack('Order', 4, 'Signal', 'Sent to watched forwarders', 'Value', Watched, 'State', 'Unknown',
        'Detail', strcat(WatchedNames, ' distinct names')),
    pack('Order', 5, 'Signal', 'Forwarder timeouts', 'Value', Timeouts, 'State', iff(Timeouts > 0, 'Degraded', 'Available'),
        'Detail', 'no answer from where a name was sent'))
| mv-expand r = rows
| project Order = toint(r.Order), Signal = tostring(r.Signal), Value = tolong(r.Value), State = tostring(r.State),
    Detail = tostring(r.Detail)
| order by Order asc
"""

WINDNS_TREND_Q = ANSWERED + "Received\n| summarize Lookups = count() by bin(TimeGenerated, {TimeRange:grain}), Answer\n"

WINDNS_ANSWER_PIE_Q = ANSWERED + "Received\n| summarize Lookups = count() by Answer\n| order by Lookups desc\n"

WINDNS_FORWARDERS_Q = WINDNS + r"""WinDns
| where EventId in (260, 261, 262) and isnotempty(Peer)
| summarize Sent = countif(EventId == 260), Answered = countif(EventId == 261), Timeouts = countif(EventId == 262),
    Names = dcountif(Query, EventId == 260), Servers = strcat_array(make_set(Server, 5), ', '), Last = max(TimeGenerated)
    by Peer, PeerKind
| extend TimeoutPct = round(100.0 * Timeouts / max_of(Sent, 1), 1)
| order by Sent desc
"""

WINDNS_INTERNAL_Q = ANSWERED + r"""Received
| where Answer startswith 'Own'
| summarize Lookups = count(), Names = dcount(Query), Clients = dcount(Client), Failed = countif(Rcode !in ('NOERROR', '')),
    Servers = strcat_array(make_set(Server, 5), ', '), Examples = strcat_array(make_set(Query, 3), ', ')
    by Zone = iff(isnotempty(OwnZone), tolower(OwnZone), DomainOf(Query))
| order by Lookups desc
"""

WINDNS_EXTERNAL_Q = WINDNS + r"""WinDns
| where EventId == 260 and not(Internal)
| summarize Forwards = count(), Names = dcount(Query), To = strcat_array(make_set(PeerKind), ', '),
    Watched = countif(PeerKind == 'Watched forwarder'), Servers = strcat_array(make_set(Server, 5), ', '),
    Examples = strcat_array(make_set(Query, 3), ', ') by Domain = DomainOf(Query)
| top 200 by Forwards desc
"""

WINDNS_WATCHED_Q = WINDNS + r"""WinDns
| where EventId in (260, 262) and PeerKind == 'Watched forwarder'
| summarize Sent = countif(EventId == 260), Timeouts = countif(EventId == 262), To = strcat_array(make_set(Peer), ', '),
    Servers = strcat_array(make_set(Server, 5), ', '), Last = max(TimeGenerated) by Query, QueryType, Domain = DomainOf(Query)
| top 500 by Sent desc
"""

WINDNS_WATCHED_CLIENTS_Q = WINDNS + r"""let Sent = WinDns
    | where EventId == 260 and PeerKind == 'Watched forwarder'
    | distinct Server, Query;
WinDns
| where EventId == 256
| join kind=inner Sent on Server, Query
| summarize Lookups = count(), Names = dcount(Query), Examples = strcat_array(make_set(Query, 5), ', '),
    Servers = strcat_array(make_set(Server, 3), ', '), Last = max(TimeGenerated) by Client
| top 200 by Lookups desc
"""

# Port 53 straight to a watched forwarder through Azure Firewall. A source that is not one of the DNS servers in
# these logs is a client bypassing them (its own DNS settings, or hard-coded resolvers).
WINDNS_FIREWALL_Q = WINDNS + r"""let ServerIps = WinDns
    | where isnotempty(ServerIp)
    | distinct ServerIp;
union isfuzzy=true
    (datatable(TimeGenerated: datetime, SourceIp: string, DestinationIp: string, DestinationPort: int, Action: string,
        _ResourceId: string)[]),
    (AZFWNetworkRule | where TimeGenerated {TimeRange})
| where set_has_element(Watch, DestinationIp) and DestinationPort == 53
| summarize Connections = count(), Denied = countif(Action =~ 'Deny'), To = strcat_array(make_set(DestinationIp), ', '),
    Firewalls = strcat_array(make_set(tostring(split(_ResourceId, '/')[-1]), 3), ', '), Last = max(TimeGenerated) by SourceIp
| join kind=leftouter (ServerIps | extend IsServer = true) on $left.SourceIp == $right.ServerIp
| extend Source = iff(IsServer == true, 'DNS server in these logs', 'Not a DNS server in these logs')
| project SourceIp, Source, Connections, Denied, To, Firewalls, Last
| order by Connections desc
"""

WINDNS_NOTE = """\
What the Windows DNS servers (the domain controllers) are doing, from their query events. **Internal** lookups are
answered from a zone the server holds, such as the AD domain. **External** lookups are forwarded to another server.
Each name a server forwards is counted, with where it went. List the **Watched forwarders** (by default the
Cisco Umbrella / OpenDNS resolvers) to see exactly which names go to them, and which clients asked for them.

The query events come from the DNS server's analytical log (event IDs 256 to 262). They reach the workspace in one
of these ways:

- Sentinel's **Windows DNS Events via AMA** connector (`ASimDnsActivityLogs`).
- `Microsoft-Windows-DNSServer` events in `Event` or `WindowsEvent`.
- The retired DNS Analytics solution (`DnsEvents`). This gives lookups only, so it can't show forwarding. Use
  **Internal suffixes** to split those lookups.

The **DNS Server** event log (event 4013 and the like) and the Audit log record server and zone changes, not
lookups. The first table shows which of these logs this workspace holds."""

WINDNS_FIREWALL_NOTE = """\
Port 53 connections straight to a watched forwarder, from Azure Firewall's network rule log (`AZFWNetworkRule`). The
DNS servers sending their forwards should be the only sources. Any other source is a client that bypasses them,
through its own DNS settings or a hard-coded resolver. Each of these connections, like each forward, takes a SNAT
port on the firewall. The **Azure Firewall** workbook's **Sources by destination** tab breaks them down further."""

PEER_KIND = status_fmt("PeerKind", good=["Azure DNS (168.63.129.16)", "Private address"], warn=["Watched forwarder"],
                       neutral=["Other public DNS"])
SOURCE_KIND = status_fmt("Source", good=["DNS server in these logs"], warn=["Not a DNS server in these logs"])
TIMEOUT_PCT = low_is_good("TimeoutPct", 1, 5)

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


def windns_tab():
    return group(f"{P}-tab-windns", [
        text(f"{P}-windns-hint", WORKSPACE_HINT, "info", visible_when=WORKSPACE_UNSET),
        text(f"{P}-windns-note", WINDNS_NOTE, "info"),
        params(f"{P}-windns-params", [
            free_text_param(P, "Forwarders", "Watched forwarders",
                            "Forwarder addresses to follow, separated by commas. Cisco Umbrella / OpenDNS by default.",
                            value="208.67.222.222, 208.67.220.220"),
            free_text_param(P, "InternalSuffixes", "Internal suffixes",
                            "Optional. Your internal domains, separated by commas (contoso.local, corp.contoso.com). "
                            "A name ending in one counts as internal, on top of what the servers answered from their "
                            "own zones."),
        ]),
        la(f"{P}-windns-sources", "DNS server logs in this workspace", WINDNS_SOURCES_Q,
           no_data="No DNS server logs in the time range."),
        la(f"{P}-windns-tiles", "", WINDNS_TILES_Q, vis="tiles", tiles=TILES),
        la(f"{P}-windns-trend", "How lookups were answered", WINDNS_TREND_Q, vis="timechart", width=67),
        la(f"{P}-windns-pie", "Internal and external", WINDNS_ANSWER_PIE_Q, vis="piechart", width=33),
        la(f"{P}-windns-forwarders", "Where the DNS servers forward", WINDNS_FORWARDERS_Q,
           formatters=[PEER_KIND, TIMEOUT_PCT],
           labels={"Peer": "Forwarded to", "PeerKind": "Kind", "Names": "Distinct names", "TimeoutPct": "Timeouts %",
                   "Servers": "From DNS servers"},
           no_data="No forwarding events (260). DnsEvents and the DNS Server event log don't record forwarding."),
        la(f"{P}-windns-internal", "Internal: zones the DNS servers answered from", WINDNS_INTERNAL_Q, width=50,
           labels={"Names": "Distinct names", "Failed": "Not NOERROR", "Examples": "Example names"},
           no_data="No lookups answered from the servers' own zones."),
        la(f"{P}-windns-external", "External: domains the DNS servers forwarded", WINDNS_EXTERNAL_Q, width=50,
           labels={"Names": "Distinct names", "To": "Forwarded to", "Watched": "To watched forwarders",
                   "Examples": "Example names"},
           no_data="No forwarded names."),
        la(f"{P}-windns-watched", "Names sent to the watched forwarders", WINDNS_WATCHED_Q, width=50,
           labels={"Query": "Name", "QueryType": "Type", "Sent": "Forwards", "To": "Sent to",
                   "Servers": "From DNS servers"},
           no_data="Nothing was forwarded to the watched forwarders."),
        la(f"{P}-windns-watched-clients", "Clients behind those names", WINDNS_WATCHED_CLIENTS_Q, width=50,
           labels={"Client": "Client", "Names": "Distinct names", "Examples": "Example names",
                   "Servers": "Asked DNS servers"},
           no_data="No client lookups (256) match names sent to the watched forwarders."),
        text(f"{P}-windns-fw-note", WINDNS_FIREWALL_NOTE, "info"),
        la(f"{P}-windns-firewall", "Port 53 to the watched forwarders through Azure Firewall", WINDNS_FIREWALL_Q,
           formatters=[SOURCE_KIND], labels={"SourceIp": "Source", "Source": "Is it a DNS server?",
                                             "To": "Destination"},
           no_data="No port 53 connections to the watched forwarders in AZFWNetworkRule."),
    ], tab="windns")


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
        windns_tab(),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
