"""Generates the Azure Bastion workbook.

Run:  python src/build_bastion.py
Out:  workbook/bastion.workbook.json

Every Bastion host in the estate: how each is configured (SKU, scale units, features, zones), whether its
AzureBastionSubnet is built the way Bastion needs, which virtual machines it can reach and which it cannot, the
NSG rules that let RDP and SSH in from the internet around it, who connected to what and from where, how busy and
healthy the hosts are, and who changed them or created shareable links. From Resource Graph, Azure Monitor metrics
and Log Analytics (the Bastion audit logs and the Activity log). Built from the helpers in build_workbook.py so the
workbooks look alike.
"""

import pathlib

from build_workbook import (AVG, DAY_MS, MAX, ONE_TILE, PROVISIONING, SUBSCRIPTION_NAMES, WORKSPACE_UNSET, arg,
                            big_number_tiles, free_text_param, gid, group, la, low_is_good, m, metric_grid, metrics,
                            notebook, params, resource_link, resource_param, status_fmt, subscription_param, text,
                            time_param, workspace_param, write_workbook)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "bastion.workbook.json"

P = "bas"

BNS = "microsoft.network/bastionhosts"

TABS = [
    ("overview", "Overview"),
    ("config", "Configuration"),
    ("reach", "Reach & bypass"),
    ("sessions", "Sessions"),
    ("health", "Health & capacity"),
    ("changes", "Changes & admin"),
]

THREE_TILES = 600


def yes(expr):
    return f"iff({expr} == true, 'Yes', 'No')"


# ---------------------------------------------------------------------------
# Bastion hosts (Resource Graph)
# ---------------------------------------------------------------------------

# A Developer SKU host has no subnet or public IP of its own: it records only the VNet it serves.
BASTIONS = r"""
resources
| where type =~ 'microsoft.network/bastionhosts'
| extend subnet = tolower(tostring(properties.ipConfigurations[0].properties.subnet.id))
| extend Sku = tostring(sku.name),
    Vnet = coalesce(extract(@'^(.*/virtualnetworks/[^/]+)/subnets/', 1, subnet), tolower(tostring(properties.virtualNetwork.id))),
    PublicIp = tolower(tostring(properties.ipConfigurations[0].properties.publicIPAddress.id)),
    ScaleUnits = toint(properties.scaleUnits),
    NativeClient = """ + yes("tobool(properties.enableTunneling)") + r""",
    IpConnect = """ + yes("tobool(properties.enableIpConnect)") + r""",
    ShareableLink = """ + yes("tobool(properties.enableShareableLink)") + r""",
    FileCopy = """ + yes("tobool(properties.enableFileCopy)") + r""",
    CopyPaste = iff(tobool(properties.disableCopyPaste) == true, 'Blocked', 'Allowed'),
    Kerberos = """ + yes("tobool(properties.enableKerberos)") + r""",
    Recording = """ + yes("tobool(properties.enableSessionRecording)") + r""",
    Access = iff(tobool(properties.enablePrivateOnlyBastion) == true, 'Private only', iff(sku.name =~ 'Developer', 'Shared (Developer)', 'Public IP')),
    Zones = case(array_length(zones) >= 2, 'Zone-redundant', array_length(zones) == 1, strcat('Zone ', tostring(zones[0])), 'No zone set'),
    DnsName = tostring(properties.dnsName),
    Provisioning = tostring(properties.provisioningState)"""

INVENTORY_Q = BASTIONS + SUBSCRIPTION_NAMES + r"""
| project id, Sku, ScaleUnits, Access, Vnet, PublicIp, Zones, NativeClient, IpConnect, ShareableLink, FileCopy, CopyPaste,
    Kerberos, Recording, Provisioning, Subscription, ResourceGroup = resourceGroup, Location = location
| order by Subscription asc, tostring(id) asc
"""

# One row per finding per host, worst first.
FINDINGS_Q = BASTIONS + SUBSCRIPTION_NAMES + r"""
| extend Findings = array_concat(
    iff(Provisioning !~ 'Succeeded', pack_array(strcat('Provisioning ', Provisioning)), dynamic([])),
    iff(Sku =~ 'Developer', dynamic(['Developer SKU']), dynamic([])),
    iff(Sku =~ 'Basic', dynamic(['Basic SKU']), dynamic([])),
    iff(ShareableLink == 'Yes', dynamic(['Shareable links on']), dynamic([])),
    iff(Sku in~ ('Standard', 'Premium') and ScaleUnits <= 2, dynamic(['Two instances (the minimum)']), dynamic([])),
    iff(Sku =~ 'Premium' and Recording == 'No', dynamic(['Session recording off']), dynamic([])),
    iff(Sku !~ 'Developer' and Zones == 'No zone set', dynamic(['No zones set']), dynamic([])))
| mv-expand Finding = Findings to typeof(string)
| where isnotempty(Finding)
| extend Severity = case(Finding startswith 'Provisioning', 'High', Finding in ('Developer SKU', 'Shareable links on'), 'Medium',
        Finding == 'Basic SKU', 'Medium', 'Low'),
    Advice = case(
        Finding startswith 'Provisioning', 'Open the host and retry the last operation; a failed host may not accept connections',
        Finding == 'Developer SKU', 'Shared infrastructure with no SLA, one VNet only and no peering: use Basic or above for anything beyond testing',
        Finding == 'Basic SKU', 'No native client, IP-based connection, Kerberos, shareable links or scaling: upgrade to Standard if any are needed (an upgrade, not a rebuild)',
        Finding == 'Shareable links on', 'Anyone holding a link can reach the VM without Azure portal access; check the links issued (Changes & admin) and turn off if unused',
        Finding == 'Two instances (the minimum)', 'Each instance carries about 20 RDP or 40 SSH sessions; compare with the peak on Health & capacity',
        Finding == 'Session recording off', 'Premium can record sessions to a storage account, often required for privileged access to production',
        Finding == 'No zones set', 'Bastion can be zone-redundant only when created so, in regions that support it; recreate to change',
        '')
| project Severity, Finding, id, Sku, ScaleUnits, Advice, Subscription, ResourceGroup = resourceGroup
| order by case(Severity == 'High', 0, Severity == 'Medium', 1, 2) asc, Finding asc
"""

