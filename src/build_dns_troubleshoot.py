"""Generates the DNS and private endpoint troubleshooting workbook.

Run:  python src/build_dns_troubleshoot.py
Out:  workbook/dns-troubleshoot.workbook.json

Answers "why does this name not resolve, or resolve to the wrong address?" for a name served through Private
Link. From Resource Graph: the private endpoint behind the name and the address it should resolve to, the
private DNS zones that can answer it and the virtual networks they are linked to, and which DNS server a client
uses and where that server does its lookups. From Resource Manager: the records in a zone and the forwarding
rules of a DNS Private Resolver ruleset. From Log Analytics (optional): what DNS servers actually answered,
from Azure Firewall DNS proxy, DNS security policy and Windows DNS server logs. Built from the helpers in
build_workbook.py so the workbooks look alike.
"""

import pathlib

from build_workbook import (DAY_MS, PROVISIONING, WORKSPACE_SET, WORKSPACE_UNSET, arg, arm, choice_param,
                            free_text_param, gid, hidden_arg_param, la, notebook, params, resource_link, status_fmt,
                            subscription_param, text, time_param, when_set, workspace_param, write_workbook)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "dns-troubleshoot.workbook.json"

P = "dns"
HOUR_MS = 3600000

# ---------------------------------------------------------------------------
# The name, worked out the same way in every query
# ---------------------------------------------------------------------------

# Resource Graph has no `let`, so each query extends its rows with the name as typed (N), its first label and the
# Private Link form of it (PL): mystg.blob.core.windows.net is a CNAME to mystg.privatelink.blob.core.windows.net,
# and that is the name the privatelink zone holds. A URL, a trailing dot and upper case are all accepted.
NAME_COLS = r"""| extend N = trim_end(@'\.', extract(@'^(?:[a-z]+://)?([^/:?\s]+)', 1, tolower(trim(@'\s+', @'{Name}'))))
| extend Label = tostring(split(N, '.')[0])
| extend Rest = substring(N, strlen(Label) + 1)
| extend PL = iff(isempty(N) or Rest startswith 'privatelink.', N, strcat(Label, '.privatelink.', Rest))"""

NAME_LETS = r"""let N = trim_end(@'\.', extract(@'^(?:[a-z]+://)?([^/:?\s]+)', 1, tolower(trim(@'\s+', @'{Name}'))));
let Label = tostring(split(N, '.')[0]);
let Rest = substring(N, strlen(Label) + 1);
let PL = iff(isempty(N) or Rest startswith 'privatelink.', N, strcat(Label, '.privatelink.', Rest));
let Client = trim(@'\s+', @'{ClientIp}');"""

# A zone answers the name if it is the name itself or a parent of it, in either form.
ZONE_MATCHES = "(N == Zone or N endswith strcat('.', Zone) or PL == Zone or PL endswith strcat('.', Zone))"

# ---------------------------------------------------------------------------
# Private endpoints
# ---------------------------------------------------------------------------

# An endpoint holds its connection under one of two properties depending on whether it was auto-approved.
# customDnsConfigs is filled in only when the endpoint has no private DNS zone group, so it stands in for that.
PE_DETAILS = """
    resources
    | where type =~ 'microsoft.network/privateendpoints'
    | extend conns = iff(array_length(properties.privateLinkServiceConnections) > 0,
        properties.privateLinkServiceConnections, properties.manualPrivateLinkServiceConnections)
    | mv-expand c = conns
    | project pe = tolower(id), Connection = tostring(c.properties.privateLinkServiceConnectionState.status),
        Target = tostring(c.properties.privateLinkServiceId), SubResource = tostring(c.properties.groupIds[0]),
        Provisioning = tostring(properties.provisioningState),
        ZoneGroup = iff(array_length(properties.customDnsConfigs) > 0, 'None', 'Yes'),
        Subnet = tostring(split(tostring(properties.subnet.id), '/')[10]),
        Vnet = tostring(split(tostring(properties.subnet.id), '/')[8])"""

