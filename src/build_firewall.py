"""Generates the Azure Firewall workbook, with a page for diagnosing SNAT port exhaustion.

Run:  python src/build_firewall.py
Out:  workbook/firewall.workbook.json

Every Azure Firewall in the estate: how each is built (tier, hub, zones, public IPs, NAT gateway, policy), how healthy
and busy it is, and above all why it runs short of SNAT ports and who is taking them. Azure Firewall has 2,496 SNAT
ports per public IP per instance, reused only across different destination IPs and ports, so exhaustion is usually
many connections to one destination; the SNAT tab sets the firewall's capacity against the connection rate per
destination and per source from the firewall logs, with a busiest-minute drill-down and the fixes in order. Also the
policies, denied traffic, threat intelligence and IDPS hits, and DNS proxy failures. From Resource Graph, Azure Monitor
metrics and Log Analytics (the resource-specific AZFW* tables). Blocked connections have their own troubleshooter,
firewall-troubleshoot. Built from the helpers in build_workbook.py so the workbooks look alike.
"""

import pathlib

from build_workbook import (AVG, DAY_MS, MAX, ONE_TILE, PROVISIONING, SUM, WORKSPACE_SET, WORKSPACE_UNSET, arg,
                            big_number_tiles, export_row, gid, group, high_is_good, la, low_is_good, m, metric_grid,
                            metrics, notebook, params, resource_link, resource_param, status_fmt, subscription_param,
                            text, time_param, when_set, workspace_param, write_workbook)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "firewall.workbook.json"

P = "afw"
NS = "microsoft.network/azurefirewalls"

TABS = [
    ("overview", "Overview"),
    ("snat", "SNAT ports"),
    ("health", "Health & capacity"),
    ("policy", "Policy"),
    ("traffic", "Traffic & threats"),
]

TILES = big_number_tiles("Signal", "State", "Value", "Detail")

FIREWALLS_Q = "resources\n| where type =~ 'microsoft.network/azurefirewalls'"

# ---------------------------------------------------------------------------
# Firewalls and how they reach the internet (Resource Graph)
# ---------------------------------------------------------------------------