# Every AzureBastionSubnet, with the host in it and what its NSG allows. Bastion needs a /26 or larger, supports no
# route table on the subnet, and an NSG on it must keep the rules Bastion needs: HTTPS in from the internet (unless
# the host is private only) and from GatewayManager, and out to the VMs (RDP and SSH to VirtualNetwork) and AzureCloud.
SUBNETS_Q = r"""
resources
| where type =~ 'microsoft.network/virtualnetworks'
| mv-expand s = properties.subnets
| where tostring(s.name) =~ 'AzureBastionSubnet'
| extend subnet = tolower(tostring(s.id)),
    Prefix = coalesce(tostring(s.properties.addressPrefix), tostring(s.properties.addressPrefixes[0])),
    Nsg = tolower(tostring(s.properties.networkSecurityGroup.id)),
    RouteTable = tolower(tostring(s.properties.routeTable.id))
| extend Size = toint(extract(@'/(\d+)$', 1, Prefix))
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/bastionhosts'
    | project subnet = tolower(tostring(properties.ipConfigurations[0].properties.subnet.id)), Bastion = tolower(id),
        PrivateOnly = tobool(properties.enablePrivateOnlyBastion)
  ) on subnet
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/networksecuritygroups'
    | mv-expand r = properties.securityRules
    | extend dir = tostring(r.properties.direction), access = tostring(r.properties.access),
        src = tostring(r.properties.sourceAddressPrefix), dst = tostring(r.properties.destinationAddressPrefix),
        ports = strcat(tostring(r.properties.destinationPortRange), ',', strcat_array(r.properties.destinationPortRanges, ','))
    | extend allowIn = dir =~ 'Inbound' and access =~ 'Allow', allowOut = dir =~ 'Outbound' and access =~ 'Allow'
    | summarize HttpsFromInternet = countif(allowIn and src in~ ('Internet', '*') and (ports has '443' or ports contains '*')) > 0,
        FromGatewayManager = countif(allowIn and src =~ 'GatewayManager') > 0,
        ToVms = countif(allowOut and dst in~ ('VirtualNetwork', '*') and (ports has '3389' or ports has '22' or ports contains '*')) > 0,
        ToAzureCloud = countif(allowOut and dst in~ ('AzureCloud', '*')) > 0
        by Nsg = tolower(id)
  ) on Nsg
| extend Problems = array_concat(
    iff(Size > 26, dynamic(['Smaller than /26']), dynamic([])),
    iff(isnotempty(RouteTable), dynamic(['Route table attached (not supported)']), dynamic([])),
    iff(isnotempty(Nsg) and PrivateOnly != true and HttpsFromInternet != true, dynamic(['NSG: no HTTPS in from Internet']), dynamic([])),
    iff(isnotempty(Nsg) and FromGatewayManager != true, dynamic(['NSG: no GatewayManager in']), dynamic([])),
    iff(isnotempty(Nsg) and ToVms != true, dynamic(['NSG: no RDP/SSH out to VirtualNetwork']), dynamic([])),
    iff(isnotempty(Nsg) and ToAzureCloud != true, dynamic(['NSG: no HTTPS out to AzureCloud']), dynamic([])))
| project Vnet = tolower(id), Prefix, Bastion, Nsg, RouteTable,
    State = case(array_length(Problems) > 0, 'Problem', isempty(Bastion), 'No Bastion in it', 'OK'),
    Problems = strcat_array(Problems, ' · '), subscriptionId, ResourceGroup = resourceGroup
""" + SUBSCRIPTION_NAMES + r"""
| project-away subscriptionId, subscriptionId1
| order by case(State == 'Problem', 0, State == 'OK', 1, 2) asc
"""

SUBNETS_NOTE = """\
The checks follow Microsoft's requirements for the subnet. An NSG on AzureBastionSubnet is optional, but if there is
one it must allow, at least: **inbound** HTTPS (443) from *Internet* (not needed for a private-only host) and from
*GatewayManager*, and 8080 and 5701 within *VirtualNetwork* for the host's own data plane; **outbound** RDP and SSH
(3389, 22) to *VirtualNetwork*, HTTPS to *AzureCloud*, and 80 to *Internet* for certificate checks. The checks here
look for the main ones by service tag; a rule that names address ranges instead is not recognised. Bastion does not
support a route table on its subnet, so traffic from it cannot be forced through a firewall."""