# Each endpoint for this name, found two ways: its network interface lists the FQDNs it serves, and its target
# resource is usually named after the first label (mystg for mystg.blob.core.windows.net).
PE_Q = f"""
resources
| where type =~ 'microsoft.network/networkinterfaces' and isnotempty(tostring(properties.privateEndpoint.id))
| mv-expand ipc = properties.ipConfigurations
| mv-expand f = ipc.properties.privateLinkConnectionProperties.fqdns
| extend Fqdn = tolower(tostring(f))
{NAME_COLS}
| where isnotempty(N) and (Fqdn == N or Fqdn == PL)
| project pe = tolower(tostring(properties.privateEndpoint.id)), Fqdn, Ip = tostring(ipc.properties.privateIPAddress)
| union (
    resources
    | where type =~ 'microsoft.network/privateendpoints'
    | mv-expand c = array_concat(properties.privateLinkServiceConnections, properties.manualPrivateLinkServiceConnections)
    {NAME_COLS.replace(chr(10), chr(10) + '    ')}
    | where isnotempty(Label) and tolower(tostring(split(tostring(c.properties.privateLinkServiceId), '/')[8])) == Label
    | project pe = tolower(id), Fqdn = '', Ip = '')
| summarize Fqdns = make_set_if(Fqdn, isnotempty(Fqdn)), Ips = make_set_if(Ip, isnotempty(Ip)) by pe
| join kind=inner ({PE_DETAILS}
  ) on pe
| project pe, ShouldResolveTo = strcat_array(Ips, ', '), Connection, ZoneGroup, Provisioning, Target, SubResource,
    Vnet, Subnet, Fqdns = strcat_array(Fqdns, ', ')
| order by case(Connection =~ 'Approved', 1, 0) asc, pe asc
"""

# ---------------------------------------------------------------------------
# Private DNS zones
# ---------------------------------------------------------------------------

# The virtual networks that do the lookups for the client: a hidden parameter, filled in by LOOKUP_VNETS_Q.
LINKED = "tolower(tostring(properties.virtualNetwork.id)) in~ ({LookupVnets})"

ZONES_Q = f"""
resources
| where type =~ 'microsoft.network/privatednszones'
| extend Zone = tolower(name)
{NAME_COLS}
| where isnotempty(N) and {ZONE_MATCHES}
| extend zone = tolower(id)
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/privatednszones'
    | summarize Copies = count() by Zone = tolower(name)
  ) on Zone
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/privatednszones/virtualnetworklinks'
    | summarize LinkedToLookup = countif({LINKED}),
        Fallback = countif(tostring(properties.resolutionPolicy) =~ 'NxDomainRedirect')
        by zone = tolower(tostring(split(id, '/virtualnetworklinks/')[0]))
  ) on zone
| project zone, Answers = iff(N == Zone or N endswith strcat('.', Zone), N, PL),
    LookupVnet = case(isempty(trim(@'\\s+', strcat(@'{{ClientIp}}', @'{{DnsServer}}'))), 'No client given',
        LinkedToLookup > 0, 'Linked', 'Not linked'),
    Copies, Links = toint(properties.numberOfVirtualNetworkLinks), RecordSets = toint(properties.numberOfRecordSets),
    Fallback = iff(Fallback > 0, 'On some links', 'Off'), ResourceGroup = resourceGroup, SubscriptionId = subscriptionId
| order by strlen(Answers) desc, LookupVnet asc
"""

LINKS_Q = f"""
resources
| where type =~ 'microsoft.network/privatednszones/virtualnetworklinks'
| extend Zone = tolower(tostring(split(id, '/')[8]))
{NAME_COLS}
| where isnotempty(N) and {ZONE_MATCHES}
| project zone = tolower(tostring(split(id, '/virtualnetworklinks/')[0])), Vnet = tolower(tostring(properties.virtualNetwork.id)),
    Lookup = iff({LINKED}, 'Yes', ''), State = tostring(properties.virtualNetworkLinkState),
    AutoRegistration = tostring(properties.registrationEnabled),
    Fallback = iff(tostring(properties.resolutionPolicy) =~ 'NxDomainRedirect', 'Internet fallback', 'Default'),
    Provisioning = tostring(properties.provisioningState)
| order by Lookup desc, zone asc
"""

