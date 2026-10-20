"""Generates the blocked-connection troubleshooting workbook for Azure Firewall, Palo Alto and Check Point.

Run:  python src/build_firewall_troubleshoot.py
Out:  workbook/firewall-troubleshoot.workbook.json

Answers "is a firewall blocking this connection, and which rule did it?" from the resource-specific Azure
Firewall logs (AZFW* tables) and the Palo Alto and Check Point CEF logs in CommonSecurityLog. Source,
destination and port are all optional: fill in whatever is known and leave the rest empty. Built from the
helpers in build_workbook.py so the two workbooks look alike.
"""

import json
import pathlib

from build_workbook import (DAY_MS, ICON_ONLY, WORKSPACE_SET, WORKSPACE_UNSET, _icons, _t, arg, gid, group, la,
                            low_is_good, params, resource_link, resource_param, status_fmt, text)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "firewall-troubleshoot.workbook.json"

HOUR_MS = 3600000

# ---------------------------------------------------------------------------
# Shared query
# ---------------------------------------------------------------------------

PLATFORMS = ["Azure Firewall", "Palo Alto", "Check Point", "NSG"]

# CommonSecurityLog rows from the two NVA vendors. An exact list rather than a word search, because the table
# is large (tens of millions of rows a day) and `in~` on the vendor column is far cheaper.
NVA_VENDORS = ("DeviceVendor in~ ('Palo Alto Networks', 'Check Point', 'CheckPoint', "
               "'Check Point Software Technologies')")
# Names the platform of a row that NVA_VENDORS kept.
NVA_PLATFORM = "iff(DeviceVendor startswith 'Palo', 'Palo Alto', 'Check Point')"


def cs_field(has, has_not=()):
    """The CEF custom string whose label contains the word `has` (and none of `has_not`).

    Vendors put the rule name and policy layer in different DeviceCustomString slots but label them: Palo Alto's
    rule is cs1 "Rule", Check Point's is labelled "Rule Name". Matching the label finds it in whichever slot.
    """
    tests = []
    for i in range(1, 7):
        label = f"DeviceCustomString{i}Label"
        cond = " and ".join([f"{label} has '{has}'"] + [f"{label} !has '{n}'" for n in has_not])
        tests.append(f"{cond}, DeviceCustomString{i}")
    return "case(" + ", ".join(tests) + ", '')"


NOT_AN_ID = ("id", "uid", "uuid")

# Parses the filter boxes. Each takes a comma, space or semicolon separated list, and an empty one matches
# everything. Destinations drop a leading "*." so a wildcard FQDN works. Ports take single ports and ranges
# ("1433, 11000-11999"), expanded into a set of port numbers.
FILTERS = r"""
let Clean = (s: string) { trim(@',+', replace_regex(s, @'[\s;,]+', ',')) };
let SrcText = Clean(@'{SourceIp}');
let SrcList = split(SrcText, ',');
let DstText = Clean(replace_string(replace_string(@'{Destination}', '*.', ''), '*', ''));
let DstList = split(DstText, ',');
let PortText = Clean(replace_regex(@'{Port}', @'\s*-\s*', '-'));
let PortSet = toscalar(print p = split(PortText, ',')
    | mv-expand p to typeof(string)
    | extend lo = toint(extract(@'^(\d+)', 1, p)), hi = toint(extract(@'^\d+-(\d+)$', 1, p))
    | where isnotnull(lo)
    | mv-expand Port = range(lo, coalesce(hi, lo), 1) to typeof(int)
    | summarize make_set(Port, 65536));
let Platforms = dynamic([{Platform}]);
let Devices = dynamic([{Device}]);
"""

# Session states that say the return traffic took another path: Check Point's "First packet isn't SYN" drop,
# and the equivalent wording other versions use.
NOT_SYN = "has_any (\"isn't SYN\", 'not SYN', 'non-SYN', 'out of state', 'out-of-state')"

def leg_filters(platform, device, src, dst_ip, dst_names, port):
    """The filter boxes as `where` clauses on one log source's own columns.

    Each source is filtered before anything else is worked out for its rows, so the expensive columns (rule name,
    host name, session state) are only computed for rows that survive. That matters for CommonSecurityLog, where an
    unfiltered hour can be millions of rows.
    """
    dst = " or ".join([f"ipv4_is_in_any_range({dst_ip}, DstList) == true"] + [f"{n} has_any (DstList)" for n in dst_names])
    return f"""
    | where array_length(Platforms) == 0 or {platform} in (Platforms)
    | where array_length(Devices) == 0 or {device}
    | where isempty(SrcText) or ipv4_is_in_any_range({src}, SrcList) == true
    | where isempty(DstText) or {dst}
    | where isempty(PortText) or {port} in (PortSet)"""