SKU_NOTE = """\
**What each SKU adds.** *Developer*: free, shared, one VNet, browser only, no peering. *Basic*: a dedicated host
with two instances, reaching VMs in its own and directly peered VNets. *Standard*: adds scaling (2 to 50 instances),
the native client (`az network bastion rdp/ssh`), IP-based connection (any routable address, including on-premises),
Kerberos, shareable links and file copy. *Premium*: adds session recording and private-only deployment (no public IP)."""

# ---------------------------------------------------------------------------
# Reach and bypass
# ---------------------------------------------------------------------------

# Bastion reaches VMs in its own VNet and, except the Developer SKU, in VNets directly peered with it (peering
# connected). Each VNet is paired with itself and its connected peers, matched to the hosts' VNets, and every VM is
# then placed by the VNet of its first NIC.
REACH_Q = r"""
resources
| where type =~ 'microsoft.network/networkinterfaces'
| where isnotempty(tostring(properties.virtualMachine.id))
| extend vm = tolower(tostring(properties.virtualMachine.id)),
    vnet = tolower(extract(@'(?i)^(.*/virtualnetworks/[^/]+)/subnets/', 1, tostring(properties.ipConfigurations[0].properties.subnet.id))),
    VmIp = tostring(properties.ipConfigurations[0].properties.privateIPAddress)
| summarize vnet = take_any(vnet), VmIp = take_any(VmIp) by vm, subscriptionId, resourceGroup
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/virtualnetworks'
    | extend vnet = tolower(id)
    | mv-expand p = iff(array_length(properties.virtualNetworkPeerings) > 0, properties.virtualNetworkPeerings, pack_array(dynamic({})))
    | extend remote = iff(tostring(p.properties.peeringState) =~ 'Connected', tolower(tostring(p.properties.remoteVirtualNetwork.id)), '')
    | mv-expand cand = pack_array(vnet, remote) to typeof(string)
    | where isnotempty(cand)
    | join kind=inner (
        resources
        | where type =~ 'microsoft.network/bastionhosts'
        | extend cand = coalesce(tolower(extract(@'(?i)^(.*/virtualnetworks/[^/]+)/subnets/', 1, tostring(properties.ipConfigurations[0].properties.subnet.id))),
            tolower(tostring(properties.virtualNetwork.id)))
        | project cand, Bastion = tolower(id), BastionSku = tostring(sku.name)
      ) on cand
    | extend Path = iff(cand == vnet, 'Same VNet', 'Peered VNet')
    | where Path == 'Same VNet' or BastionSku !~ 'Developer'
    | summarize Path = max(Path), Bastions = make_set(Bastion, 5) by vnet
  ) on vnet
| extend Reach = iff(isempty(Path), 'No Bastion in its VNet or a peered VNet', Path), Bastion = tostring(Bastions[0])
""" + SUBSCRIPTION_NAMES

REACH_TILE_Q = REACH_Q + r"""
| summarize VMs = count(), Without = countif(Reach startswith 'No ')
| project Signal = 'VMs with no Bastion path', Value = Without, State = iff(Without > 0, 'Degraded', 'Available'),
    Detail = strcat('of ', VMs, ' VMs (own or peered VNet)')
"""

REACH_PIE_Q = REACH_Q + "\n| summarize VMs = count() by Reach\n| order by VMs desc"

REACH_LIST_Q = REACH_Q + r"""
| project Reach, id = vm, VmIp, Vnet = vnet, Bastion, Subscription, ResourceGroup = resourceGroup
| order by case(Reach startswith 'No ', 0, 1) asc, Vnet asc
"""

REACH_NOTE = """\
Bastion reaches VMs in its own VNet and in VNets **directly peered** with it. In a Virtual WAN landing zone, spokes
are connected to the hub rather than peered with each other, so a host in one spoke does not reach VMs in another
by default: give each spoke that needs it a host (the Developer SKU costs nothing for testing), or use a Standard or
Premium host with **IP-based connection**, which connects to any private address the host can route to (through
the hub, or on-premises) if the NSGs allow it. VMs listed as having no path may still be reachable that way."""