# Zones for the record picker.
ZONE_PICK_Q = f"""
resources
| where type =~ 'microsoft.network/privatednszones'
| extend Zone = tolower(name)
{NAME_COLS}
| where isnotempty(N) and {ZONE_MATCHES}
| project value = id, label = strcat(name, ' (', resourceGroup, ')')
"""

# ---------------------------------------------------------------------------
# Which DNS server the client uses, and where it looks names up
# ---------------------------------------------------------------------------

# Every address that can be a DNS server, with the virtual network its lookups are made from:
# - Azure-provided DNS (168.63.129.16) looks up from the client's own network.
# - A DNS Private Resolver inbound endpoint looks up from the resolver's network, then its forwarding rulesets.
# - Azure Firewall DNS proxy looks up from the firewall's network, or forwards to the policy's custom servers.
# - Any other VM (a domain controller, say) looks up from its own network if it forwards to Azure DNS.
SERVERS = """
    resources
    | where type =~ 'microsoft.network/dnsresolvers/inboundendpoints'
    | mv-expand c = properties.ipConfigurations
    | project Ip = tostring(c.privateIpAddress), Kind = 'DNS Private Resolver inbound endpoint', Owner = tolower(id),
        Lookup = tolower(tostring(split(tostring(c.subnet.id), '/subnets/')[0])),
        Then = 'Private DNS zones linked to the resolver network, then forwarding rulesets linked to it'
    | union (
        // A Virtual WAN hub firewall has no IP configurations, only a hub address.
        resources
        | where type =~ 'microsoft.network/azurefirewalls'
        | extend hubIp = tostring(properties.hubIPAddresses.privateIPAddress)
        | mv-expand c = iff(isnotempty(hubIp), pack_array(hubIp), properties.ipConfigurations)
        | extend Ip = iff(isnotempty(hubIp), hubIp, tostring(c.properties.privateIPAddress)),
            Lookup = iff(isnotempty(hubIp), tolower(tostring(properties.virtualHub.id)),
                tolower(tostring(split(tostring(c.properties.subnet.id), '/subnets/')[0])))
        | where isnotempty(Ip)
        | project Ip, Lookup, Owner = tolower(id), policy = tolower(tostring(properties.firewallPolicy.id)))
    | join kind=leftouter (
        resources
        | where type =~ 'microsoft.network/firewallpolicies'
        | project policy = tolower(id), Proxy = tostring(properties.dnsSettings.enableProxy),
            Servers = strcat_array(properties.dnsSettings.servers, ', ')
      ) on policy
    | extend Kind = coalesce(Kind, iff(Proxy =~ 'true', 'Azure Firewall (DNS proxy)', 'Azure Firewall (DNS proxy is off)')),
        Then = coalesce(Then, iff(isempty(Servers), 'Azure DNS from the firewall network',
            strcat('Forwards to ', Servers, ': enter one as the DNS server to follow it')))
    | union (
        resources
        | where type =~ 'microsoft.network/networkinterfaces' and isnotempty(tostring(properties.virtualMachine.id))
        | mv-expand c = properties.ipConfigurations
        | project Ip = tostring(c.properties.privateIPAddress), Kind = 'Virtual machine (custom DNS server)',
            Owner = tolower(tostring(properties.virtualMachine.id)),
            Lookup = tolower(tostring(split(tostring(c.properties.subnet.id), '/subnets/')[0])),
            Then = 'Its own forwarders. Azure DNS (and so the private zones) only if it forwards to 168.63.129.16')
    | project Ip, Kind, Owner, Lookup, Then"""