# Every panel starts from this. It folds the Azure Firewall log tables, the NVA CEF logs and NSG flow logs into one
# shape, each filtered first. Sources and destinations accept IPs or CIDR ranges; destinations also accept FQDNs,
# matched as whole words against the FQDN, host name or URL ("contoso.com" matches "www.contoso.com"). Azure
# Firewall application rule logs carry no destination IP, so an IP filter finds them only when the client asked
# for the IP rather than a name.
BASE = FILTERS + r"""let Flows = union isfuzzy=true
    (union isfuzzy=true
        (AZFWNetworkRule | where TimeGenerated {TimeRange}
            | extend Source = 'Network rule', Reason = column_ifexists('ActionReason', '')),
        (AZFWApplicationRule | where TimeGenerated {TimeRange}
            | extend Source = 'Application rule',
                Reason = strcat_delim(' · ', column_ifexists('ActionReason', ''), column_ifexists('WebCategory', ''))),
        (AZFWNatRule | where TimeGenerated {TimeRange}
            | extend Source = 'DNAT rule', Action = 'DNAT',
                Reason = strcat('Translated to ', TranslatedIp, ':', TranslatedPort)),
        (AZFWThreatIntel | where TimeGenerated {TimeRange}
            | extend Source = 'Threat intel', Reason = ThreatDescription),
        (AZFWIdpsSignature | where TimeGenerated {TimeRange}
            | extend Source = 'IDPS', Reason = strcat('Signature ', SignatureId, ' (', Category, ', severity ', Severity, '): ', Description))
    // A table missing from the workspace drops its columns from the union; put them back empty.
    | extend Fqdn = column_ifexists('Fqdn', ''), TargetUrl = column_ifexists('TargetUrl', ''),
        DestinationIp = column_ifexists('DestinationIp', ''),
        Policy = column_ifexists('Policy', ''), RuleCollectionGroup = column_ifexists('RuleCollectionGroup', ''),
        RuleCollection = column_ifexists('RuleCollection', ''), Rule = column_ifexists('Rule', '')
    AZFW_FILTERS
    | project TimeGenerated, Platform = 'Azure Firewall', Device = tostring(split(_ResourceId, '/')[-1]),
        DeviceId = tolower(_ResourceId), Source, Action,
        SourceIp, SourcePort, DestinationIp, Fqdn, DestinationPort, Protocol, TargetUrl,
        Policy, RuleCollectionGroup, RuleCollection, Rule, Reason, ReplyBytes = long(null), NotSyn = false),
    // Palo Alto and Check Point, sent as CEF. The rule name and policy layer come from labelled custom strings;
    // ReceivedBytes is what came back from the destination.
    (CommonSecurityLog | where TimeGenerated {TimeRange}
    | where NVA_VENDORS
    | extend Platform = NVA_PLATFORM
    NVA_FILTERS
    // Only Check Point drops can be out-of-state drops, so the text search runs on those alone.
    | extend NotSyn = Platform == 'Check Point' and DeviceAction in~ ('Drop', 'Reject') and (Reason NOT_SYN or Message NOT_SYN)
    | project TimeGenerated, Platform, Device = coalesce(DeviceName, Computer), DeviceId = '',
        Source = iff(Platform == 'Palo Alto', strcat('Palo Alto ', tolower(coalesce(Activity, 'log'))), strcat('Check Point ', DeviceProduct)),
        Action = DeviceAction, SourceIp = SourceIP, SourcePort, DestinationIp = DestinationIP,
        Fqdn = iff(isnotempty(DestinationHostName), DestinationHostName, extract(@'^(?:[A-Za-z]+://)?([^/:?]+)', 1, RequestURL)),
        DestinationPort, Protocol, TargetUrl = RequestURL,
        Policy = CS_POLICY, RuleCollectionGroup = '', RuleCollection = CS_LAYER, Rule = CS_RULE,
        Reason = strcat_delim(' · ', Reason, DeviceEventClassID), ReplyBytes = ReceivedBytes, NotSyn),
    // NSG decisions from VNet flow logs (Traffic Analytics). Each row is a flow summed over the logging interval.
    (union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (NTANetAnalytics)
    | where TimeGenerated {TimeRange}
    | where column_ifexists('SubType', '') == 'FlowLog'
    | extend AclGroup = tostring(column_ifexists('AclGroup', '')), L4 = tostring(column_ifexists('L4Protocol', '')),
        Direction = tostring(column_ifexists('FlowDirection', ''))
    | project TimeGenerated, Platform = 'NSG', Device = tostring(split(AclGroup, '/')[-1]),
        DeviceId = iff(AclGroup startswith '/subscriptions/', tolower(AclGroup), ''), Source = 'NSG flow log',
        Action = tostring(column_ifexists('FlowStatus', '')), SourceIp = tostring(column_ifexists('SrcIp', '')),
        SourcePort = toint(column_ifexists('SrcPort', int(null))), DestinationIp = tostring(column_ifexists('DestIp', '')),
        Fqdn = '', DestinationPort = toint(column_ifexists('DestPort', int(null))),
        Protocol = case(L4 == 'T', 'TCP', L4 == 'U', 'UDP', L4), TargetUrl = '',
        Policy = tostring(split(AclGroup, '/')[-1]), RuleCollectionGroup = '', RuleCollection = '',
        Rule = tostring(column_ifexists('AclRule', '')), Reason = case(Direction == 'I', 'Inbound', Direction == 'O', 'Outbound', Direction),
        ReplyBytes = tolong(column_ifexists('BytesDestToSrc', long(null))), NotSyn = false
    NSG_FILTERS)
// Azure Firewall: Deny. Palo Alto: deny, drop, reset-*, block-*, sinkhole. Check Point: Drop, Reject, Block, Prevent.
// NSG: Denied.
| extend Blocked = Action in~ ('deny', 'drop', 'drop-icmp', 'drop-all-packets', 'reject', 'reset-client', 'reset-server',
    'reset-both', 'block', 'block-url', 'block-ip', 'block-continue', 'sinkhole', 'prevent', 'blocked', 'denied')
| project TimeGenerated, Platform, Device, DeviceId, Verdict = iff(Blocked, 'Blocked', 'Allowed'), Blocked, Source, Action,
    SourceIp, SourcePort, Destination = coalesce(Fqdn, DestinationIp), DestinationIp, DestinationPort, Protocol, TargetUrl,
    Policy, RuleCollectionGroup, RuleCollection,
    RuleName = case(isnotempty(Rule), Rule,
        Source in ('Threat intel', 'IDPS'), '',
        Platform == 'Azure Firewall' and Blocked, '(no rule matched: default deny)', '(no rule name)'),
    Reason, ReplyBytes, NotSyn,
    // An allowed TCP session that got nothing back: the reply went another way, or the destination never answered.
    NoReply = not(Blocked) and Protocol in~ ('tcp', '6') and ReplyBytes == 0;
let Shown = Flows | where '{Show}' == 'all' or ('{Show}' == 'blocked') == Blocked;
""".replace("AZFW_FILTERS", leg_filters("'Azure Firewall'", "tostring(split(_ResourceId, '/')[-1]) in~ (Devices)",
                                        "SourceIp", "DestinationIp", ["Fqdn"], "DestinationPort").strip()) \
   .replace("NVA_FILTERS", leg_filters("Platform", "DeviceName in~ (Devices) or Computer in~ (Devices)",
                                       "SourceIP", "DestinationIP", ["DestinationHostName", "RequestURL"],
                                       "DestinationPort").strip()) \
   .replace("NSG_FILTERS", leg_filters("'NSG'", "Device in~ (Devices)", "SourceIp", "DestinationIp", [],
                                       "DestinationPort").strip()) \
   .replace("NVA_VENDORS", NVA_VENDORS) \
   .replace("NVA_PLATFORM", NVA_PLATFORM) \
   .replace("NOT_SYN", NOT_SYN) \
   .replace("CS_POLICY", cs_field("policy", NOT_AN_ID)) \
   .replace("CS_LAYER", cs_field("layer")) \
   .replace("CS_RULE", cs_field("rule", NOT_AN_ID))


def fw(name, title, body, **kw):
    """A log panel on the shared filtered events: `Flows` ignores the Show filter, `Shown` applies it."""
    return la(name, title, BASE + body, **kw)


VERDICT = status_fmt("Verdict", good=["Allowed"], bad=["Blocked"])
LAST_ACTION = status_fmt("Action", good=["Allow", "allow", "Accept", "DNAT"], warn=["Alert", "alert", "Detect"],
                         bad=["Deny", "deny", "Drop", "drop", "Reject", "Block", "Prevent",
                              "reset-both", "reset-client", "reset-server"])

# One tile per verdict and log source. The icon shows the verdict; the number is the event count.
VERDICT_TILES = {
    "titleContent": {"columnMatch": "Source", "formatter": 1},
    "subtitleContent": {"columnMatch": "Verdict", "formatter": 1},
    "leftContent": {"columnMatch": "Verdict", "formatter": 18, "formatOptions": _icons([
        _t("==", "Blocked", "4", ICON_ONLY), _t("==", "Allowed", "success", ICON_ONLY),
        _t("Default", None, "Blank", ICON_ONLY)])},
    "rightContent": {"columnMatch": "Events", "formatter": 12, "formatOptions": {"palette": "none"}},
    "secondaryContent": {"columnMatch": "Detail", "formatter": 1},
    "showBorder": True,
}

# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