# Inbound rules that let RDP or SSH in from anywhere: the way round Bastion that it exists to replace. A rule on an
# NSG that is not attached to a subnet or NIC does nothing, and a VM is only exposed if it also has a public IP or
# sits behind a public load balancer, but the rule is a finding either way.
BYPASS_Q = r"""
resources
| where type =~ 'microsoft.network/networksecuritygroups'
| where tostring(properties.subnets) !contains '/subnets/azurebastionsubnet'
| mv-expand r = properties.securityRules
| extend src = tostring(r.properties.sourceAddressPrefix), srcs = r.properties.sourceAddressPrefixes
| where tostring(r.properties.direction) =~ 'Inbound' and tostring(r.properties.access) =~ 'Allow'
| where src in ('*', 'Internet', '0.0.0.0/0', 'Any') or set_has_element(srcs, '*') or set_has_element(srcs, 'Internet')
    or set_has_element(srcs, '0.0.0.0/0')
| extend portList = array_concat(pack_array(tostring(r.properties.destinationPortRange)),
    iff(isnull(r.properties.destinationPortRanges), dynamic([]), r.properties.destinationPortRanges))
| mv-expand port = portList to typeof(string)
| extend lo = toint(split(port, '-')[0]), hi = toint(iff(port contains '-', tostring(split(port, '-')[1]), port))
| extend Rdp = port == '*' or (lo <= 3389 and hi >= 3389), Ssh = port == '*' or (lo <= 22 and hi >= 22)
| where Rdp or Ssh
| summarize Ports = strcat_array(make_set(port), ', '), Rdp = max(toint(Rdp)), Ssh = max(toint(Ssh))
    by id, Rule = tostring(r.name), Priority = toint(r.properties.priority), Source = iff(isnotempty(src), src, strcat_array(srcs, ', ')),
    Subnets = array_length(properties.subnets), Nics = array_length(properties.networkInterfaces), subscriptionId, resourceGroup
| extend Exposes = case(Rdp == 1 and Ssh == 1, 'RDP and SSH', Rdp == 1, 'RDP', 'SSH'),
    InUse = iff(coalesce(Subnets, 0) + coalesce(Nics, 0) > 0, 'Attached', 'Not attached')
""" + SUBSCRIPTION_NAMES + r"""
| project Exposes, id, Rule, Priority, Source, Ports, InUse, Subnets, Nics, Subscription, ResourceGroup = resourceGroup
| order by case(InUse == 'Attached', 0, 1) asc, Exposes asc
"""

BYPASS_TILE_Q = BYPASS_Q + r"""
| summarize Rules = count(), Attached = countif(InUse == 'Attached')
| project Signal = 'RDP/SSH open to the internet', Value = Attached, State = iff(Attached > 0, 'Unavailable', 'Available'),
    Detail = strcat('NSG rules in use · ', Rules - Attached, ' more on unattached NSGs')
"""

# ---------------------------------------------------------------------------
# Sessions (Bastion audit logs)
# ---------------------------------------------------------------------------

# Sessions from the resource-specific table, or from AzureDiagnostics for a diagnostic setting in the older mode.
# Duration is in milliseconds; SessionEndTime is held as text. The user and target filters at the top apply.
SESSIONS = r"""let Sessions = union isfuzzy=true
    (datatable(TimeGenerated: datetime, Bastion: string, User: string, ClientIp: string, Target: string, TargetIp: string,
        Protocol: string, Start: datetime, End: datetime, DurationMs: long, UserAgent: string, Operation: string, Message: string)[]),
    (MicrosoftAzureBastionAuditLogs
    | where TimeGenerated {TimeRange}
    | project TimeGenerated, Bastion = tolower(_ResourceId), User = coalesce(UserEmail, UserName), ClientIp = ClientIpAddress,
        Target = tolower(TargetResourceId), TargetIp = TargetVMIPAddress, Protocol, Start = SessionStartTime,
        End = todatetime(SessionEndTime), DurationMs = tolong(Duration), UserAgent, Operation = OperationName, Message),
    (AzureDiagnostics
    | where TimeGenerated {TimeRange}
    | where Category == 'BastionAuditLogs'
    | project TimeGenerated, Bastion = tolower(ResourceId),
        User = coalesce(tostring(column_ifexists('userEmail_s', '')), tostring(column_ifexists('userName_s', ''))),
        ClientIp = tostring(column_ifexists('clientIpAddress_s', '')), Target = tolower(tostring(column_ifexists('targetResourceId_s', ''))),
        TargetIp = tostring(column_ifexists('targetVMIPAddress_s', '')), Protocol = tostring(column_ifexists('protocol_s', '')),
        Start = todatetime(column_ifexists('sessionStartTime_t', datetime(null))),
        End = todatetime(column_ifexists('sessionEndTime_t', datetime(null))),
        DurationMs = tolong(column_ifexists('duration_d', real(null))), UserAgent = tostring(column_ifexists('userAgent_s', '')),
        Operation = OperationName, Message = tostring(column_ifexists('message_s', '')))
    | extend Start = coalesce(Start, TimeGenerated)
    | extend Minutes = round(coalesce(todouble(End - Start) / 600000000.0, DurationMs / 60000.0), 1),
        Client = case(UserAgent has_any ('mstsc', 'Remote Desktop', 'ssh', 'AzureCLI', 'azure-cli', 'python'), 'Native client',
            UserAgent has_any ('Mozilla', 'Chrome', 'Edg/', 'Safari', 'Firefox'), 'Browser', 'Unknown'),
        TargetName = iff(isnotempty(Target), tostring(split(Target, '/')[-1]), TargetIp)
    | where '{User}' == '' or User contains '{User}'
    | where '{Target}' == '' or Target contains '{Target}' or TargetIp == '{Target}' or TargetName =~ '{Target}';
"""