# The client's network and subnet, and the DNS servers it is given. A DNS server typed in replaces them, for a
# client on-premises (whose forwarder points at a resolver inbound endpoint, say) or to follow a forwarding hop.
# It starts from one subscription row so there is a row to work with when only a DNS server is given.
CLIENT_SERVERS = r"""
resourcecontainers
| where type =~ 'microsoft.resources/subscriptions'
| take 1
| project k = 1
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/virtualnetworks'
    | mv-expand s = properties.subnets
    | extend prefixes = iff(array_length(s.properties.addressPrefixes) > 0, s.properties.addressPrefixes, pack_array(s.properties.addressPrefix))
    | where isnotempty(trim(@'\s+', @'{ClientIp}')) and ipv4_is_in_any_range(trim(@'\s+', @'{ClientIp}'), prefixes)
    | take 1
    | project k = 1, vnet = tolower(id), Subnet = tostring(s.name),
        Servers = iff(array_length(properties.dhcpOptions.dnsServers) > 0, properties.dhcpOptions.dnsServers, pack_array('168.63.129.16'))
  ) on k
| where isnotempty(vnet) or isnotempty(trim(@'\s+', @'{DnsServer}'))
| extend Servers = iff(isnotempty(trim(@'\s+', @'{DnsServer}')), split(replace_regex(trim(@'[\s,;]+', @'{DnsServer}'), @'[\s,;]+', ','), ','), Servers)
| mv-expand Server = Servers to typeof(string)"""

CLIENT_Q = CLIENT_SERVERS + f"""
| join kind=leftouter ({SERVERS}
  ) on $left.Server == $right.Ip
| extend Kind = case(Server == '168.63.129.16', 'Azure-provided DNS', isnotempty(Kind), Kind, 'Not an Azure resource in the selected subscriptions'),
    Lookup = case(Server == '168.63.129.16', vnet, Lookup),
    Then = case(Server == '168.63.129.16', 'Private DNS zones linked to the client network, then public DNS',
        isnotempty(Then), Then, 'On-premises or third-party DNS: it needs a conditional forwarder to a resolver inbound endpoint')
| project ClientVnet = vnet, Subnet, Server, Kind, Owner, Lookup, Then
"""

# The networks lookups are made from, as a quoted list for LINKED (an empty list would not parse, so '').
LOOKUP_VNETS_Q = CLIENT_Q + """| where isnotempty(Lookup)
| summarize ids = make_set(Lookup)
| project value = iff(array_length(ids) == 0, "''", strcat("'", strcat_array(ids, "','"), "'"))
"""

# ---------------------------------------------------------------------------
# DNS Private Resolver
# ---------------------------------------------------------------------------

RESOLVERS_Q = """
resources
| where type =~ 'microsoft.network/dnsresolvers'
| project resolver = tolower(id), Vnet = tolower(tostring(properties.virtualNetwork.id)),
    State = tostring(properties.dnsResolverState), Provisioning = tostring(properties.provisioningState), Location = location
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/dnsresolvers/inboundendpoints'
    | mv-expand c = properties.ipConfigurations
    | summarize Inbound = strcat_array(make_set(tostring(c.privateIpAddress)), ', ')
        by resolver = tolower(tostring(split(id, '/inboundendpoints/')[0]))
  ) on resolver
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/dnsresolvers/outboundendpoints'
    | summarize Outbound = count() by resolver = tolower(tostring(split(id, '/outboundendpoints/')[0]))
  ) on resolver
| project resolver, Vnet, Inbound, Outbound = coalesce(Outbound, 0), State, Provisioning, Location
"""

RULESETS_Q = """
resources
| where type =~ 'microsoft.network/dnsforwardingrulesets'
| project id, Resolvers = strcat_array(properties.dnsResolverOutboundEndpoints, ', '),
    Provisioning = tostring(properties.provisioningState), ResourceGroup = resourceGroup, Location = location
| extend Resolvers = extract_all(@'dnsResolvers/([^/]+)/', Resolvers)
| project id, Resolvers = strcat_array(Resolvers, ', '), Provisioning, ResourceGroup, Location
"""

RULESET_PICK_Q = "resources\n| where type =~ 'microsoft.network/dnsforwardingrulesets'\n| project id"

# ---------------------------------------------------------------------------
# What DNS servers actually answered (Log Analytics)
# ---------------------------------------------------------------------------