# Azure Firewall gives 2,496 SNAT ports per public IP per instance; a NAT gateway on AzureFirewallSubnet gives 64,512
# per public IP (up to 16) and takes over all outbound traffic. A firewall in a Virtual WAN secured hub cannot use a
# NAT gateway. The private ranges decide what is SNATed at all: 255.255.255.255/32 means everything, private
# destinations included.
FIREWALLS = r"""
resources
| where type =~ 'microsoft.network/azurefirewalls'
| where id in~ ({Firewalls})
| extend InHub = isnotempty(tostring(properties.virtualHub.id))
| project id, Tier = tostring(properties.sku.tier), InHub, Zones = strcat_array(zones, ','),
    FirewallIPs = toint(iff(InHub, toint(properties.hubIPAddresses.publicIPs['count']), array_length(properties.ipConfigurations))),
    PrivateIP = coalesce(tostring(properties.hubIPAddresses.privateIPAddress),
        tostring(properties.ipConfigurations[0].properties.privateIPAddress)),
    subnetId = tolower(tostring(properties.ipConfigurations[0].properties.subnet.id)),
    policyId = tolower(tostring(properties.firewallPolicy.id)),
    Hub = iff(InHub, tostring(split(tostring(properties.virtualHub.id), '/')[8]), 'Hub VNet'),
    ClassicRanges = tostring(properties.additionalProperties['Network.SNAT.PrivateRanges']),
    Provisioning = tostring(properties.provisioningState), ResourceGroup = resourceGroup, Location = location
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/virtualnetworks'
    | mv-expand s = properties.subnets limit 400
    | where tostring(s.name) =~ 'AzureFirewallSubnet'
    | project subnetId = tolower(tostring(s.id)), natId = tolower(tostring(s.properties.natGateway.id))
  ) on subnetId
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/natgateways'
    | project natId = tolower(id), NatIPs = coalesce(array_length(properties.publicIpAddresses), 0),
        NatPrefixes = coalesce(array_length(properties.publicIpPrefixes), 0)
  ) on natId
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/firewallpolicies'
    | project policyId = tolower(id), Policy = name, PolicyRanges = strcat_array(properties.snat.privateRanges, ', ')
  ) on policyId
| extend NatGateway = isnotempty(natId), Ranges = coalesce(PolicyRanges, ClassicRanges)
| extend SnatAll = Ranges has '255.255.255.255/32'
| extend OutboundVia = iff(NatGateway, 'NAT gateway', 'Firewall public IPs'),
    NatIPs = iff(NatGateway, NatIPs, int(null)), NatPrefixes = iff(NatGateway, NatPrefixes, int(null)),
    PortsPerInstance = iff(NatGateway, int(null), FirewallIPs * 2496),
    NatGatewayPorts = iff(NatGateway, NatIPs * 64512, int(null)),
    PrivateRanges = iff(isempty(Ranges), 'IANA private ranges (default)', Ranges),
    Advice = case(
        SnatAll, 'Private ranges are 255.255.255.255/32, so traffic to private addresses is SNATed too: SNAT only traffic leaving for the internet',
        NatGateway and NatIPs + NatPrefixes < 2, 'Add public IPs or a prefix to the NAT gateway (64,512 ports each, up to 16 addresses)',
        NatGateway, 'Outbound already uses a NAT gateway: find the destination taking the ports in the logs below',
        InHub, 'Add public IPs to the firewall (2,496 ports each per instance, up to 250): a secured hub cannot use a NAT gateway',
        'Associate a NAT gateway with AzureFirewallSubnet: 64,512 ports per public IP, up to 16 addresses')
"""

INVENTORY_Q = FIREWALLS + """| project id, Tier, Hub, Policy, Zones = iff(isempty(Zones), 'No zones', Zones), FirewallIPs, OutboundVia,
    PrivateIP, Provisioning, ResourceGroup, Location
| order by id asc
"""

SNAT_CONFIG_Q = FIREWALLS + """| project id, Hub, OutboundVia, FirewallIPs, NatIPs, NatPrefixes, PortsPerInstance, NatGatewayPorts,
    PrivateRanges, Advice
| order by OutboundVia desc, FirewallIPs asc
"""

TILES_Q = FIREWALLS + """| summarize Firewalls = count(), NoNat = countif(not(NatGateway) and not(InHub)), OneIp = countif(not(NatGateway) and FirewallIPs < 2),
    SnatEverything = countif(SnatAll), NoZones = countif(isempty(Zones)), Failed = countif(Provisioning !~ 'Succeeded')
| extend rows = pack_array(
    pack('Signal', 'Firewalls', 'Value', Firewalls, 'Detail', 'selected', 'State', 'Available'),
    pack('Signal', 'Hub VNet firewalls with no NAT gateway', 'Value', NoNat, 'Detail', '2,496 SNAT ports per IP per instance',
        'State', iff(NoNat > 0, 'Degraded', 'Available')),
    pack('Signal', 'Outbound on one public IP', 'Value', OneIp, 'Detail', 'and no NAT gateway',
        'State', iff(OneIp > 0, 'Degraded', 'Available')),
    pack('Signal', 'SNAT private traffic too', 'Value', SnatEverything, 'Detail', 'private ranges 255.255.255.255/32',
        'State', iff(SnatEverything > 0, 'Degraded', 'Available')),
    pack('Signal', 'Not zone-redundant', 'Value', NoZones, 'Detail', 'no availability zones',
        'State', iff(NoZones > 0, 'Degraded', 'Available')),
    pack('Signal', 'Not provisioned', 'Value', Failed, 'Detail', 'provisioning state not Succeeded',
        'State', iff(Failed > 0, 'Unavailable', 'Available')))
| mv-expand r = rows
| project Signal = tostring(r.Signal), Value = toint(r.Value), Detail = tostring(r.Detail), State = tostring(r.State)
"""