SESSION_TILES_Q = SESSIONS + r"""Sessions
| summarize Sessions = count(), Users = dcount(User), Targets = dcount(coalesce(Target, TargetIp)), ClientIps = dcount(ClientIp),
    Hours = round(sum(Minutes) / 60, 1), Native = countif(Client == 'Native client'), Longest = max(Minutes)
| extend rows = pack_array(
    pack('Order', 1, 'Signal', 'Sessions', 'Value', Sessions, 'Detail', strcat(Hours, ' hours in all')),
    pack('Order', 2, 'Signal', 'People', 'Value', Users, 'Detail', strcat('from ', ClientIps, ' client addresses')),
    pack('Order', 3, 'Signal', 'Machines reached', 'Value', Targets, 'Detail', 'VMs or IP addresses'),
    pack('Order', 4, 'Signal', 'Longest session', 'Value', round(Longest / 60, 1), 'Detail', 'hours'),
    pack('Order', 5, 'Signal', 'Native client', 'Value', iff(Sessions > 0, round(100.0 * Native / Sessions, 0), 0.0),
        'Detail', '% of sessions (the rest in a browser)'))
| mv-expand r = rows
| project Order = toint(r.Order), Signal = tostring(r.Signal), Value = toreal(r.Value), Detail = tostring(r.Detail), State = 'Unknown'
| order by Order asc
"""

SESSION_TREND_Q = SESSIONS + r"""Sessions
| summarize Sessions = count() by bin(Start, {TimeRange:grain}), Protocol
"""

SESSION_LIST_Q = SESSIONS + r"""Sessions
| project Start, End, Minutes, User, ClientIp, Target, TargetIp, Protocol, Client, Bastion, UserAgent
| order by Start desc
| take 1000
"""

USERS_Q = SESSIONS + r"""Sessions
| summarize Sessions = count(), Machines = dcount(coalesce(Target, TargetIp)), ClientIps = dcount(ClientIp),
    Hours = round(sum(Minutes) / 60, 1), First = min(Start), Last = max(Start),
    Addresses = strcat_array(make_set(ClientIp, 5), ', ') by User
| order by Sessions desc
"""

TARGETS_Q = SESSIONS + r"""Sessions
| summarize Sessions = count(), People = dcount(User), Hours = round(sum(Minutes) / 60, 1), Last = max(Start),
    Users = strcat_array(make_set(User, 5), ', '), Protocols = strcat_array(make_set(Protocol), ', ')
    by Target = coalesce(Target, TargetIp)
| order by Sessions desc
"""

# Things worth a second look: sessions of 8 hours or more (left open), and a person connecting from an address
# they had not used before in the time range's first half.
UNUSUAL_Q = SESSIONS + r"""let Half = (now() - {TimeRange:start}) / 2;
let Seen = Sessions | where Start < {TimeRange:start} + Half | distinct User, ClientIp;
union
    (Sessions | where Minutes >= 480
        | project Start, Why = 'Session of 8 hours or more', User, ClientIp, Target = coalesce(Target, TargetIp), Minutes),
    (Sessions | where Start >= {TimeRange:start} + Half
        | join kind=leftanti Seen on User, ClientIp
        | where User in ((Seen | distinct User))
        | summarize Start = min(Start), Target = take_any(coalesce(Target, TargetIp)), Minutes = sum(Minutes) by User, ClientIp
        | extend Why = 'New client address for this person')
| order by Start desc
| take 500
"""

# Concurrent sessions per host in 15-minute steps, from each session's start and end.
CONCURRENT_Q = SESSIONS + r"""Sessions
| where isnotnull(Start)
| extend End = coalesce(End, Start + DurationMs * 1ms, now())
| extend End = iff(End - Start > 7d, Start + 7d, End)
| mv-expand Bin = range(bin(Start, 15m), End, 15m) to typeof(datetime)
| summarize Concurrent = count() by Bin, Bastion = tostring(split(Bastion, '/')[-1])
"""

SESSIONS_NOTE = """\
From each host's **Bastion audit logs** (diagnostic setting category *BastionAuditLogs*, table
`MicrosoftAzureBastionAuditLogs`, or `AzureDiagnostics` in the older mode). A session is logged when it ends. *Client*
is read from the user agent: the native client (`az network bastion rdp/ssh`, or `mstsc` through a tunnel) or a
browser. Filter by **User** and **Target** at the top to follow one person or one machine."""

# ---------------------------------------------------------------------------
# Changes and admin actions
# ---------------------------------------------------------------------------

CHANGES_Q = r"""
resourcechanges
| where tolower(tostring(properties.targetResourceType)) == 'microsoft.network/bastionhosts'
| extend Time = todatetime(properties.changeAttributes.timestamp)
| where Time >= todatetime('{TimeRange:startISO}')
| extend changes = properties.changes
| project Time, ChangeType = tostring(properties.changeType), id = tolower(tostring(properties.targetResourceId)),
    What = strcat_array(bag_keys(changes), ', '),
    ChangedBy = tostring(properties.changeAttributes.changedBy), Client = tostring(properties.changeAttributes.clientType)
| order by Time desc
| take 500
"""