# Devices that logged in the time range: Azure Firewalls by resource name, NVAs by the name they log under.
DEVICES_Q = r"""
let Platforms = dynamic([{Platform}]);
union isfuzzy=true
    (union isfuzzy=true AZFWNetworkRule, AZFWApplicationRule, AZFWNatRule, AZFWThreatIntel, AZFWIdpsSignature
        | where TimeGenerated {TimeRange}
        | summarize by Device = tostring(split(_ResourceId, '/')[-1]), Platform = 'Azure Firewall'),
    (CommonSecurityLog
        | where TimeGenerated {TimeRange}
        | where NVA_VENDORS
        | summarize by Device = coalesce(DeviceName, Computer), Platform = NVA_PLATFORM),
    (union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (NTANetAnalytics)
        | where TimeGenerated {TimeRange}
        | where column_ifexists('SubType', '') == 'FlowLog'
        | summarize by Device = tostring(split(tostring(column_ifexists('AclGroup', '')), '/')[-1]), Platform = 'NSG')
| where isnotempty(Device)
| where array_length(Platforms) == 0 or Platform in (Platforms)
| order by Platform asc, Device asc
| project value = strcat("@'", replace_string(Device, "'", "''"), "'"), label = strcat(Device, ' (', Platform, ')'),
    selected = false
""".replace("NVA_VENDORS", NVA_VENDORS).replace("NVA_PLATFORM", NVA_PLATFORM)


# Every Azure Firewall in the selected subscriptions, so the logging check lists the ones that send nothing too.
AZFW_IDS_Q = """
resources
| where type =~ 'microsoft.network/azurefirewalls'
| summarize ids = make_list(tolower(id))
| project value = strcat("'", strcat_array(ids, "','"), "'")
"""


def text_param(name, label, description):
    return {"id": gid("fwts-param-" + name), "version": "KqlParameterItem/1.0", "name": name, "label": label,
            "type": 1, "isRequired": False, "value": "", "description": description}


def parameters():
    return params("fwts-params", [
        {
            "id": gid("fwts-param-Subscription"),
            "version": "KqlParameterItem/1.0",
            "name": "Subscription",
            "label": "Subscriptions",
            "type": 6,
            "isRequired": True,
            "multiSelect": True,
            "quote": "'",
            "delimiter": ",",
            "query": "summarize by subscriptionId\n| project value = strcat('/subscriptions/', subscriptionId), label = subscriptionId",
            "crossComponentResources": ["value::all"],
            "typeSettings": {"additionalResourceOptions": ["value::all"], "showDefault": False},
            "defaultValue": "value::all",
            "value": ["value::all"],
            "queryType": 1,
            "resourceType": "microsoft.resourcegraph/resources",
            "description": "Where to look for workspaces to pick from.",
        },
        {
            "id": gid("fwts-param-Workspace"),
            "version": "KqlParameterItem/1.0",
            "name": "Workspace",
            "label": "Log Analytics workspace",
            "type": 5,
            "isRequired": True,
            "multiSelect": True,
            "quote": "'",
            "delimiter": ",",
            "query": "resources\n| where type =~ 'microsoft.operationalinsights/workspaces'\n| project id",
            "crossComponentResources": ["{Subscription}"],
            "typeSettings": {"resourceTypeFilter": {"microsoft.operationalinsights/workspaces": True},
                             "additionalResourceOptions": [], "showDefault": False},
            "queryType": 1,
            "resourceType": "microsoft.resourcegraph/resources",
            "description": "The workspace (or workspaces) the firewalls log to.",
        },
        {
            "id": gid("fwts-param-AzureFirewallIds"),
            "version": "KqlParameterItem/1.0",
            "name": "AzureFirewallIds",
            "type": 1,
            "query": AZFW_IDS_Q.strip(),
            "crossComponentResources": ["{Subscription}"],
            "isHiddenWhenLocked": True,
            "queryType": 1,
            "resourceType": "microsoft.resourcegraph/resources",
        },
        {
            "id": gid("fwts-param-TimeRange"),
            "version": "KqlParameterItem/1.0",
            "name": "TimeRange",
            "label": "Time range",
            "type": 4,
            "isRequired": True,
            "value": {"durationMs": HOUR_MS},
            "typeSettings": {
                "selectableValues": [{"durationMs": ms} for ms in
                                     (900000, 1800000, HOUR_MS, 4 * HOUR_MS, 12 * HOUR_MS, DAY_MS, 3 * DAY_MS, 7 * DAY_MS)],
                "allowCustom": True,
            },
        },
        {
            "id": gid("fwts-param-Platform"),
            "version": "KqlParameterItem/1.0",
            "name": "Platform",
            "label": "Platforms",
            "type": 2,
            "isRequired": False,
            "multiSelect": True,
            "quote": "'",
            "delimiter": ",",
            "jsonData": json.dumps([{"value": p, "label": p} for p in PLATFORMS]),
            "value": [],
            "typeSettings": {"showDefault": False},
            "description": "Leave empty for all. NSG is the network security group decision from VNet flow logs.",
        },
        {
            "id": gid("fwts-param-Device"),
            "version": "KqlParameterItem/1.0",
            "name": "Device",
            "label": "Firewalls",
            "type": 2,
            "isRequired": False,
            "multiSelect": True,
            # Each value is already a quoted verbatim string; see DEVICES_Q.
            "quote": "",
            "delimiter": ",",
            "query": DEVICES_Q.strip(),
            "crossComponentResources": ["{Workspace}"],
            "timeContextFromParameter": "TimeRange",
            "value": [],
            "typeSettings": {"additionalResourceOptions": [], "showDefault": False},
            "queryType": 0,
            "resourceType": "microsoft.operationalinsights/workspaces",
            "description": "Firewalls that logged in the time range. Leave empty for all of them.",
        },
        text_param("SourceIp", "Source IP / CIDR",
                   "Optional. One or more IPs or CIDR ranges, separated by commas, e.g. 10.1.0.4, 10.2.0.0/16."),
        text_param("Destination", "Destination IP / CIDR / FQDN",
                   "Optional. IPs, CIDR ranges or FQDNs, separated by commas. FQDNs match as whole words, so "
                   "contoso.com matches www.contoso.com."),
        text_param("Port", "Destination port",
                   "Optional. Ports and ranges separated by commas, e.g. 443, 1433, 11000-11999."),
        {
            "id": gid("fwts-param-HopMatch"),
            "version": "KqlParameterItem/1.0",
            "name": "HopMatch",
            "label": "Match hops on",
            "type": 2,
            "isRequired": True,
            "jsonData": json.dumps([
                {"value": "source", "label": "Source, destination and port"},
                {"value": "destination", "label": "Destination and port (source is NATed)"},
            ]),
            "value": "source",
            "typeSettings": {"showDefault": False},
            "description": "How *Path through the firewalls* lines up one flow across firewalls. If Azure Firewall "
                           "SNATs traffic before the Palo Alto or Check Point, the source changes between hops: "
                           "match on destination and port only.",
        },
        {
            "id": gid("fwts-param-Show"),
            "version": "KqlParameterItem/1.0",
            "name": "Show",
            "label": "Show",
            "type": 2,
            "isRequired": True,
            "jsonData": json.dumps([
                {"value": "blocked", "label": "Blocked only"},
                {"value": "allowed", "label": "Allowed only"},
                {"value": "all", "label": "Blocked and allowed"},
            ]),
            "value": "blocked",
            "typeSettings": {"showDefault": False},
            "description": "Filters the tiles, timeline, rules, top lists and events. The path, no-reply and verdict "
                           "panels always use both, since they compare allowed and blocked.",
        },
    ])


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------