# IDPS and TLS inspection exist only on Premium policies, so other tiers show n/a rather than Off.
POLICIES_Q = r"""
resources
| where type =~ 'microsoft.network/firewallpolicies'
| extend Tier = tostring(properties.sku.tier)
| project id = tolower(id), Tier,
    ThreatIntel = tostring(properties.threatIntelMode),
    Idps = iff(Tier =~ 'Premium', coalesce(tostring(properties.intrusionDetection.mode), 'Off'), 'n/a'),
    TlsInspection = case(Tier !~ 'Premium', 'n/a',
        isnotempty(tostring(properties.transportSecurity.certificateAuthority.keyVaultSecretId)), 'Yes', 'No'),
    DnsProxy = coalesce(tostring(properties.dnsSettings.enableProxy), 'false'),
    SnatPrivateRanges = strcat_array(properties.snat.privateRanges, ', '),
    Firewalls = coalesce(array_length(properties.firewalls), 0),
    ParentPolicy = tostring(split(tostring(properties.basePolicy.id), '/')[8]),
    RuleCollectionGroups = coalesce(array_length(properties.ruleCollectionGroups), 0),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/firewallpolicies/rulecollectiongroups'
    | mv-expand rc = properties.ruleCollections limit 400
    | summarize RuleCollections = count(), Rules = sum(array_length(rc.rules))
        by id = tostring(split(tolower(id), '/rulecollectiongroups/')[0])
  ) on id
| project id, Tier, ThreatIntel, Idps, TlsInspection, DnsProxy,
    SnatPrivateRanges = iff(isempty(SnatPrivateRanges), 'IANA private ranges (default)', SnatPrivateRanges), Firewalls,
    ParentPolicy, RuleCollectionGroups, RuleCollections = coalesce(RuleCollections, 0), Rules = coalesce(Rules, 0),
    Provisioning, ResourceGroup
"""

# ---------------------------------------------------------------------------
# Firewall logs (Log Analytics, resource-specific AZFW* tables)
# ---------------------------------------------------------------------------

ON_FIREWALLS = "| where _ResourceId in~ ({Firewalls})"

# Allowed outbound connections that take a SNAT port: network rule flows to public addresses and application rule
# requests. Each row is a new connection, so these show the rate ports are taken, not how many are held.
FLOWS = f"""let Flows = union isfuzzy=true
    (datatable(TimeGenerated: datetime, _ResourceId: string, SourceIp: string, Destination: string, Protocol: string, Rule: string)[]),
    (AZFWNetworkRule
    | where TimeGenerated {{TimeRange}}
    | where Action !~ 'Deny' and isnotempty(DestinationIp) and not(ipv4_is_private(DestinationIp))
    | project TimeGenerated, _ResourceId, SourceIp, Destination = strcat(DestinationIp, ':', DestinationPort), Protocol,
        Rule = 'Network'),
    (AZFWApplicationRule
    | where TimeGenerated {{TimeRange}}
    | where Action !~ 'Deny'
    | project TimeGenerated, _ResourceId, SourceIp, Destination = strcat(Fqdn, ':', DestinationPort), Protocol,
        Rule = 'Application')
{ON_FIREWALLS};
"""

RATE_Q = FLOWS + """Flows
| summarize Connections = count() by bin(TimeGenerated, {TimeRange:grain}), Protocol
"""

DEST_Q = FLOWS + """Flows
| summarize PerMinute = count(), Sources = dcount(SourceIp) by Destination, Protocol, Minute = bin(TimeGenerated, 1m)
| summarize Connections = sum(PerMinute), PeakPerMinute = max(PerMinute), MostSources = max(Sources) by Destination, Protocol
| top 50 by PeakPerMinute desc
"""