# Every source in one shape. Each table exists only once something has written to it, so each is read through an
# empty placeholder table and column_ifexists. Result codes are DNS RCODE names; the Windows DNS Analytics table
# logs the number.
DNS_LOGS = NAME_LETS + r"""
let Rcode = (code: int) { case(code == 0, 'NOERROR', code == 2, 'SERVFAIL', code == 3, 'NXDOMAIN', code == 5, 'REFUSED', tostring(code)) };
let Lookups = union isfuzzy=true
    (union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (AZFWDnsQuery)
    | where TimeGenerated {TimeRange}
    | project TimeGenerated, Log = 'Azure Firewall DNS proxy',
        Server = tostring(split(tostring(column_ifexists('_ResourceId', '')), '/')[-1]),
        ClientIp = tostring(column_ifexists('SourceIp', '')), Query = tostring(column_ifexists('QueryName', '')),
        QueryType = tostring(column_ifexists('QueryType', '')), Result = toupper(tostring(column_ifexists('ResponseCode', ''))),
        Answer = '', Detail = tostring(column_ifexists('ErrorMessage', ''))),
    (union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (DNSQueryLogs)
    | where TimeGenerated {TimeRange}
    | project TimeGenerated, Log = 'DNS security policy',
        Server = tostring(split(tostring(column_ifexists('VirtualNetworkId', '')), '/')[-1]),
        ClientIp = tostring(column_ifexists('SourceIpAddress', '')), Query = tostring(column_ifexists('QueryName', '')),
        QueryType = tostring(column_ifexists('QueryType', '')),
        Result = toupper(coalesce(tostring(column_ifexists('ResponseCode', '')), tostring(column_ifexists('QueryResponseCode', '')))),
        Answer = tostring(column_ifexists('Answer', '')),
        Detail = strcat_delim(' · ', tostring(column_ifexists('ResolutionPath', '')), tostring(column_ifexists('ResolverPolicyRuleAction', '')))),
    (union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (DnsEvents)
    | where TimeGenerated {TimeRange}
    | where tostring(column_ifexists('SubType', '')) == 'LookupQuery'
    | project TimeGenerated, Log = 'Windows DNS server', Server = tostring(column_ifexists('Computer', '')),
        ClientIp = tostring(column_ifexists('ClientIP', '')), Query = tostring(column_ifexists('Name', '')),
        QueryType = tostring(column_ifexists('QueryType', '')), Result = Rcode(toint(column_ifexists('ResultCode', int(null)))),
        Answer = tostring(column_ifexists('IPAddresses', '')), Detail = ''),
    (union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (ASimDnsActivityLogs)
    | where TimeGenerated {TimeRange}
    | project TimeGenerated, Log = 'DNS server (ASIM)', Server = tostring(column_ifexists('Dvc', '')),
        ClientIp = tostring(column_ifexists('SrcIpAddr', '')), Query = tostring(column_ifexists('DnsQuery', '')),
        QueryType = tostring(column_ifexists('DnsQueryTypeName', '')), Result = toupper(tostring(column_ifexists('DnsResponseCodeName', ''))),
        Answer = tostring(column_ifexists('DnsResponseName', '')), Detail = '')
| extend Query = tolower(trim_end(@'\.', Query))
| where isempty(N) or Query == N or Query == PL or Query endswith strcat('.', N)
| where isempty(Client) or ClientIp == Client
| extend AnswerIp = extract(@'(\d+\.\d+\.\d+\.\d+)', 1, Answer)
| extend Answered = case(Result != 'NOERROR', Result, isempty(AnswerIp), 'NOERROR',
    ipv4_is_private(AnswerIp), 'Private address', 'Public address');
"""

SUMMARY_LOG_Q = DNS_LOGS + """
Lookups
| summarize Lookups = count(), Clients = dcount(ClientIp), Answers = strcat_array(make_set_if(AnswerIp, isnotempty(AnswerIp), 5), ', '),
    LastSeen = max(TimeGenerated) by Log, Server, Query, QueryType, Answered
| order by case(Answered in ('NOERROR', 'Private address'), 1, 0) asc, Lookups desc
| take 200
"""