SUMMARY_Q = """
Shown
| summarize Events = count(), Sources = dcount(SourceIp), Destinations = dcount(Destination), LastSeen = max(TimeGenerated)
    by Verdict, Source
| extend Detail = strcat(Sources, ' sources → ', Destinations, ' destinations · last ', format_datetime(LastSeen, 'yyyy-MM-dd HH:mm'))
| order by Verdict desc, Events desc
"""

TIMELINE_Q = """
Shown
| summarize Events = count() by bin(TimeGenerated, {TimeRange:grain}), Series = strcat(Verdict, ' · ', Source)
"""

# Latest verdict per flow and firewall, with both counts, so a flow that is now allowed after a rule change (or
# the reverse) is obvious, and a flow that crosses two firewalls shows what each one did. Ignores the Show
# filter on purpose.
VERDICTS_Q = """
Flows
| summarize arg_max(TimeGenerated, Action, Source, RuleName, Reason), Blocked = countif(Blocked), Allowed = countif(not(Blocked)),
    FirstSeen = min(TimeGenerated), DeviceId = max(DeviceId) by SourceIp, Destination, DestinationPort, Protocol, Platform, Device
| project LastSeen = TimeGenerated, SourceIp, Destination, DestinationPort, Protocol, Device, DeviceId, Blocked, Allowed,
    Action, Source, RuleName, Reason, FirstSeen
| order by Blocked desc, Allowed desc
| take 250
"""

# One row per flow, one column pair per hop in path order (Azure Firewall, the NVA, then the NSG in front of the
# destination), and the hop where the flow stops. The destination key is the IP where there is one: Azure
# Firewall application rules log only the FQDN, so those flows line up with the other hops only when they log
# the same name. Ignores the Show filter: a path needs the allowed hops as well as the blocked one.
#
# A hop reads Blocked, Allowed, Mixed (some of each), No reply (allowed, but no TCP session got a byte back) or
# Out of state (its only drops were packets that did not start a session: the return traffic took another path).
PATH_Q = """
let BySource = '{HopMatch}' == 'source';
Flows
| extend SourceKey = iff(BySource, SourceIp, '(any source)'), DestinationKey = coalesce(DestinationIp, Destination)
| summarize Blocked = countif(Blocked), Allowed = countif(not(Blocked)), NoReply = countif(NoReply), OutOfState = countif(NotSyn),
    arg_max(TimeGenerated, RuleName), Devices = strcat_array(make_set(Device, 5), ', '), DeviceId = max(DeviceId)
    by SourceKey, DestinationKey, DestinationPort, Platform
| extend Hop = case(
        Blocked > 0 and Blocked == OutOfState, 'Out of state',
        Blocked > 0 and Allowed > 0, 'Mixed',
        Blocked > 0, 'Blocked',
        NoReply > 0 and NoReply == Allowed, 'No reply',
        'Allowed'),
    Rule = strcat(RuleName, ' (', Blocked, ' blocked, ', Allowed, ' allowed)')
| summarize LastSeen = max(TimeGenerated),
    AzureFirewall = take_anyif(Hop, Platform == 'Azure Firewall'), AzureFirewallRule = take_anyif(Rule, Platform == 'Azure Firewall'),
    AzureFirewallId = take_anyif(DeviceId, Platform == 'Azure Firewall'),
    PaloAlto = take_anyif(Hop, Platform == 'Palo Alto'), PaloAltoRule = take_anyif(Rule, Platform == 'Palo Alto'),
    CheckPoint = take_anyif(Hop, Platform == 'Check Point'), CheckPointRule = take_anyif(Rule, Platform == 'Check Point'),
    Nsg = take_anyif(Hop, Platform == 'NSG'), NsgRule = take_anyif(Rule, Platform == 'NSG'), NsgId = take_anyif(DeviceId, Platform == 'NSG'),
    Firewalls = strcat_array(make_set(Devices), ', ')
    by SourceKey, DestinationKey, DestinationPort
| extend AzureFirewall = coalesce(AzureFirewall, 'Not seen'), PaloAlto = coalesce(PaloAlto, 'Not seen'),
    CheckPoint = coalesce(CheckPoint, 'Not seen'), Nsg = coalesce(Nsg, 'Not seen')
| extend StoppedAt = case(
    AzureFirewall == 'Blocked', 'Azure Firewall',
    PaloAlto == 'Blocked', 'Palo Alto',
    CheckPoint == 'Blocked', 'Check Point',
    Nsg == 'Blocked', 'NSG',
    PaloAlto == 'Out of state' or CheckPoint == 'Out of state', 'Asymmetric routing (out-of-state drops)',
    AzureFirewall == 'Mixed', 'Azure Firewall (some attempts)',
    PaloAlto == 'Mixed', 'Palo Alto (some attempts)',
    CheckPoint == 'Mixed', 'Check Point (some attempts)',
    Nsg == 'Mixed', 'NSG (some attempts)',
    PaloAlto == 'No reply' or CheckPoint == 'No reply' or Nsg == 'No reply', 'No reply from the destination',
    AzureFirewall == 'Allowed' and PaloAlto == 'Not seen' and CheckPoint == 'Not seen', 'Passed Azure Firewall, not seen at Palo Alto or Check Point',
    AzureFirewall == 'Not seen' and (PaloAlto != 'Not seen' or CheckPoint != 'Not seen'), 'Not seen at Azure Firewall',
    'Allowed everywhere it was logged')
| extend Rank = case(StoppedAt in ('Azure Firewall', 'Palo Alto', 'Check Point', 'NSG'), 0,
    StoppedAt startswith 'Asymmetric' or StoppedAt startswith 'No reply', 1, StoppedAt has 'some attempts', 2, 3)
| order by Rank asc, LastSeen desc
| take 250
| project SourceKey, DestinationKey, DestinationPort, StoppedAt, AzureFirewall, AzureFirewallRule, AzureFirewallId,
    PaloAlto, PaloAltoRule, CheckPoint, CheckPointRule, Nsg, NsgRule, NsgId, Firewalls, LastSeen
"""

HOP_FORMATTERS = [status_fmt(col, good=["Allowed"], warn=["Mixed", "No reply", "Out of state"], bad=["Blocked"],
                             neutral=["Not seen"])
                  for col in ("AzureFirewall", "PaloAlto", "CheckPoint", "Nsg")]