# Shareable links and session management are actions, not changes to the host, so only the Activity log has them.
ADMIN_Q = r"""
AzureActivity
| where TimeGenerated {TimeRange}
| where OperationNameValue has 'MICROSOFT.NETWORK/BASTIONHOSTS/'
| where OperationNameValue !endswith '/READ'
| where ActivityStatusValue in~ ('Success', 'Succeeded', 'Failed', 'Failure')
| extend Action = case(
    OperationNameValue has 'CREATESHAREABLELINKS', 'Shareable links created',
    OperationNameValue has 'DELETESHAREABLELINKS', 'Shareable links deleted',
    OperationNameValue has 'GETSHAREABLELINKS', 'Shareable links listed',
    OperationNameValue has 'DISCONNECTACTIVESESSIONS', 'Sessions disconnected',
    OperationNameValue has 'GETACTIVESESSIONS', 'Active sessions listed',
    OperationNameValue endswith '/WRITE', 'Created or changed',
    OperationNameValue endswith '/DELETE', 'Deleted',
    tostring(split(OperationNameValue, '/')[-1]))
| project TimeGenerated, Action, Caller, CallerIpAddress, Status = ActivityStatusValue, id = tolower(_ResourceId)
| order by TimeGenerated desc
| take 500
"""

ACTION = status_fmt("Action", warn=["Shareable links created", "Sessions disconnected", "Created or changed"],
                    bad=["Deleted"])

# ---------------------------------------------------------------------------
# Overview tiles (Resource Graph)
# ---------------------------------------------------------------------------

HOSTS_TILE_Q = BASTIONS + r"""
| summarize Hosts = count(), Failed = countif(Provisioning !~ 'Succeeded'),
    Dev = countif(Sku =~ 'Developer'), Basic = countif(Sku =~ 'Basic'), Std = countif(Sku =~ 'Standard'), Prem = countif(Sku =~ 'Premium')
| project Signal = 'Bastion hosts', Value = Hosts, State = iff(Failed > 0, 'Unavailable', 'Available'),
    Detail = strcat_delim(' · ', strcat(Prem, ' Premium'), strcat(Std, ' Standard'), strcat(Basic, ' Basic'), strcat(Dev, ' Developer'))
"""

LINKS_TILE_Q = BASTIONS + r"""
| summarize Links = countif(ShareableLink == 'Yes'), Hosts = count()
| project Signal = 'Shareable links on', Value = Links, State = iff(Links > 0, 'Degraded', 'Available'),
    Detail = strcat('of ', Hosts, ' hosts')
"""

SUBNET_TILE_Q = SUBNETS_Q + r"""
| summarize Problems = countif(State == 'Problem'), Subnets = count()
| project Signal = 'Bastion subnets with problems', Value = Problems, State = iff(Problems > 0, 'Unavailable', 'Available'),
    Detail = strcat('of ', Subnets, ' AzureBastionSubnets')
"""

# ---------------------------------------------------------------------------
# Parameters, tabs and layout
# ---------------------------------------------------------------------------

Q_BASTIONS = "resources\n| where type =~ 'microsoft.network/bastionhosts'\n| where sku.name !~ 'Developer'"


def global_params():
    return params(f"{P}-params", [
        subscription_param(P),
        workspace_param(P, "The workspace that receives the Bastion audit logs and the Activity log."),
        time_param(P, 7 * DAY_MS, [d * DAY_MS for d in (1, 3, 7, 14, 30, 60, 90)],
                   "For sessions, metrics and changes. Resource Graph keeps 14 days of changes."),
        free_text_param(P, "User", "User", "Optional. Part of a user's name or email, to follow one person's sessions."),
        free_text_param(P, "Target", "Target",
                        "Optional. A VM name, part of its resource id, or its IP address, to see who connected to it."),
        {"id": gid(f"{P}-param-selectedTab"), "version": "KqlParameterItem/1.0", "name": "selectedTab", "type": 1,
         "value": "overview", "isHiddenWhenLocked": True},
    ])


def tabs():
    return {"type": 11, "content": {"version": "LinkItem/1.0", "style": "tabs", "links": [
        {"id": gid(f"{P}-tab-" + key), "cellValue": "selectedTab", "linkTarget": "parameter",
         "linkLabel": label, "subTarget": key, "style": "link"} for key, label in TABS
    ]}, "name": f"{P}-tabs"}


TILES = big_number_tiles("Signal", "State", "Value", "Detail")
YES_WARN = lambda col: status_fmt(col, warn=["Yes"])
YES_GOOD = lambda col: status_fmt(col, good=["Yes"])
SEVERITY = status_fmt("Severity", warn=["Medium"], bad=["High"], neutral=["Low"])
ZONES = status_fmt("Zones", good=["Zone-redundant"], warn=["Zone 1", "Zone 2", "Zone 3"], neutral=["No zone set"])
REACH = status_fmt("Reach", good=["Same VNet", "Peered VNet"], warn=["No Bastion in its VNet or a peered VNet"])
WORKSPACE_HINT = ("Select a **Log Analytics workspace** at the top for sessions: who connected to what, from where, "
                  "and for how long.")