TIMELINE_LOG_Q = DNS_LOGS + """
Lookups
| summarize Lookups = count() by bin(TimeGenerated, {TimeRange:grain}), Answered
"""

EVENTS_LOG_Q = DNS_LOGS + """
Lookups
| top 500 by TimeGenerated desc
| project TimeGenerated, Log, Server, ClientIp, Query, QueryType, Answered, Answer, Detail
"""

ANSWERED = status_fmt("Answered", good=["Private address", "NOERROR"], warn=["Public address"],
                      bad=["NXDOMAIN", "SERVFAIL", "REFUSED"])

# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

HOW_TO = """\
Type the name that will not resolve, e.g. `mystg.blob.core.windows.net` (a URL works too). Add the **client IP**
to see which DNS server the client uses and whether that server can see the private zone. For a client
on-premises, or to follow a forwarder, put the DNS server's address in **DNS server** instead.

**How a Private Link name resolves.** The public name (`mystg.blob.core.windows.net`) is a CNAME to the
Private Link name (`mystg.privatelink.blob.core.windows.net`). Azure DNS answers that from a private DNS zone
**only if the zone is linked to the virtual network the lookup is made from**; otherwise it carries on to public
DNS and returns the public address. So check, in order:
1. **The endpoint:** approved, and with a DNS zone group, so its A record is written into the zone.
2. **The zone:** one copy of `privatelink.…` that holds the record. Two copies in different subscriptions each
   answer only for the networks linked to them.
3. **The lookup network:** the zone is linked to the network the DNS server looks up from (the client's own
   network for Azure-provided DNS; the resolver's network for a DNS Private Resolver; the firewall's for DNS proxy).
4. **On-premises:** a conditional forwarder for the public zone (`blob.core.windows.net`, not `privatelink.…`) to
   a resolver inbound endpoint."""

ZONES_NOTE = """\
*Lookup network* says whether the zone is linked to a network that resolves for the client (fill in *Client IP*
or *DNS server*). *Copies* above 1 means the same zone exists more than once: each copy answers only for the
networks linked to it, so the record may be in one and the client's network linked to the other. *Internet
fallback* (`NxDomainRedirect`) answers from public DNS when the private zone has no record, which hides a missing
record. A Virtual WAN hub cannot be linked to a zone, so a secured hub firewall's DNS proxy must forward to a
resolver."""

LOGS_NOTE = """\
*Answered* reads **Public address** when the lookup succeeded but returned a public IP: the private zone was not
used, so the request goes to the public endpoint (and is usually refused there). **NXDOMAIN** for the Private
Link name means the zone was used but has no record: check the endpoint's DNS zone group. Sources: Azure Firewall
DNS proxy (`AZFWDnsQuery`), DNS security policy (`DNSQueryLogs`), and Windows DNS servers (`DnsEvents`, or
`ASimDnsActivityLogs` from the Windows DNS events connector). Azure-provided DNS logs nothing on its own: add a DNS
security policy to the client network to see those lookups."""

# ---------------------------------------------------------------------------
# Workbook
# ---------------------------------------------------------------------------


def parameters():
    return params(f"{P}-params", [
        subscription_param(P),
        free_text_param(P, "Name", "Name to resolve",
                        "The FQDN (or URL) that will not resolve, e.g. mystg.blob.core.windows.net."),
        free_text_param(P, "ClientIp", "Client IP",
                        "Optional. The private IP of the machine doing the lookup, to find its network and DNS servers."),
        free_text_param(P, "DnsServer", "DNS server",
                        "Optional. The DNS server the client uses, if not its network's. For a client on-premises, the "
                        "address its forwarder sends to."),
        hidden_arg_param(P, "LookupVnets", LOOKUP_VNETS_Q),
        workspace_param(P, "Optional. The workspace your firewalls, DNS security policies or DNS servers log to."),
        time_param(P, HOUR_MS, (900000, HOUR_MS, 4 * HOUR_MS, 12 * HOUR_MS, DAY_MS, 3 * DAY_MS, 7 * DAY_MS),
                   "Applies to the DNS logs."),
    ])