STOPPED_AT = status_fmt("StoppedAt", good=["Allowed everywhere it was logged"],
                        warn=["Asymmetric routing (out-of-state drops)", "No reply from the destination",
                              "Passed Azure Firewall, not seen at Palo Alto or Check Point", "Not seen at Azure Firewall",
                              "Azure Firewall (some attempts)", "Palo Alto (some attempts)",
                              "Check Point (some attempts)", "NSG (some attempts)"],
                        bad=["Azure Firewall", "Palo Alto", "Check Point", "NSG"])

PATH_NOTE = """\
**Reading the path.** Each row is one flow, with what each hop did in path order: Azure Firewall, Palo Alto or
Check Point, then the NSG (from VNet flow logs). *Stopped at* names the first hop that blocked it.
- **Asymmetric routing:** the Palo Alto or Check Point dropped packets that did not start a session. The request
  went one way and the reply came back another, so this firewall saw only half of the conversation. Check the
  route tables on both sides, including the destination subnet's route back to the source.
- **No reply from the destination:** every hop allowed it, but no TCP session got a byte back. The reply took
  another path, or the destination is not listening. See *Allowed but no reply* below.
- **Passed Azure Firewall, not seen at Palo Alto or Check Point:** the next hop never logged it. Check the route
  from the Azure Firewall subnet to the NVA, or the NVA's logging for that rule. If Azure Firewall SNATs this
  traffic, set *Match hops on* to *Destination and port*.
- **Not seen at Azure Firewall:** the flow reached an NVA without going through Azure Firewall (check routing), or
  the source was translated before it got there.
- **Allowed everywhere it was logged:** look past the network: the host firewall, the service itself, DNS or
  authentication.

*No reply* needs byte counts, which Palo Alto, Check Point and VNet flow logs carry and Azure Firewall rule logs
do not. Azure Firewall application rules log only the FQDN, so to follow web traffic put both the FQDN and the IP
in *Destination*."""

# Each Azure Firewall in the selected subscriptions, whether its rule logs reach this workspace, and whether flow
# trace logs (AZFWFlowTrace) do. Records arriving is the proof: a ticked diagnostic category sends nothing until
# flow trace is also enabled for the firewall's subscription.
LOGGING_Q = """
let Firewalls = print FirewallId = dynamic([{AzureFirewallIds}])
    | mv-expand FirewallId to typeof(string)
    | where isnotempty(FirewallId);
let RuleLogs = union isfuzzy=true (datatable(TimeGenerated: datetime, _ResourceId: string)[]),
        AZFWNetworkRule, AZFWApplicationRule, AZFWNatRule
    | where TimeGenerated {TimeRange}
    | summarize LastRuleLog = max(TimeGenerated) by FirewallId = tolower(_ResourceId);
let Trace = union isfuzzy=true (datatable(TimeGenerated: datetime, _ResourceId: string)[]), AZFWFlowTrace
    | where TimeGenerated {TimeRange}
    | summarize FlowTraceRecords = count(), Invalid = countif(tostring(column_ifexists('Flag', '')) =~ 'INVALID'),
        LastFlowTrace = max(TimeGenerated) by FirewallId = tolower(_ResourceId);
Firewalls
| join kind=leftouter RuleLogs on FirewallId
| join kind=leftouter Trace on FirewallId
| project FirewallId,
    RuleLogs = iff(isnull(LastRuleLog), 'None in this workspace', 'Arriving'),
    FlowTrace = case(FlowTraceRecords > 0, 'On', isnull(LastRuleLog), 'Unknown', 'Off'),
    FlowTraceRecords = coalesce(FlowTraceRecords, 0), Invalid = coalesce(Invalid, 0), LastFlowTrace, LastRuleLog
| order by case(FlowTrace == 'Off', 0, FlowTrace == 'Unknown', 1, 2) asc, FirewallId asc
"""

LOGGING_NOTE = """**Off** means the firewall's rule logs reach this workspace but no flow trace records do. Flow trace needs both:
1. **AZFWFlowTrace** ticked in the firewall's diagnostic setting (resource-specific mode), and
2. flow trace enabled for the subscription: `Register-AzProviderFeature -FeatureName AFWEnableTcpConnectionLogging
   -ProviderNamespace Microsoft.Network`, then `Register-AzResourceProvider -ProviderNamespace Microsoft.Network`.
   Registration can take a while to apply.

Flow trace logs every SYN-ACK, FIN, RST and invalid packet, so they are high-volume and add ingestion cost. Many
teams turn them on while troubleshooting and off again afterwards. **Unknown** means the firewall sends no rule
logs to this workspace either; it may log to another workspace, or have no diagnostic setting."""

# Sessions a firewall let through that never got an answer, and drops of packets that did not open a session.
# Both point at the return path rather than a rule. Azure Firewall's version is the INVALID flag in the optional
# flow trace log (AZFWFlowTrace), which records packets that are not part of a known session.
NO_REPLY_Q = r"""
union isfuzzy=true
    (Flows
    | where NoReply or NotSyn
    | extend Symptom = iff(NotSyn, 'Out-of-state drop (asymmetric routing)', 'Allowed, nothing came back')),
    (union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (AZFWFlowTrace)
    | where TimeGenerated {TimeRange}
    | where tostring(column_ifexists('Flag', '')) =~ 'INVALID'
    | project TimeGenerated, Platform = 'Azure Firewall', Device = tostring(split(_ResourceId, '/')[-1]),
        SourceIp = tostring(column_ifexists('SourceIp', '')), DestinationIp = tostring(column_ifexists('DestinationIp', '')),
        DestinationPort = toint(column_ifexists('DestinationPort', int(null))), Protocol = tostring(column_ifexists('Protocol', '')),
        Reason = tostring(column_ifexists('ActionReason', '')), RuleName = '',
        Symptom = 'Packet outside a known session (flow trace INVALID)'
    | where array_length(Platforms) == 0 or 'Azure Firewall' in (Platforms)
    | where array_length(Devices) == 0 or Device in~ (Devices)
    | where isempty(SrcText) or ipv4_is_in_any_range(SourceIp, SrcList) == true
    | where isempty(DstText) or ipv4_is_in_any_range(DestinationIp, DstList) == true
    | where isempty(PortText) or DestinationPort in (PortSet)
    | extend Destination = DestinationIp)
| summarize Events = count(), LastSeen = max(TimeGenerated), Rules = strcat_array(make_set(RuleName, 5), ', '),
    Reasons = strcat_array(make_set(Reason, 5), ' | ')
    by Symptom, Platform, Device, SourceIp, Destination, DestinationPort, Protocol
| order by Events desc
| take 200
"""

RULES_Q = """
Shown
| summarize Events = count(), Sources = dcount(SourceIp), Destinations = dcount(Destination),
    Ports = strcat_array(make_set(DestinationPort, 10), ', '), Devices = strcat_array(make_set(Device, 5), ', '),
    LastSeen = max(TimeGenerated)
    by Verdict, Source, Policy, RuleCollectionGroup, RuleCollection, RuleName, Reason
| order by Events desc
| take 100
"""

TOP_SOURCES_Q = """
Shown
| summarize Events = count(), Destinations = dcount(Destination), LastSeen = max(TimeGenerated) by SourceIp
| top 25 by Events desc
"""