SOURCE_Q = FLOWS + """Flows
| summarize PerMinute = count(), Destinations = dcount(Destination) by SourceIp, Minute = bin(TimeGenerated, 1m)
| summarize Connections = sum(PerMinute), PeakPerMinute = max(PerMinute), MostDestinations = max(Destinations) by SourceIp
| top 50 by PeakPerMinute desc
"""

BUSIEST_Q = FLOWS + """Flows
| summarize Connections = count(), Sources = dcount(SourceIp), Destinations = dcount(Destination)
    by Minute = bin(TimeGenerated, 1m)
| top 20 by Connections desc
"""

MINUTE_Q = FLOWS + """Flows
| where bin(TimeGenerated, 1m) == todatetime('{SnatMinute}')
| summarize Connections = count() by SourceIp, Destination, Protocol, Rule
| top 100 by Connections desc
"""

DENIED_Q = f"""union isfuzzy=true
    (datatable(TimeGenerated: datetime, _ResourceId: string, Rule: string, SourceIp: string, Destination: string, Protocol: string)[]),
    (AZFWNetworkRule | where TimeGenerated {{TimeRange}} | where Action == 'Deny'
        | project TimeGenerated, _ResourceId, Rule = 'Network', SourceIp, Destination = strcat(DestinationIp, ':', DestinationPort), Protocol),
    (AZFWApplicationRule | where TimeGenerated {{TimeRange}} | where Action == 'Deny'
        | project TimeGenerated, _ResourceId, Rule = 'Application', SourceIp, Destination = strcat(Fqdn, ':', DestinationPort), Protocol)
{ON_FIREWALLS}
| summarize Hits = count(), LastSeen = max(TimeGenerated) by Rule, SourceIp, Destination, Protocol
| top 50 by Hits desc
"""

THREATS_Q = f"""union isfuzzy=true
    (datatable(TimeGenerated: datetime, _ResourceId: string, Source: string, SourceIp: string, Destination: string, Action: string, Detail: string)[]),
    (AZFWThreatIntel | where TimeGenerated {{TimeRange}}
        | project TimeGenerated, _ResourceId, Source = 'Threat intel', SourceIp, Destination = strcat(DestinationIp, ':', DestinationPort), Action, Detail = ThreatDescription),
    (AZFWIdpsSignature | where TimeGenerated {{TimeRange}}
        | project TimeGenerated, _ResourceId, Source = 'IDPS', SourceIp, Destination = strcat(DestinationIp, ':', DestinationPort), Action, Detail = Description)
{ON_FIREWALLS}
| summarize Hits = count(), LastSeen = max(TimeGenerated) by Source, Action, Detail, SourceIp, Destination
| top 50 by Hits desc
"""

DNS_CODES_Q = f"""union isfuzzy=true
    (datatable(TimeGenerated: datetime, _ResourceId: string, SourceIp: string, QueryName: string, QueryType: string, ResponseCode: string)[]),
    (AZFWDnsQuery | where TimeGenerated {{TimeRange}})
{ON_FIREWALLS}
| summarize Queries = count() by bin(TimeGenerated, {{TimeRange:grain}}), ResponseCode
"""

DNS_FAILED_Q = f"""union isfuzzy=true
    (datatable(TimeGenerated: datetime, _ResourceId: string, SourceIp: string, QueryName: string, QueryType: string, ResponseCode: string)[]),
    (AZFWDnsQuery | where TimeGenerated {{TimeRange}})
{ON_FIREWALLS}
| where ResponseCode !~ 'NOERROR'
| summarize Queries = count(), Sources = dcount(SourceIp), LastSeen = max(TimeGenerated) by QueryName, QueryType, ResponseCode
| top 50 by Queries desc
"""

# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

LOGS_HINT = ("Select a **Log Analytics workspace** at the top for what the firewall logs show (needs the "
             "resource-specific firewall logs, such as `AZFWNetworkRule` and `AZFWApplicationRule`).")