def overview_tab():
    return group(f"{P}-tab-overview", [
        arg(f"{P}-tile-hosts", "", HOSTS_TILE_Q, vis="tiles", tiles=TILES, fixed_px=ONE_TILE),
        arg(f"{P}-tile-subnets", "", SUBNET_TILE_Q, vis="tiles", tiles=TILES, fixed_px=ONE_TILE),
        arg(f"{P}-tile-reach", "", REACH_TILE_Q, vis="tiles", tiles=TILES, fixed_px=ONE_TILE),
        arg(f"{P}-tile-bypass", "", BYPASS_TILE_Q, vis="tiles", tiles=TILES, fixed_px=ONE_TILE),
        arg(f"{P}-tile-links", "", LINKS_TILE_Q, vis="tiles", tiles=TILES, fixed_px=ONE_TILE),
        text(f"{P}-hint", WORKSPACE_HINT, "info", visible_when=WORKSPACE_UNSET),
        la(f"{P}-session-tiles", "", SESSION_TILES_Q, vis="tiles", tiles=TILES),
        arg(f"{P}-findings", "Findings", FINDINGS_Q, formatters=[SEVERITY, resource_link()],
            labels={"id": "Bastion", "ScaleUnits": "Instances", "ResourceGroup": "Resource group"},
            no_data="No findings: every host is provisioned, on Basic or above, with shareable links off."),
        la(f"{P}-trend", "Sessions by protocol", SESSION_TREND_Q, vis="timechart"),
    ], tab="overview")


def config_tab():
    return group(f"{P}-tab-config", [
        arg(f"{P}-inventory", "Bastion hosts", INVENTORY_Q,
            formatters=[resource_link(), resource_link("Vnet"), resource_link("PublicIp"), PROVISIONING, ZONES,
                        YES_GOOD("NativeClient"), YES_GOOD("IpConnect"), YES_WARN("ShareableLink"), YES_GOOD("Recording"),
                        status_fmt("Sku", warn=["Developer"], neutral=["Basic"], good=["Standard", "Premium"])],
            labels={"id": "Bastion", "Sku": "SKU", "ScaleUnits": "Instances", "Vnet": "VNet", "PublicIp": "Public IP",
                    "NativeClient": "Native client", "IpConnect": "IP-based connection", "ShareableLink": "Shareable links",
                    "FileCopy": "File copy", "CopyPaste": "Copy and paste", "Recording": "Session recording",
                    "ResourceGroup": "Resource group"},
            no_data="No Bastion hosts in the selected subscriptions."),
        text(f"{P}-sku-note", SKU_NOTE, "info"),
        arg(f"{P}-subnets", "AzureBastionSubnet in every VNet", SUBNETS_Q,
            formatters=[status_fmt("State", good=["OK"], bad=["Problem"], neutral=["No Bastion in it"]), resource_link("Vnet"),
                        resource_link("Bastion"), resource_link("Nsg"), resource_link("RouteTable")],
            labels={"Vnet": "VNet", "Nsg": "NSG", "RouteTable": "Route table", "ResourceGroup": "Resource group"},
            no_data="No VNet has an AzureBastionSubnet."),
        text(f"{P}-subnets-note", SUBNETS_NOTE, "info"),
    ], tab="config")


def reach_tab():
    return group(f"{P}-tab-reach", [
        arg(f"{P}-reach-pie", "Virtual machines by Bastion path", REACH_PIE_Q, vis="piechart", width=35,
            chart={"seriesLabelSettings": [{"seriesName": "Same VNet", "color": "green"},
                                           {"seriesName": "Peered VNet", "color": "greenDark"},
                                           {"seriesName": "No Bastion in its VNet or a peered VNet", "color": "orange"}]}),
        text(f"{P}-reach-note", REACH_NOTE, "info"),
        arg(f"{P}-reach", "Virtual machines and the Bastion that reaches them", REACH_LIST_Q,
            formatters=[REACH, resource_link(), resource_link("Vnet"), resource_link("Bastion")],
            labels={"id": "Virtual machine", "VmIp": "Private IP", "Vnet": "VNet", "ResourceGroup": "Resource group"},
            group_by="Reach", no_data="No virtual machines in the selected subscriptions."),
        text(f"{P}-bypass-h", "### Around Bastion: RDP and SSH open to the internet"),
        arg(f"{P}-bypass", "NSG rules allowing RDP or SSH in from any address", BYPASS_Q,
            formatters=[status_fmt("Exposes", bad=["RDP and SSH", "RDP", "SSH"]), resource_link(),
                        status_fmt("InUse", warn=["Attached"], neutral=["Not attached"])],
            labels={"id": "NSG", "InUse": "NSG in use", "Nics": "NICs", "ResourceGroup": "Resource group"},
            no_data="No NSG rule lets RDP or SSH in from the internet."),
        text(f"{P}-bypass-note", "A VM is reachable through such a rule only if it also has a public IP or sits behind "
             "a public load balancer, but each rule is one change away from exposing a management port, which is "
             "what Bastion is there to avoid. Narrow the source, or remove the rule and connect through Bastion. "
             "Rules on the AzureBastionSubnet's own NSG are left out.", "info"),
    ], tab="reach")