TOP_DESTINATIONS_Q = """
Shown
| summarize Events = count(), Sources = dcount(SourceIp), Ports = strcat_array(make_set(DestinationPort, 10), ', '),
    LastSeen = max(TimeGenerated) by Destination
| top 25 by Events desc
"""

EVENTS_Q = """
Shown
| top 500 by TimeGenerated desc
| project TimeGenerated, Verdict, Device, DeviceId, Source, Action, SourceIp, SourcePort, Destination, DestinationPort, Protocol,
    TargetUrl, Policy, RuleCollectionGroup, RuleCollection, RuleName, Reason
"""

# DNS failures look like a block from the client side. Azure Firewall only (DNS proxy); the port filter
# does not apply. Both DNS tables exist only once a firewall has written to them, so each is read through an
# empty placeholder table and column_ifexists, the same way as the rule logs.
DNS_Q = FILTERS + r"""
union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (AZFWDnsQuery)
| where TimeGenerated {TimeRange}
| extend QueryName = tostring(column_ifexists('QueryName', '')), QueryType = tostring(column_ifexists('QueryType', '')),
    ResponseCode = tostring(column_ifexists('ResponseCode', '')), SourceIp = tostring(column_ifexists('SourceIp', '')),
    Device = tostring(split(tostring(column_ifexists('_ResourceId', '')), '/')[-1])
| where ResponseCode !~ 'NOERROR'
| where array_length(Platforms) == 0 or 'Azure Firewall' in (Platforms)
| where array_length(Devices) == 0 or Device in~ (Devices)
| where isempty(SrcText) or ipv4_is_in_any_range(SourceIp, SrcList) == true
| where isempty(DstText) or QueryName has_any (DstList)
| summarize Queries = count(), Sources = dcount(SourceIp), LastSeen = max(TimeGenerated) by QueryName, QueryType, ResponseCode
| top 50 by Queries desc
"""

# A network rule written with FQDNs needs DNS proxy to resolve them; when that fails, the rule never matches.
FQDN_FAIL_Q = FILTERS + r"""
union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (AZFWFqdnResolveFailure)
| where TimeGenerated {TimeRange}
| extend Fqdn = tostring(column_ifexists('Fqdn', '')), ServerIp = tostring(column_ifexists('ServerIp', '')),
    ServerPort = toint(column_ifexists('ServerPort', int(null))), Error = tostring(column_ifexists('Error', '')),
    Device = tostring(split(tostring(column_ifexists('_ResourceId', '')), '/')[-1])
| where array_length(Platforms) == 0 or 'Azure Firewall' in (Platforms)
| where array_length(Devices) == 0 or Device in~ (Devices)
| where isempty(DstText) or Fqdn has_any (DstList)
| summarize Failures = count(), LastSeen = max(TimeGenerated) by Fqdn, ServerIp, ServerPort, Error
| top 50 by Failures desc
"""

HOW_TO = """\
Fill in whatever you know about the connection (source, destination, port) and leave the rest empty.
Each box takes a comma-separated list (ports also take ranges, e.g. `11000-11999`), and an empty box matches
everything, so with nothing filled in you see everything blocked in the time range. If traffic crosses more than one firewall (say a Palo Alto
behind an Azure Firewall), *Verdict per flow* shows what each one decided.

**Azure Firewall.** Threat intelligence and IDPS are checked first and can drop traffic before any rule runs.
Then DNAT rules, then network rules, then application rules (HTTP, HTTPS and MSSQL only). Traffic that matches no
rule is denied, and shows as *(no rule matched: default deny)*: add an allow rule.

**Palo Alto and Check Point.** The rule column is the rule that matched: Palo Alto's `interzone-default`, or
Check Point's cleanup rule, means nothing allowed it. Palo Alto threat logs (antivirus, vulnerability, URL
filtering) show as *Palo Alto threat*; Check Point blades show under their product name (IPS, Application Control).

**NSG.** Network security group decisions come from VNet flow logs with Traffic Analytics
(`NTANetAnalytics`). An NSG deny never shows in a firewall's log, so this is the last hop before the destination.

**Nothing shows up?** Set *Show* to *Blocked and allowed*. If the flow is not logged at all, it never reached the
firewall (check the route table on the source subnet, or vWAN routing intent), or its logs are not reaching this
workspace: Azure Firewall needs a diagnostic setting sending the resource-specific `AZFW*` tables, and Palo Alto
and Check Point need to send CEF (`CommonSecurityLog`), with logging turned on for the rule. Azure Firewall flow
trace logs (`AZFWFlowTrace`) are optional and add Azure Firewall to the out-of-state check. Plain syslog and the
older Azure Firewall `AzureDiagnostics` format are not read here."""


# ---------------------------------------------------------------------------
# SQL Managed Instance checks (Resource Graph, loaded on demand)
# ---------------------------------------------------------------------------

Q_MI = "resources\n| where type =~ 'microsoft.sql/managedinstances'"

# Every subnet in the selected subscriptions with its route table and NSG, keyed by lower-case subnet id.
SUBNETS = """
    resources
    | where type =~ 'microsoft.network/virtualnetworks'
    | mv-expand s = properties.subnets limit 2000
    | project subnetId = tolower(tostring(s.id)), Prefix = tostring(s.properties.addressPrefix),
        RouteTable = tolower(tostring(s.properties.routeTable.id)), Nsg = tolower(tostring(s.properties.networkSecurityGroup.id))"""

MI_BASE = Q_MI + """
| where id in~ ({ManagedInstance})
| project mi = id, Instance = name, subnetId = tolower(tostring(properties.subnetId)), properties
| join kind=leftouter (""" + SUBNETS + """
  ) on subnetId"""

# Proxy needs 1433 only; Redirect also needs 11000-11999 to the instance's nodes. Default is decided by the
# service, so it is flagged for checking. The public endpoint, when on, listens on 3342.
MI_OVERVIEW_Q = MI_BASE + """
| extend ConnectionType = tostring(properties.proxyOverride), PublicEndpoint = tostring(properties.publicDataEndpointEnabled)
| project mi, State = tostring(properties.state), ConnectionType,
    PortsNeeded = strcat(case(ConnectionType =~ 'Proxy', '1433', ConnectionType =~ 'Redirect', '1433, 11000-11999',
        '1433 (and 11000-11999 if Redirect)'), iff(PublicEndpoint =~ 'true', '; 3342 for the public endpoint', '')),
    Fqdn = tostring(properties.fullyQualifiedDomainName), Subnet = tostring(split(subnetId, '/')[10]), Prefix,
    RouteTable = tostring(split(RouteTable, '/')[8]), Nsg = tostring(split(Nsg, '/')[8]), PublicEndpoint,
    MinTls = tostring(properties.minimalTlsVersion)
"""