SNAT_INTRO = """\
### SNAT ports
Every outbound connection the firewall translates to a public IP takes a **SNAT port**. Azure Firewall has 2,496
ports per public IP per instance, and a port can be reused only for a *different* destination IP and port. So
ports usually run out because many connections go to **one destination** (a storage or API endpoint, an external DNS
server) faster than ports are freed, rather than because of total traffic. When they run out, new connections fail
while existing ones carry on. Work down the page: is the firewall built with enough ports, when did use peak, and
which destinations and sources were taking them at the time."""

SNAT_LOGS_NOTE = """\
The logs record each **new** connection, so these panels show how fast ports are taken, not how many are held; a
port stays taken for a while after its connection closes. Line the busiest minutes up with the SNAT chart above.
Application rule rows name the FQDN rather than the address it resolved to. To find what a source address is, use
the **Routing** workbook."""

SNAT_FIX = """\
**What to do, in order of effect**
1. **Hub VNet firewall: associate a NAT gateway with `AzureFirewallSubnet`.** Outbound then uses the NAT gateway's
   64,512 ports per public IP (up to 16 addresses, or a prefix) instead of 2,496 per IP per instance. A firewall in a
   Virtual WAN secured hub cannot use a NAT gateway: add public IPs to it instead (up to 250).
2. **Stop SNATing what does not need it.** With private ranges set to `255.255.255.255/32`, traffic to private
   addresses takes ports too. Reach Azure PaaS services through private endpoints rather than their public addresses.
3. **Fix the heaviest destination.** Where one destination takes most connections, the client is usually opening a
   new connection per request: reuse connections (HTTP keep-alive, connection pooling, one shared HTTP client). For
   DNS, use the firewall's DNS proxy or Azure DNS rather than an external resolver.
4. **Scale out ahead of known peaks.** Each extra instance brings its own ports, but scaling out takes minutes, so a
   sudden burst can exhaust ports first. If *Observed capacity* stays flat while SNAT use climbs, the burst outran
   scale-out."""

# ---------------------------------------------------------------------------
# Parameters and tabs
# ---------------------------------------------------------------------------


def global_params():
    return params(f"{P}-params", [
        subscription_param(P),
        {**resource_param("Firewalls", "Firewalls", FIREWALLS_Q), "id": gid(f"{P}-param-Firewalls")},
        workspace_param(P, "The workspace that receives the firewall logs (resource-specific AZFW* tables)."),
        time_param(P, DAY_MS, [h * 3600000 for h in (1, 4, 12)] + [d * DAY_MS for d in (1, 3, 7, 14, 30)],
                   "For the metrics and logs."),
        {"id": gid(f"{P}-param-selectedTab"), "version": "KqlParameterItem/1.0", "name": "selectedTab", "type": 1,
         "value": "overview", "isHiddenWhenLocked": True},
    ])


def tabs():
    return {"type": 11, "content": {"version": "LinkItem/1.0", "style": "tabs", "links": [
        {"id": gid(f"{P}-tab-" + key), "cellValue": "selectedTab", "linkTarget": "parameter",
         "linkLabel": label, "subTarget": key, "style": "link"} for key, label in TABS
    ]}, "name": f"{P}-tabs"}


OUTBOUND = status_fmt("OutboundVia", good=["NAT gateway"], neutral=["Firewall public IPs"])