def sessions_tab():
    return group(f"{P}-tab-sessions", [
        text(f"{P}-sessions-hint", WORKSPACE_HINT, "info", visible_when=WORKSPACE_UNSET),
        text(f"{P}-sessions-note", SESSIONS_NOTE, "info"),
        la(f"{P}-sessions", "Sessions", SESSION_LIST_Q,
           formatters=[resource_link("Target"), resource_link("Bastion"),
                       status_fmt("Client", good=["Native client"], neutral=["Browser", "Unknown"]),
                       low_is_good("Minutes", 240, 480)],
           labels={"ClientIp": "Client address", "TargetIp": "Target IP"},
           no_data="No Bastion sessions in the time range, or the hosts do not send audit logs to this workspace."),
        la(f"{P}-users", "By person", USERS_Q, width=50,
           labels={"ClientIps": "Client addresses", "Addresses": "Addresses used"}, no_data="No sessions."),
        la(f"{P}-targets", "By machine", TARGETS_Q, width=50, formatters=[resource_link("Target")],
           no_data="No sessions."),
        la(f"{P}-unusual", "Worth a second look", UNUSUAL_Q,
           formatters=[resource_link("Target"), status_fmt("Why", warn=["Session of 8 hours or more",
                                                                         "New client address for this person"])],
           labels={"ClientIp": "Client address"},
           no_data="No sessions of 8 hours or more, and nobody connected from an address new to them."),
        text(f"{P}-unusual-note", "*New client address* compares the second half of the time range with the first: a "
             "person who connected from an address they had not used before. Expect some from home working and "
             "changing ISPs; follow up on addresses in unexpected countries.", "info"),
    ], tab="sessions")


def health_tab():
    return group(f"{P}-tab-health", [
        params(f"{P}-health-params", [resource_param("Bastions", "Bastion hosts", Q_BASTIONS)]),
        metric_grid(f"{P}-kpis", "Bastion metrics (over time range)", BNS, "Bastions", [
            ("pingmesh", AVG, "Communication status", ("high", 1, 0.9)),
            ("sessions", MAX, "Sessions (peak)", None),
            ("usage_user", AVG, "CPU usage", ("low", 70, 90)),
            ("used", AVG, "Memory used", None),
        ]),
        metrics(f"{P}-sessions-chart", "Sessions", BNS, "Bastions", [m(BNS, "sessions", MAX)], width=50),
        metrics(f"{P}-pingmesh", "Communication status (1 = healthy)", BNS, "Bastions", [m(BNS, "pingmesh", AVG)],
                width=50),
        metrics(f"{P}-cpu", "CPU usage", BNS, "Bastions", [m(BNS, "usage_user", AVG)], width=50),
        metrics(f"{P}-memory", "Memory used", BNS, "Bastions", [m(BNS, "used", AVG)], width=50),
        text(f"{P}-capacity-h", "### Concurrent sessions, from the audit logs"),
        text(f"{P}-capacity-hint", WORKSPACE_HINT, "info", visible_when=WORKSPACE_UNSET),
        la(f"{P}-concurrent", "Concurrent sessions per host (15-minute steps)", CONCURRENT_Q, vis="timechart"),
        text(f"{P}-capacity-note", "Microsoft sizes each Bastion instance for about **20 concurrent RDP** or **40 "
             "concurrent SSH** sessions for typical use (fewer for heavy graphical work). A Basic host has two "
             "instances; Standard and Premium can be scaled from 2 to 50 in *Configuration → Instance count*. If the "
             "peak approaches instances × 20, scale up before people start seeing slow or refused connections. "
             "*Communication status* below 1 means the instances cannot reach each other or the control plane: "
             "check the subnet's NSG on the *Configuration* tab. The Developer SKU has no metrics and is left out "
             "of the picker.", "info"),
    ], tab="health")


def changes_tab():
    return group(f"{P}-tab-changes", [
        arg(f"{P}-changes", "Bastion hosts created, changed and deleted", CHANGES_Q,
            formatters=[status_fmt("ChangeType", good=["Create"], warn=["Update"], bad=["Delete"]), resource_link()],
            labels={"ChangeType": "Change", "id": "Bastion", "What": "Properties changed", "ChangedBy": "Changed by"},
            no_data="No Bastion host changed in the time range (Resource Graph keeps 14 days)."),
        text(f"{P}-admin-hint", "Select a **Log Analytics workspace** at the top for shareable links and session "
             "management, from the Activity log.", "info", visible_when=WORKSPACE_UNSET),
        la(f"{P}-admin", "Shareable links, session management and changes (Activity log)", ADMIN_Q,
           formatters=[ACTION, resource_link(), status_fmt("Status", good=["Success", "Succeeded"], bad=["Failed", "Failure"])],
           labels={"TimeGenerated": "Time", "CallerIpAddress": "Caller address", "id": "Bastion"},
           no_data="No Bastion actions in the Activity log in the time range."),
        text(f"{P}-admin-note", "A **shareable link** lets anyone who holds it reach that VM through Bastion without "
             "signing in to the Azure portal, until the link is deleted. Check who created each one, and delete links "
             "that are no longer needed (the host's *Shareable links* blade).", "warning"),
    ], tab="changes")


def workbook():
    return notebook([
        text(f"{P}-header", "# Azure Bastion\n"
             "Every Bastion host: how it is configured, whether its subnet is right, which VMs it can reach, the "
             "rules that let RDP and SSH round it, who connected to what, how busy it is, and who changed it."),
        global_params(),
        tabs(),
        overview_tab(),
        config_tab(),
        reach_tab(),
        sessions_tab(),
        health_tab(),
        changes_tab(),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