# Routes on the instance's subnet. The service adds its own routes for management traffic; a user route that
# sends 0.0.0.0/0 to a firewall is supported, but the service routes must stay.
MI_ROUTES_Q = MI_BASE + """
| join kind=inner (
    resources
    | where type =~ 'microsoft.network/routetables'
    | mv-expand r = properties.routes limit 2000
    | project RouteTable = tolower(id), Route = tostring(r.name), AddressPrefix = tostring(r.properties.addressPrefix),
        NextHop = tostring(r.properties.nextHopType), NextHopIp = tostring(r.properties.nextHopIpAddress)
  ) on RouteTable
| extend Check = case(
    Route has 'UseOnly' or Route startswith 'mi-', 'Service route (managed by SQL MI)',
    AddressPrefix == '0.0.0.0/0' and NextHop =~ 'VirtualAppliance', 'Default route to a firewall: return traffic must come back the same way',
    NextHop =~ 'VirtualAppliance', 'Sent to a firewall',
    NextHop =~ 'None', 'Dropped',
    '')
| project Instance, RouteTable = tostring(split(RouteTable, '/')[8]), Route, AddressPrefix, NextHop, NextHopIp, Check
| order by Instance asc, Check desc, AddressPrefix asc
"""

# NSG rules on the instance's subnet that cover the SQL ports. Each rule's ports are expanded to ranges so a rule
# for "*", "1000-2000" or a list is matched correctly.
MI_NSG_Q = MI_BASE + """
| join kind=inner (
    resources
    | where type =~ 'microsoft.network/networksecuritygroups'
    | mv-expand rule = properties.securityRules limit 2000
    | project Nsg = tolower(id), Rule = tostring(rule.name), Direction = tostring(rule.properties.direction),
        Access = tostring(rule.properties.access), Priority = toint(rule.properties.priority),
        Source = coalesce(tostring(rule.properties.sourceAddressPrefix), strcat_array(rule.properties.sourceAddressPrefixes, ', ')),
        Destination = coalesce(tostring(rule.properties.destinationAddressPrefix), strcat_array(rule.properties.destinationAddressPrefixes, ', ')),
        Ports = coalesce(tostring(rule.properties.destinationPortRange), strcat_array(rule.properties.destinationPortRanges, ','))
  ) on Nsg
| mv-expand p = split(Ports, ',') limit 400
| extend p = trim(' ', tostring(p))
| extend lo = toint(extract('^([0-9]+)', 1, p)), hi = toint(extract('-([0-9]+)$', 1, p))
| extend hi = iff(isnull(hi), lo, hi), AnyPort = p == '*'
| summarize Tds = sum(iff(AnyPort or (lo <= 1433 and hi >= 1433), 1, 0)),
    Redirect = sum(iff(AnyPort or (lo <= 11999 and hi >= 11000), 1, 0)),
    Public = sum(iff(AnyPort or (lo <= 3342 and hi >= 3342), 1, 0))
    by Instance, Nsg, Rule, Direction, Access, Priority, Source, Destination, Ports
| where Tds > 0 or Redirect > 0 or Public > 0
| project Instance, Nsg = tostring(split(Nsg, '/')[8]), Direction, Priority, Rule, Access, Source, Destination, Ports,
    Covers = trim(' ', strcat_array(pack_array(iff(Tds > 0, '1433', ''), iff(Redirect > 0, '11000-11999', ''), iff(Public > 0, '3342', '')), ' '))
| order by Instance asc, Direction asc, Priority asc
"""

# The instance, its virtual network (subnet changes are recorded against the network), route table and NSG, as a
# quoted list for the changes query.
MI_RELATED_Q = MI_BASE + """
| extend related = pack_array(tolower(mi), tostring(split(subnetId, '/subnets/')[0]), RouteTable, Nsg)
| mv-expand related
| where isnotempty(tostring(related))
| summarize ids = make_set(tostring(related))
| project value = strcat("'", strcat_array(ids, "','"), "'")
"""

MI_CHANGES_Q = """
resourcechanges
| extend Time = todatetime(properties.changeAttributes.timestamp)
| where Time >= todatetime('{TimeRange:startISO}')
| extend id = tolower(tostring(properties.targetResourceId))
| where id in~ ({MiRelated})
| project Time, id, Type = tostring(split(tostring(properties.targetResourceType), '/')[1]), ChangeType = tostring(properties.changeType),
    Properties = strcat_array(bag_keys(properties.changes), ', '),
    ChangedBy = tostring(properties.changeAttributes.changedBy),
    Client = tostring(properties.changeAttributes.clientType),
    Operation = tostring(properties.changeAttributes.operation)
| order by Time desc
| take 200
"""

MI_NOTE = """\
Connection type decides the ports: **Proxy** uses 1433 only. **Redirect** connects on 1433, then sends the client
straight to the instance's node on **11000-11999**, so every firewall and NSG on the way must allow both, to the
whole instance subnet rather than one IP. The public endpoint uses **3342**. To check the path above, put the
instance subnet in *Destination* and `1433, 11000-11999` in *Destination port*."""


def sql_mi_group():
    return group("fwts-sqlmi", [
        text("fwts-sqlmi-h", "## SQL Managed Instance checks\nConfiguration that commonly breaks connectivity to a "
             "managed instance: connection type and ports, routes and NSG rules on its subnet, and what changed."),
        params("fwts-sqlmi-params", [
            resource_param("ManagedInstance", "Managed instances", Q_MI),
            {
                "id": gid("fwts-param-MiRelated"),
                "version": "KqlParameterItem/1.0",
                "name": "MiRelated",
                "type": 1,
                "query": MI_RELATED_Q.strip(),
                "crossComponentResources": ["{Subscription}"],
                "isHiddenWhenLocked": True,
                "queryType": 1,
                "resourceType": "microsoft.resourcegraph/resources",
            },
        ]),
        text("fwts-sqlmi-note", MI_NOTE, "info"),
        arg("fwts-sqlmi-overview", "Managed instances", MI_OVERVIEW_Q,
            formatters=[resource_link("mi"), status_fmt("State", good=["Ready"], warn=["Updating", "Creating"], bad=["Failed"]),
                        status_fmt("ConnectionType", good=["Proxy", "Redirect"], warn=["Default"])],
            labels={"mi": "Instance", "ConnectionType": "Connection type", "PortsNeeded": "Ports to allow",
                    "Fqdn": "FQDN", "Prefix": "Subnet range", "RouteTable": "Route table", "Nsg": "NSG",
                    "PublicEndpoint": "Public endpoint", "MinTls": "Minimum TLS"},
            no_data="No managed instances in the selected subscriptions."),
        arg("fwts-sqlmi-routes", "Routes on the instance subnet", MI_ROUTES_Q, width=50,
            formatters=[status_fmt("Check", good=["Service route (managed by SQL MI)"],
                                   warn=["Default route to a firewall: return traffic must come back the same way",
                                         "Sent to a firewall"], bad=["Dropped"])],
            labels={"RouteTable": "Route table", "AddressPrefix": "Prefix", "NextHop": "Next hop", "NextHopIp": "Next hop IP"},
            no_data="No route table on the instance subnet."),
        arg("fwts-sqlmi-nsg", "NSG rules on the instance subnet covering SQL ports", MI_NSG_Q, width=50,
            formatters=[status_fmt("Access", good=["Allow"], bad=["Deny"])],
            labels={"Nsg": "NSG", "Covers": "SQL ports covered"},
            no_data="No custom NSG rules cover 1433, 11000-11999 or 3342: the default rules apply (virtual network "
                    "traffic allowed, internet inbound denied)."),
        arg("fwts-sqlmi-changes", "Changes to the instance, its network, route table and NSG (time range, up to 14 days)",
            MI_CHANGES_Q, formatters=[resource_link()],
            labels={"id": "Resource", "ChangeType": "Change", "ChangedBy": "Changed by"},
            no_data="No changes in the time range. Widen it (Resource Graph keeps 14 days)."),
    ], load_button="Show SQL Managed Instance checks")