def overview_tab():
    return group(f"{P}-tab-overview", [
        arg(f"{P}-tiles", "", TILES_Q, vis="tiles", tiles=TILES),
        metric_grid(f"{P}-kpis", "Key metrics over the time range", NS, "Firewalls", [
            ("FirewallHealth", AVG, "Health %", ("high", 99, 90)),
            ("SNATPortUtilization", MAX, "Max SNAT %", ("low", 70, 90)),
            ("ObservedCapacity", MAX, "Observed capacity units (max)", None),
            ("Throughput", AVG, "Avg throughput", None),
            ("FirewallLatencyPng", AVG, "Latency probe (ms)", ("low", 10, 20)),
        ]),
        arg(f"{P}-inventory", "Firewalls", INVENTORY_Q, formatters=[resource_link(), PROVISIONING, OUTBOUND,
                                                                    status_fmt("Zones", warn=["No zones"])],
            labels={"id": "Firewall", "FirewallIPs": "Public IPs", "OutboundVia": "Outbound through",
                    "PrivateIP": "Private IP", "ResourceGroup": "Resource group"},
            no_data="No Azure Firewalls found."),
        text(f"{P}-overview-note", "Running short of SNAT ports? Start on the **SNAT ports** tab. For a connection "
             "the firewall blocks, use the **Firewalls: blocked connections** workbook.", "info"),
    ], tab="overview")


def snat_tab():
    return group(f"{P}-tab-snat", [
        text(f"{P}-snat-intro", SNAT_INTRO),
        arg(f"{P}-snat-config", "SNAT capacity and settings by firewall", SNAT_CONFIG_Q,
            formatters=[resource_link(), OUTBOUND, high_is_good("FirewallIPs", 2, 2)],
            labels={"id": "Firewall", "OutboundVia": "Outbound through", "FirewallIPs": "Firewall public IPs",
                    "NatIPs": "NAT gateway IPs", "NatPrefixes": "NAT gateway prefixes",
                    "PortsPerInstance": "SNAT ports per instance", "NatGatewayPorts": "NAT gateway SNAT ports",
                    "PrivateRanges": "Not SNATed (private ranges)", "Advice": "What to do"},
            no_data="No Azure Firewalls selected."),
        metrics(f"{P}-snat-util", "SNAT port use % by protocol (max)", NS, "Firewalls",
                [m(NS, "SNATPortUtilization", MAX, split="Protocol")], width=50),
        metrics(f"{P}-snat-capacity", "Observed capacity units (max): did scale-out keep up?", NS, "Firewalls",
                [m(NS, "ObservedCapacity", MAX)], width=50),
        text(f"{P}-snat-hint", LOGS_HINT, "info", visible_when=WORKSPACE_UNSET),
        la(f"{P}-snat-rate", "New outbound connections taking SNAT ports, by protocol", RATE_Q, vis="timechart",
           no_data="No allowed outbound connections logged (or the structured firewall logs are not enabled)."),
        la(f"{P}-snat-destinations", "Destinations taking the most connections (ports run out per destination)",
           DEST_Q, width=50, formatters=[low_is_good("PeakPerMinute", 500, 2000)],
           labels={"PeakPerMinute": "Peak per minute", "MostSources": "Most sources in a minute"},
           no_data="No outbound connections to public destinations."),
        la(f"{P}-snat-sources", "Sources opening the most outbound connections", SOURCE_Q, width=50,
           formatters=[low_is_good("PeakPerMinute", 500, 2000)],
           labels={"SourceIp": "Source", "PeakPerMinute": "Peak per minute",
                   "MostDestinations": "Most destinations in a minute"},
           no_data="No outbound connections to public destinations."),
        export_row(la(f"{P}-snat-busiest", "Busiest minutes (select one to see who was connecting)", BUSIEST_Q,
                      width=40, no_data="No outbound connections to public destinations."), "Minute", "SnatMinute"),
        when_set(la(f"{P}-snat-minute", "Connections in the selected minute", MINUTE_Q, width=60,
                    labels={"SourceIp": "Source"}), "SnatMinute"),
        text(f"{P}-snat-logs-note", SNAT_LOGS_NOTE, "info", visible_when=WORKSPACE_SET),
        text(f"{P}-snat-fix", SNAT_FIX),
    ], tab="snat")