def picker(name, label, query):
    return {"id": gid(f"{P}-param-{name}"), "version": "KqlParameterItem/1.0", "name": name, "label": label,
            "type": 5, "isRequired": False, "multiSelect": False, "query": query.strip(),
            "crossComponentResources": ["{Subscription}"], "typeSettings": {"showDefault": False},
            "queryType": 1, "resourceType": "microsoft.resourcegraph/resources"}


def workbook():
    record_cols = [("Record", "$.name", None), ("FQDN", "$.properties.fqdn", None),
                   ("Addresses", "$.properties.aRecords[*].ipv4Address", None), ("TTL", "$.properties.ttl", None),
                   ("Auto-registered", "$.properties.isAutoRegistered", None)]
    rule_cols = [("Rule", "$.name", None), ("Domain", "$.properties.domainName", None),
                 ("Target servers", "$.properties.targetDnsServers[*].ipAddress", None),
                 ("State", "$.properties.forwardingRuleState", None)]
    ruleset_link_cols = [("Link", "$.name", None), ("Virtual network", "$.properties.virtualNetwork.id", None)]
    return notebook([
        text(f"{P}-header", "# DNS and private endpoints\n"
             "Why does this name not resolve, or resolve to the wrong address? Follows a Private Link name from the "
             "endpoint to its private DNS zone, the networks the zone is linked to, and the DNS server the client "
             "uses, then shows what the DNS servers actually answered."),
        parameters(),
        text(f"{P}-howto", HOW_TO, "info"),
        when_set(arg(f"{P}-pe", "Private endpoints for this name", PE_Q,
                     formatters=[resource_link("pe"), resource_link("Target"), PROVISIONING,
                                 status_fmt("Connection", good=["Approved"], warn=["Pending"], bad=["Rejected", "Disconnected"]),
                                 status_fmt("ZoneGroup", good=["Yes"], warn=["None"])],
                     labels={"pe": "Private endpoint", "ShouldResolveTo": "Should resolve to", "ZoneGroup": "DNS zone group",
                             "SubResource": "Sub-resource", "Vnet": "Virtual network", "Fqdns": "Names it serves"},
                     no_data="No private endpoint serves this name in the selected subscriptions. The name resolves "
                             "publicly unless a zone holds a record for it by hand."), "Name"),
        when_set(arg(f"{P}-zones", "Private DNS zones that can answer this name", ZONES_Q,
                     formatters=[resource_link("zone"),
                                 status_fmt("LookupVnet", good=["Linked"], bad=["Not linked"], neutral=["No client given"]),
                                 {"columnMatch": "Copies", "formatter": 18, "formatOptions": {
                                     "thresholdsOptions": "icons", "thresholdsGrid": [
                                         {"operator": ">", "thresholdValue": "1", "representation": "2", "text": "{0}{1}"},
                                         {"operator": "Default", "thresholdValue": None, "representation": "success", "text": "{0}{1}"}]}},
                                 status_fmt("Fallback", warn=["On some links"])],
                     labels={"zone": "Zone", "Answers": "Answers for", "LookupVnet": "Lookup network",
                             "RecordSets": "Record sets", "Fallback": "Internet fallback", "SubscriptionId": "Subscription"},
                     no_data="No private DNS zone in the selected subscriptions covers this name, so Azure DNS answers it "
                             "from public DNS."), "Name"),
        when_set(text(f"{P}-zones-note", ZONES_NOTE, "info"), "Name"),
        when_set(arg(f"{P}-links", "Networks linked to those zones", LINKS_Q,
                     formatters=[resource_link("zone"), resource_link("Vnet"), status_fmt("Lookup", good=["Yes"]),
                                 status_fmt("State", good=["Completed"], warn=["InProgress"]),
                                 status_fmt("Fallback", warn=["Internet fallback"])],
                     labels={"zone": "Zone", "Vnet": "Virtual network", "Lookup": "Resolves for the client",
                             "AutoRegistration": "Auto-registration"},
                     no_data="The matching zones are not linked to any virtual network."), "Name"),
        text(f"{P}-client-h", "### The client's DNS servers"),
        arg(f"{P}-client", "DNS servers the client uses, and where each looks names up", CLIENT_Q,
            formatters=[resource_link("ClientVnet"), resource_link("Owner"), resource_link("Lookup")],
            labels={"ClientVnet": "Client network", "Server": "DNS server", "Kind": "Server is",
                    "Owner": "Resource", "Lookup": "Looks up from", "Then": "Then"},
            no_data="Enter a client IP or a DNS server. A client IP that is not in any virtual network in the selected "
                    "subscriptions is probably on-premises: enter its DNS server instead."),
        text(f"{P}-records-h", "### Records in a zone"),
        text(f"{P}-records-note", "Record sets are not in Resource Graph, so pick a zone to read its A records from "
             "Azure Resource Manager. The Private Link name needs an A record for the first label "
             "(e.g. `mystg`) pointing at the endpoint's address above.", "info"),
        params(f"{P}-zone-params", [picker("Zone", "Zone", ZONE_PICK_Q)]),
        when_set(arm(f"{P}-records", "A records", "{Zone}/A", "2020-06-01", record_cols, url_params=[("$top", "1000")],
                     no_data="The zone has no A records."), "Zone"),
        text(f"{P}-resolver-h", "### DNS Private Resolver"),
        arg(f"{P}-resolvers", "Resolvers and their inbound endpoints", RESOLVERS_Q,
            formatters=[resource_link("resolver"), resource_link("Vnet"), PROVISIONING,
                        status_fmt("State", good=["Connected"], bad=["Disconnected"])],
            labels={"resolver": "Resolver", "Vnet": "Virtual network", "Inbound": "Inbound endpoint IPs",
                    "Outbound": "Outbound endpoints"},
            no_data="No DNS Private Resolvers in the selected subscriptions."),
        arg(f"{P}-rulesets", "Forwarding rulesets", RULESETS_Q, formatters=[resource_link(), PROVISIONING],
            labels={"id": "Ruleset", "Resolvers": "Outbound endpoints of"},
            no_data="No forwarding rulesets in the selected subscriptions."),
        text(f"{P}-rules-note", "A forwarding rule sends every name under its domain to the target servers instead of "
             "Azure DNS, so a rule for `windows.net.` or `.` stops the private zones being used for networks "
             "linked to the ruleset. Pick a ruleset to read its rules and links from Azure Resource Manager.", "info"),
        params(f"{P}-ruleset-params", [picker("Ruleset", "Ruleset", RULESET_PICK_Q)]),
        when_set(arm(f"{P}-rules", "Forwarding rules", "{Ruleset}/forwardingRules", "2022-07-01", rule_cols,
                     width=60, no_data="The ruleset has no rules."), "Ruleset"),
        when_set(arm(f"{P}-ruleset-links", "Networks linked to the ruleset", "{Ruleset}/virtualNetworkLinks",
                     "2022-07-01", ruleset_link_cols, width=40, no_data="The ruleset is not linked to any network."),
                 "Ruleset"),
        text(f"{P}-logs-h", "### What the DNS servers answered"),
        text(f"{P}-ws-hint", "Select a **Log Analytics workspace** to see the lookups your DNS servers logged.", "info",
             visible_when=WORKSPACE_UNSET),
        text(f"{P}-logs-note", LOGS_NOTE, "info", visible_when=WORKSPACE_SET),
        la(f"{P}-log-summary", "Lookups by server, name and answer", SUMMARY_LOG_Q, formatters=[ANSWERED],
           labels={"QueryType": "Type", "LastSeen": "Last seen"},
           no_data="No matching lookups. Widen the time range, clear Client IP, or check the DNS logs reach this workspace."),
        la(f"{P}-log-timeline", "Lookups over time by answer", TIMELINE_LOG_Q, vis="timechart"),
        la(f"{P}-log-events", "Lookups (latest 500)", EVENTS_LOG_Q, formatters=[ANSWERED],
           labels={"TimeGenerated": "Time", "ClientIp": "Client", "QueryType": "Type"}, no_data="No matching lookups."),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