def workbook():
    return {
        "version": "Notebook/1.0",
        "items": [
            text("fwts-header", "# Firewalls: blocked connections\n"
                 "Is a firewall blocking this connection, and which rule did it? Covers Azure Firewall (network, "
                 "application and DNAT rules, threat intelligence and IDPS), Palo Alto, Check Point and NSGs, "
                 "and shows where along the path a flow stops."),
            parameters(),
            text("fwts-workspace-hint", "Select the **Log Analytics workspace** your firewalls log to.", "info",
                 visible_when=WORKSPACE_UNSET),
            text("fwts-howto", HOW_TO, "info", visible_when=WORKSPACE_SET),
            fw("fwts-summary", "Events by verdict and log source", SUMMARY_Q, vis="tiles", tiles=VERDICT_TILES,
               no_data="No matching firewall events. Try *Blocked and allowed*, a longer time range, or fewer filters."),
            fw("fwts-path", "Path through the firewalls: where does each flow stop?", PATH_Q,
               formatters=HOP_FORMATTERS + [STOPPED_AT, resource_link("AzureFirewallId"), resource_link("NsgId")],
               labels={"SourceKey": "Source IP", "DestinationKey": "Destination", "DestinationPort": "Port",
                       "StoppedAt": "Stopped at", "AzureFirewall": "Azure Firewall", "AzureFirewallRule": "Azure Firewall rule",
                       "PaloAlto": "Palo Alto", "PaloAltoRule": "Palo Alto rule", "CheckPoint": "Check Point",
                       "CheckPointRule": "Check Point rule", "Nsg": "NSG", "NsgRule": "NSG rule",
                       "AzureFirewallId": "Azure Firewall resource", "NsgId": "NSG resource",
                       "Firewalls": "Devices", "LastSeen": "Last seen"},
               no_data="No matching flows. Try a longer time range or fewer filters."),
            text("fwts-path-note", PATH_NOTE, "info", visible_when=WORKSPACE_SET),
            fw("fwts-noreply", "Allowed but no reply, and out-of-state drops (return path problems)", NO_REPLY_Q,
               formatters=[status_fmt("Symptom", warn=["Allowed, nothing came back"],
                                      bad=["Out-of-state drop (asymmetric routing)",
                                           "Packet outside a known session (flow trace INVALID)"])],
               labels={"Device": "Firewall", "SourceIp": "Source IP", "DestinationPort": "Port", "LastSeen": "Last seen"},
               no_data="No unanswered sessions or out-of-state drops. Azure Firewall needs flow trace logs "
                       "(AZFWFlowTrace) turned on to appear here: see *Azure Firewall logging* below."),
            la("fwts-logging", "Azure Firewall logging: rule logs and flow trace, per firewall", LOGGING_Q,
               formatters=[resource_link("FirewallId"),
                           status_fmt("RuleLogs", good=["Arriving"], bad=["None in this workspace"]),
                           status_fmt("FlowTrace", good=["On"], warn=["Off"], neutral=["Unknown"])],
               labels={"FirewallId": "Azure Firewall", "RuleLogs": "Rule logs", "FlowTrace": "Flow trace",
                       "FlowTraceRecords": "Flow trace records", "Invalid": "Invalid packets",
                       "LastFlowTrace": "Last flow trace", "LastRuleLog": "Last rule log"},
               no_data="No Azure Firewalls in the selected subscriptions."),
            text("fwts-logging-note", LOGGING_NOTE, "info", visible_when=WORKSPACE_SET),
            # Each panel runs the whole shared query again, so the secondary ones wait behind a button.
            group("fwts-more", [
            fw("fwts-timeline", "Events over time", TIMELINE_Q, vis="timechart"),
            fw("fwts-verdicts", "Verdict per flow (latest decision by each firewall, blocked and allowed)", VERDICTS_Q,
               formatters=[LAST_ACTION, low_is_good("Blocked", 1, 1), resource_link("DeviceId")],
               labels={"LastSeen": "Last seen", "SourceIp": "Source IP", "DestinationPort": "Port", "Device": "Firewall",
                       "Action": "Last action", "Source": "Decided by", "RuleName": "Rule", "FirstSeen": "First seen",
                       "DeviceId": "Azure resource"},
               no_data="No matching flows."),
            fw("fwts-rules", "Rules that matched", RULES_Q, formatters=[VERDICT],
               labels={"Source": "Log", "RuleCollectionGroup": "Rule collection group",
                       "RuleCollection": "Rule collection / layer", "RuleName": "Rule", "Devices": "Firewalls",
                       "LastSeen": "Last seen"},
               no_data="No matching rule hits."),
            fw("fwts-top-sources", "Top source IPs", TOP_SOURCES_Q, width=50,
               labels={"SourceIp": "Source IP", "LastSeen": "Last seen"}),
            fw("fwts-top-destinations", "Top destinations", TOP_DESTINATIONS_Q, width=50,
               labels={"LastSeen": "Last seen"}),
            ], load_button="Show timeline, verdict per flow, rules and top talkers"),
            fw("fwts-events", "Events (latest 500)", EVENTS_Q, formatters=[VERDICT, resource_link("DeviceId")],
               labels={"TimeGenerated": "Time", "Device": "Firewall", "DeviceId": "Azure resource", "Source": "Log", "SourceIp": "Source IP",
                       "SourcePort": "Source port", "DestinationPort": "Port", "TargetUrl": "URL",
                       "RuleCollectionGroup": "Rule collection group", "RuleCollection": "Rule collection / layer",
                       "RuleName": "Rule"},
               no_data="No matching events."),
            text("fwts-dns-h", "### DNS (Azure Firewall)\nA name that does not resolve looks like a block from the "
                 "client. These need DNS proxy on the firewall policy.", visible_when=WORKSPACE_SET),
            la("fwts-dns", "Failing DNS proxy queries", DNS_Q, width=50,
               labels={"QueryName": "Query", "QueryType": "Type", "ResponseCode": "Response", "LastSeen": "Last seen"},
               no_data="No failing DNS queries (or DNS proxy logs are not enabled)."),
            la("fwts-fqdn-fail", "FQDNs in network rules that failed to resolve", FQDN_FAIL_Q, width=50,
               labels={"ServerIp": "DNS server", "ServerPort": "Port", "LastSeen": "Last seen"},
               no_data="No FQDN resolution failures."),
            sql_mi_group(),
        ],
        "fallbackResourceIds": ["Azure Monitor"],
        "$schema": "https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json",
    }


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" keeps the output byte-identical on Windows and Linux; CI regenerates it and compares.
    OUT.write_text(json.dumps(workbook(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