def health_tab():
    return group(f"{P}-tab-health", [
        metrics(f"{P}-health", "Health state %", NS, "Firewalls", [m(NS, "FirewallHealth", AVG)], width=50),
        metrics(f"{P}-latency", "Latency probe (ms)", NS, "Firewalls", [m(NS, "FirewallLatencyPng", AVG)], width=50),
        metrics(f"{P}-throughput", "Throughput", NS, "Firewalls", [m(NS, "Throughput", AVG)], width=50),
        metrics(f"{P}-capacity", "Observed capacity units (max)", NS, "Firewalls", [m(NS, "ObservedCapacity", MAX)],
                width=50),
        metrics(f"{P}-data", "Data processed", NS, "Firewalls", [m(NS, "DataProcessed", SUM)], width=50),
        metrics(f"{P}-rulehits", "Rule hits", NS, "Firewalls",
                [m(NS, "NetworkRuleHit", SUM), m(NS, "ApplicationRuleHit", SUM)], width=50),
        text(f"{P}-health-note", "Health below 100% with SNAT use near 100% is SNAT exhaustion: health includes "
             "SNAT port use. Low health with normal SNAT use and no scaling is worth raising with Microsoft support, "
             "with the firewall and the times.", "info"),
    ], tab="health")


def policy_tab():
    return group(f"{P}-tab-policy", [
        arg(f"{P}-policies", "Firewall policies", POLICIES_Q, formatters=[
            resource_link(), PROVISIONING,
            status_fmt("ThreatIntel", good=["Deny"], warn=["Alert"], bad=["Off"]),
            status_fmt("Idps", good=["Deny"], warn=["Alert"], bad=["Off"], neutral=["n/a"]),
            status_fmt("TlsInspection", good=["Yes"], neutral=["No", "n/a"]),
            status_fmt("DnsProxy", good=["true"], neutral=["false"]),
            high_is_good("Firewalls", 1, 0),
        ], labels={"id": "Policy", "ThreatIntel": "Threat intel", "Idps": "IDPS", "TlsInspection": "TLS inspection",
                   "DnsProxy": "DNS proxy", "SnatPrivateRanges": "Not SNATed (private ranges)",
                   "ParentPolicy": "Parent policy", "RuleCollectionGroups": "Rule collection groups",
                   "RuleCollections": "Rule collections", "ResourceGroup": "Resource group"},
            no_data="No firewall policies found."),
        text(f"{P}-policy-note", "A policy attached to no firewall is flagged. Rule counts are totals across the "
             "policy's own rule collection groups; rules inherited from a parent policy are counted on the parent. "
             "DNS proxy must be on for FQDNs in network rules to resolve the same way the clients do.", "info"),
    ], tab="policy")


def traffic_tab():
    return group(f"{P}-tab-traffic", [
        text(f"{P}-traffic-hint", LOGS_HINT, "info", visible_when=WORKSPACE_UNSET),
        la(f"{P}-denied", "Top denied flows", DENIED_Q, width=50,
           no_data="No denied flows (or the structured firewall logs are not enabled)."),
        la(f"{P}-threats", "Threat intel and IDPS detections", THREATS_Q, width=50,
           no_data="No threat intel or IDPS hits."),
        la(f"{P}-dns-codes", "DNS proxy queries by response code", DNS_CODES_Q, vis="timechart", width=50,
           no_data="No DNS proxy queries (DNS proxy off, or its logs are not enabled)."),
        la(f"{P}-dns-failed", "Top failing DNS proxy queries", DNS_FAILED_Q, width=50,
           no_data="No failing DNS queries."),
    ], tab="traffic")


def workbook():
    return notebook([
        text(f"{P}-header", "# Azure Firewall\n"
             "Every Azure Firewall: how it is built and reaches the internet, how healthy and busy it is, why it runs "
             "short of SNAT ports and who is taking them, its policies, and the traffic it denies or flags."),
        global_params(),
        tabs(),
        overview_tab(),
        snat_tab(),
        health_tab(),
        policy_tab(),
        traffic_tab(),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
