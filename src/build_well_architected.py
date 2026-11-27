"""Generates the Well-Architected Framework workbook: a workload's gaps against the five pillars.

Run:  python src/build_well_architected.py
Out:  workbook/well-architected.workbook.json

A Well-Architected review is done per workload, so everything can be narrowed to one or more workloads, found by a
tag (`workload` unless changed). Each pillar has a tab with Azure Advisor's recommendations for it (Advisor's
categories are the pillars) and a set of configuration checks read from Resource Graph: the settings a reviewer
would otherwise look up resource by resource (zones, redundancy, SKUs being retired, public access, TLS, local
authentication, idle resources, monitoring agents, older VM sizes). A Log Analytics workspace is optional: picking
one adds the checks only logs can answer (heartbeats, request failures, denied access, resources sending no logs,
ingestion, CPU and memory), narrowed to the workload through a hidden list of its resource ids. A Workloads tab
compares every workload's findings side by side, and an Assessment tab asks the Well-Architected checklist
questions no setting can answer, scoring each pillar from the answers (kept when the workbook is saved).
Built from the helpers in build_workbook.py so the workbooks look alike.
"""

import json
import pathlib

from build_backup import VM_PROTECTION
from build_workbook import (ADVISOR_RECS, AGENT_STATUS, DAY_MS, ONE_TILE, SUBSCRIPTION_NAMES, WASTE_CHECKS,
                            WORKSPACE_UNSET, arg, big_number_tiles, export_row, free_text_param, gid, group, hidden,
                            high_is_good, la, low_is_good, machine_agents, notebook, params, pct_bar, resource_link,
                            status_fmt, subscription_param, text, time_param, when_set, workspace_param,
                            write_workbook)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "well-architected.workbook.json"

P = "waf"

TILES = big_number_tiles("Signal", "State", "Value", "Detail")
PCT_TILES = big_number_tiles("Signal", "State", "Value", "Detail", unit="%")

# ---------------------------------------------------------------------------
# Workload scope
# ---------------------------------------------------------------------------

# Placed straight after a `resources` type filter. With every workload selected nothing is filtered, so untagged
# resources count too.
SCOPE = "| where '*' in ({Workload}) or tostring(tags['{WorkloadTag}']) in ({Workload})"


def in_workload(col):
    """Narrows rows from another table (Advisor, Defender, changes) to the selected workloads, by resource id.
    With every workload selected the lookup returns nothing and nothing is filtered."""
    return f"""| join kind=leftouter (
    resources
    | where not('*' in ({{Workload}}))
    | where tostring(tags['{{WorkloadTag}}']) in ({{Workload}})
    | project {col} = tolower(id), inWorkload = true
  ) on {col}
| where '*' in ({{Workload}}) or inWorkload == true
"""


ADVISOR = ADVISOR_RECS + in_workload("rid")

WORKLOAD_Q = r"""
resources
| extend wl = tostring(tags['{WorkloadTag}'])
| where isnotempty(wl)
| summarize Resources = count() by wl
| project value = wl, label = strcat(wl, '  (', Resources, ' resources)')
| order by value asc
"""

# ---------------------------------------------------------------------------
# Configuration checks: (resource type, condition, finding, severity, detail, what to do)
# Findings and fixes go into KQL strings, so they must not contain a single quote.
# ---------------------------------------------------------------------------

NO_ZONES = "(isnull(zones) or array_length(zones) < 2)"
LOCAL_AUTH_TYPES = ["microsoft.servicebus/namespaces", "microsoft.eventhub/namespaces",
                    "microsoft.documentdb/databaseaccounts", "microsoft.cognitiveservices/accounts",
                    "microsoft.appconfiguration/configurationstores", "microsoft.signalrservice/signalr",
                    "microsoft.eventgrid/topics", "microsoft.eventgrid/domains"]
VM_SIZE = "tostring(properties.hardwareProfile.vmSize)"
SKU = "tostring(sku.name)"
TIER_SKU = "strcat(tostring(sku.tier), ' ', tostring(sku.name))"
FLEXIBLE_SERVERS = ["microsoft.dbforpostgresql/flexibleservers", "microsoft.dbformysql/flexibleservers"]
WAF_POLICIES = ["microsoft.network/applicationgatewaywebapplicationfirewallpolicies",
                "microsoft.network/frontdoorwebapplicationfirewallpolicies"]
PE_STATE = ("coalesce(tostring(properties.privateLinkServiceConnections[0].properties.privateLinkServiceConnectionState.status), "
            "tostring(properties.manualPrivateLinkServiceConnections[0].properties.privateLinkServiceConnectionState.status))")

RELIABILITY = [
    ("microsoft.compute/virtualmachines",
     "(isnull(zones) or array_length(zones) == 0) and isempty(tostring(properties.availabilitySet.id)) "
     "and isempty(tostring(properties.virtualMachineScaleSet.id))",
     "VM with no availability zone, availability set or scale set", "Medium", VM_SIZE,
     "Run two or more instances across availability zones, or record the single point of failure as accepted"),
    ("microsoft.network/publicipaddresses", "tostring(sku.name) =~ 'Basic'",
     "Basic SKU public IP (retired September 2025)", "High", "tostring(properties.ipAddress)",
     "Upgrade to a Standard SKU public IP"),
    ("microsoft.network/loadbalancers", "tostring(sku.name) =~ 'Basic'",
     "Basic SKU load balancer (retired September 2025)", "High", "''", "Upgrade to a Standard load balancer"),
    ("microsoft.network/applicationgateways", "tostring(properties.sku.tier) in~ ('Standard', 'WAF')",
     "Application Gateway v1 (retired April 2026)", "High", "tostring(properties.sku.name)",
     "Migrate to Application Gateway v2"),
    ("microsoft.network/applicationgateways", f"tostring(properties.sku.tier) in~ ('Standard_v2', 'WAF_v2') and {NO_ZONES}",
     "Application Gateway not spread across zones", "Medium", "tostring(properties.sku.name)",
     "Redeploy the gateway across availability zones"),
    ("microsoft.network/azurefirewalls", NO_ZONES, "Azure Firewall not spread across zones", "Medium",
     "tostring(properties.sku.tier)", "Deploy the firewall across availability zones"),
    ("microsoft.network/virtualnetworkgateways",
     "not(tostring(properties.sku.name) endswith 'AZ') and tostring(properties.sku.name) !~ 'ErGwScale'",
     "VPN or ExpressRoute gateway SKU is not zone-redundant", "Medium",
     "strcat(tostring(properties.gatewayType), ' ', tostring(properties.sku.name))",
     "Move to an AZ SKU (or ErGwScale for ExpressRoute)"),
    ("microsoft.storage/storageaccounts", "tostring(sku.name) endswith '_LRS'",
     "Storage account is locally redundant (LRS)", "Low", "strcat(tostring(sku.name), ' ', kind)",
     "Use ZRS, or GZRS for data that must survive the loss of a region"),
    ("microsoft.web/serverfarms",
     "tolower(tostring(sku.tier)) !in ('free', 'shared', 'dynamic', 'basic', 'elasticpremium', 'flexconsumption') "
     "and toint(sku.capacity) < 2",
     "App Service plan runs a single instance", "Medium", "strcat(tostring(sku.name), ' x', tostring(sku.capacity))",
     "Run at least two instances (three with zone redundancy)"),
    ("microsoft.web/serverfarms",
     "tolower(tostring(sku.tier)) in ('premiumv2', 'premiumv3', 'premium0v3', 'premiummv3', 'isolatedv2') "
     "and tobool(properties.zoneRedundant) != true",
     "App Service plan not zone-redundant", "Low", SKU, "Turn on zone redundancy (needs three or more instances)"),
    ("microsoft.sql/servers/databases",
     "name !~ 'master' and tostring(sku.tier) !in~ ('Basic', 'Standard', 'Free', 'System') "
     "and tobool(properties.zoneRedundant) != true",
     "SQL database not zone-redundant", "Low", "strcat(tostring(sku.tier), ' ', tostring(sku.name))",
     "Turn on zone redundancy"),
    ("microsoft.containerservice/managedclusters",
     "tostring(properties.agentPoolProfiles) !contains '\"availabilityZones\":[\"'",
     "AKS node pools not spread across zones", "Medium", "tostring(properties.kubernetesVersion)",
     "Create node pools across availability zones"),
    ("microsoft.containerservice/managedclusters", "tostring(sku.tier) =~ 'Free'",
     "AKS cluster on the Free tier (no uptime SLA)", "Medium", "''", "Use the Standard tier for production clusters"),
    ("microsoft.keyvault/vaults", "tobool(properties.enablePurgeProtection) != true",
     "Key Vault without purge protection", "Medium", "''",
     "Turn on purge protection so a deleted key or secret can always be recovered"),
    ("microsoft.cache/redis", "tostring(properties.sku.name) =~ 'Basic'",
     "Azure Cache for Redis on the Basic tier (one node, no SLA)", "Medium",
     "strcat(tostring(properties.sku.family), tostring(properties.sku.capacity))",
     "Use Standard or Premium for anything beyond development"),
    ("microsoft.documentdb/databaseaccounts",
     "coalesce(array_length(properties.locations), 0) < 2 "
     "and tostring(properties.locations) !contains '\"isZoneRedundant\":true'",
     "Cosmos DB account in one region with no zone redundancy", "Medium",
     "tostring(properties.locations[0].locationName)", "Turn on zone redundancy, or add a second region"),
    ("microsoft.network/frontdoors", "true", "Front Door (classic), retiring March 2027", "High", "''",
     "Migrate to Azure Front Door Standard or Premium"),
    ("microsoft.cdn/profiles", "tostring(sku.name) in~ ('Standard_Verizon', 'Premium_Verizon')",
     "Azure CDN from Edgio (shut down January 2025)", "High", SKU, "Move to Azure Front Door Standard or Premium"),
    ("microsoft.cdn/profiles", "tostring(sku.name) =~ 'Standard_Microsoft'",
     "Azure CDN Standard from Microsoft (classic), retiring September 2027", "Medium", SKU,
     "Migrate to Azure Front Door Standard or Premium"),
    ("microsoft.apimanagement/service", "tostring(properties.platformVersion) =~ 'stv1'",
     "API Management on the stv1 platform (retired August 2024)", "High", SKU, "Migrate the instance to stv2"),
    ("microsoft.apimanagement/service", "tostring(sku.name) =~ 'Developer'",
     "API Management on the Developer tier (no SLA)", "Medium", SKU, "Use Standard v2 or Premium for production"),
    ("microsoft.apimanagement/service", f"tostring(sku.name) =~ 'Premium' and {NO_ZONES}",
     "API Management not spread across zones", "Medium", "strcat(tostring(sku.name), ' x', tostring(sku.capacity))",
     "Deploy the units across availability zones"),
    ("microsoft.dbforpostgresql/servers", "true", "Azure Database for PostgreSQL single server (retired March 2025)",
     "High", SKU, "Migrate to a flexible server"),
    ("microsoft.dbformysql/servers", "true", "Azure Database for MySQL single server (retired September 2024)",
     "High", SKU, "Migrate to a flexible server"),
    ("microsoft.dbformariadb/servers", "true", "Azure Database for MariaDB (retired September 2025)", "High", SKU,
     "Migrate to Azure Database for MySQL flexible server"),
] + [(t, "tostring(properties.highAvailability.mode) in~ ('', 'Disabled') and tostring(sku.tier) !~ 'Burstable'",
      "PostgreSQL or MySQL flexible server with no high availability", "Medium", TIER_SKU,
      "Turn on zone-redundant high availability") for t in FLEXIBLE_SERVERS] + [
    (t, "tostring(properties.backup.geoRedundantBackup) =~ 'Disabled'",
     "PostgreSQL or MySQL flexible server backups not geo-redundant", "Low", TIER_SKU,
     "Turn on geo-redundant backup (set when the server is created) if the data must survive a region loss")
    for t in FLEXIBLE_SERVERS] + [
    ("microsoft.app/managedenvironments", "tobool(properties.zoneRedundant) != true",
     "Container Apps environment not zone-redundant", "Medium", "''",
     "Create the environment with zone redundancy (it cannot be changed afterwards)"),
    ("microsoft.recoveryservices/vaults",
     "tostring(properties.redundancySettings.standardTierStorageRedundancy) =~ 'LocallyRedundant'",
     "Recovery Services vault stores backups locally redundant", "Low", "''",
     "Use geo-redundant storage with cross-region restore for backups that must survive a region loss"),
    ("microsoft.recoveryservices/vaults",
     "tostring(properties.securitySettings.softDeleteSettings.softDeleteState) =~ 'Disabled'",
     "Recovery Services vault with soft delete off", "Medium", "''",
     "Turn soft delete on (or always-on) so deleted backups can be recovered"),
]

SECURITY = [
    ("microsoft.storage/storageaccounts", "tobool(properties.allowBlobPublicAccess) == true",
     "Storage account allows anonymous blob access", "High", "''", "Set blob anonymous access to Disabled"),
    ("microsoft.storage/storageaccounts", "tobool(properties.supportsHttpsTrafficOnly) == false",
     "Storage account accepts HTTP", "High", "''", "Require secure transfer (HTTPS only)"),
    ("microsoft.storage/storageaccounts", "tostring(properties.minimumTlsVersion) !in ('TLS1_2', 'TLS1_3')",
     "Storage account accepts TLS older than 1.2", "Medium", "tostring(properties.minimumTlsVersion)",
     "Set the minimum TLS version to 1.2"),
    ("microsoft.storage/storageaccounts",
     "tostring(properties.publicNetworkAccess) !~ 'Disabled' and tostring(properties.networkAcls.defaultAction) =~ 'Allow'",
     "Storage account open to all networks", "Medium", "''",
     "Use private endpoints, or set the firewall default action to Deny"),
    ("microsoft.storage/storageaccounts", "tobool(properties.allowSharedKeyAccess) != false",
     "Storage account allows shared key access", "Low", "''",
     "Authorise with Entra ID and turn off shared key access where the workload allows"),
    ("microsoft.keyvault/vaults",
     "tostring(properties.publicNetworkAccess) !~ 'Disabled' and tostring(properties.networkAcls.defaultAction) !~ 'Deny'",
     "Key Vault open to all networks", "High", "''", "Use a private endpoint, or set the firewall default action to Deny"),
    ("microsoft.keyvault/vaults", "tobool(properties.enableRbacAuthorization) != true",
     "Key Vault uses access policies, not Azure RBAC", "Low", "''", "Move the vault to the Azure RBAC permission model"),
    ("microsoft.sql/servers", "tostring(properties.publicNetworkAccess) !~ 'Disabled'",
     "SQL server public network access enabled", "Medium", "''",
     "Use private endpoints and turn off public network access"),
    ("microsoft.sql/servers", "tostring(properties.minimalTlsVersion) !in ('1.2', '1.3')",
     "SQL server accepts TLS older than 1.2", "Medium", "tostring(properties.minimalTlsVersion)",
     "Set the minimum TLS version to 1.2"),
    ("microsoft.sql/servers", "tobool(properties.administrators.azureADOnlyAuthentication) != true",
     "SQL server allows SQL authentication", "Low", "''", "Turn on Microsoft Entra-only authentication"),
    ("microsoft.web/sites", "tobool(properties.httpsOnly) != true", "App accepts HTTP", "High", "kind",
     "Turn on HTTPS Only"),
    ("microsoft.containerservice/managedclusters",
     "tobool(properties.apiServerAccessProfile.enablePrivateCluster) != true "
     "and coalesce(array_length(properties.apiServerAccessProfile.authorizedIPRanges), 0) == 0",
     "AKS API server open to the internet", "High", "''", "Use a private cluster, or authorised IP ranges"),
    ("microsoft.containerservice/managedclusters", "tobool(properties.disableLocalAccounts) != true",
     "AKS local accounts enabled", "Medium", "''", "Turn off local accounts and sign in with Entra ID"),
    ("microsoft.containerregistry/registries", "tobool(properties.anonymousPullEnabled) == true",
     "Container registry allows anonymous pull", "High", SKU, "Turn off anonymous pull"),
    ("microsoft.containerregistry/registries", "tobool(properties.adminUserEnabled) == true",
     "Container registry admin user enabled", "Medium", SKU,
     "Turn off the admin user; pull with managed identities or scoped tokens"),
    ("microsoft.compute/virtualmachines", "isempty(tostring(properties.securityProfile.securityType))",
     "VM without Trusted Launch", "Low", VM_SIZE,
     "Use Trusted Launch (secure boot and vTPM) for new VMs; existing Generation 2 VMs can be upgraded"),
    ("microsoft.apimanagement/service",
     r"""tostring(properties.customProperties) matches regex @'(?i)Protocols\.Tls1[01]":"true'""",
     "API Management accepts TLS 1.0 or 1.1", "Medium", SKU,
     "Turn off TLS 1.0 and 1.1 on the gateway and to the backends"),
    ("microsoft.network/applicationgateways", "tostring(properties.sku.tier) =~ 'Standard_v2'",
     "Application Gateway with no web application firewall", "Low", "tostring(properties.sku.name)",
     "Use the WAF_v2 tier with a WAF policy for anything facing the internet"),
    ("microsoft.documentdb/databaseaccounts",
     "tostring(properties.publicNetworkAccess) !~ 'Disabled' and tobool(properties.isVirtualNetworkFilterEnabled) != true "
     "and coalesce(array_length(properties.ipRules), 0) == 0",
     "Cosmos DB account open to all networks", "Medium", "''", "Use private endpoints, or limit access by network"),
    ("microsoft.cognitiveservices/accounts",
     "tostring(properties.publicNetworkAccess) !~ 'Disabled' and tostring(properties.networkAcls.defaultAction) !~ 'Deny'",
     "Azure AI services account open to all networks", "Medium", "kind",
     "Use private endpoints, or set the network default action to Deny"),
    ("microsoft.dbforpostgresql/flexibleservers", "tostring(properties.authConfig.passwordAuth) !~ 'Disabled'",
     "PostgreSQL flexible server allows password authentication", "Low", "''",
     "Use Microsoft Entra authentication and turn off password authentication"),
] + [(t, "tostring(properties.network.publicNetworkAccess) =~ 'Enabled'",
      "PostgreSQL or MySQL flexible server public network access enabled", "Medium", "''",
      "Use private access (virtual network integration) or private endpoints") for t in FLEXIBLE_SERVERS] + [
    (t, "tostring(properties.policySettings.mode) =~ 'Detection' "
        "or coalesce(tostring(properties.policySettings.state), tostring(properties.policySettings.enabledState)) =~ 'Disabled'",
     "WAF policy in Detection mode or turned off", "Medium",
     "strcat(tostring(properties.policySettings.mode), ' ', coalesce(tostring(properties.policySettings.state), "
     "tostring(properties.policySettings.enabledState)))",
     "Switch the policy to Prevention mode once false positives are tuned out") for t in WAF_POLICIES] + [
    (t, "tostring(properties.minimumTlsVersion) in ('1.0', '1.1')", "Messaging namespace accepts TLS older than 1.2",
     "Medium", "tostring(properties.minimumTlsVersion)", "Set the minimum TLS version to 1.2")
    for t in ["microsoft.servicebus/namespaces", "microsoft.eventhub/namespaces"]
] + [(t, "tobool(properties.disableLocalAuth) != true", "Key-based (local) authentication enabled", "Low", "''",
      "Turn off local authentication and use Entra ID") for t in LOCAL_AUTH_TYPES]

COST = [
    ("microsoft.compute/virtualmachines",
     "tostring(properties.storageProfile.osDisk.osType) =~ 'Windows' and isempty(tostring(properties.licenseType))",
     "Windows VM with no licence type (Azure Hybrid Benefit not used)", "Low", VM_SIZE,
     "With Windows Server licences under Software Assurance, set the licence type to Windows_Server"),
    ("microsoft.sqlvirtualmachine/sqlvirtualmachines", "tostring(properties.sqlServerLicenseType) =~ 'PAYG'",
     "SQL Server VM paying for its SQL licence", "Low", "tostring(properties.sqlImageSku)",
     "With SQL Server licences under Software Assurance, set the licence type to AHUB"),
    ("microsoft.compute/virtualmachines",
     "tostring(properties.extended.instanceView.powerState.code) =~ 'PowerState/deallocated' "
     "and tostring(properties.storageProfile.osDisk.managedDisk.storageAccountType) startswith 'Premium'",
     "Deallocated VM keeping Premium SSD disks", "Low", VM_SIZE,
     "Disks are billed while the VM is off: move long-stopped VMs to Standard SSD, or delete them"),
    ("microsoft.operationalinsights/workspaces", "toint(properties.retentionInDays) > 90",
     "Workspace keeps data searchable for more than 90 days", "Low",
     "strcat(tostring(properties.retentionInDays), ' days')",
     "Keep older data in long-term retention instead, unless it must stay searchable"),
    ("microsoft.operationalinsights/workspaces",
     "tostring(properties.sku.name) in~ ('pernode', 'standalone', 'standard', 'premium')",
     "Workspace on a legacy pricing tier", "Low", "tostring(properties.sku.name)",
     "Move to the pay-as-you-go (Per GB) tier, or a commitment tier at 100 GB a day or more"),
    ("microsoft.network/ddosprotectionplans", "coalesce(array_length(properties.virtualNetworks), 0) == 0",
     "DDoS protection plan protecting no virtual networks", "Medium", "''",
     "Delete it, or link it to the networks it should protect: a plan has a high fixed monthly charge"),
] + [(t, "tostring(properties.state) =~ 'Stopped'", "Stopped PostgreSQL or MySQL flexible server", "Low", TIER_SKU,
      "Storage is still billed, and the server starts itself again after 7 days: delete it if it is not needed")
     for t in FLEXIBLE_SERVERS] + [(t, cond, kind, "Medium", detail, fix) for t, cond, kind, detail, fix in WASTE_CHECKS]

ALERT_TYPES = ["microsoft.insights/metricalerts", "microsoft.insights/scheduledqueryrules",
               "microsoft.insights/activitylogalerts"]

OPERATIONS = [
    ("microsoft.compute/virtualmachines",
     "coalesce(tostring(properties.osProfile.windowsConfiguration.patchSettings.assessmentMode), "
     "tostring(properties.osProfile.linuxConfiguration.patchSettings.assessmentMode)) !~ 'AutomaticByPlatform'",
     "Periodic patch assessment off", "Low", "''",
     "Turn on periodic assessment in Azure Update Manager (or assign the built-in policy)"),
    ("microsoft.containerservice/managedclusters",
     "coalesce(tobool(properties.addonProfiles.omsagent.enabled), tobool(properties.addonProfiles.omsAgent.enabled), false) == false "
     "and tobool(properties.azureMonitorProfile.metrics.enabled) != true",
     "AKS cluster with no Container insights or managed Prometheus", "Medium", "''",
     "Turn on Container insights and managed Prometheus"),
    ("microsoft.containerservice/managedclusters",
     "tostring(properties.autoUpgradeProfile.upgradeChannel) in~ ('', 'none')",
     "AKS automatic upgrades off", "Low", "tostring(properties.kubernetesVersion)",
     "Set an auto-upgrade channel (patch or stable) with a planned maintenance window"),
    ("microsoft.insights/components", "isempty(tostring(properties.WorkspaceResourceId))",
     "Classic Application Insights (retired February 2024)", "Medium", "''",
     "Migrate to a workspace-based Application Insights resource"),
    ("microsoft.insights/actiongroups", "tobool(properties.enabled) == false",
     "Action group disabled", "Medium", "''", "Turn it back on, or delete it and the alert rules that use it"),
    ("microsoft.app/managedenvironments", "isempty(tostring(properties.appLogsConfiguration.destination))",
     "Container Apps environment sends its logs nowhere", "Low", "''",
     "Send the logs to Log Analytics or to Azure Monitor"),
    ("microsoft.network/privateendpoints", f"{PE_STATE} !~ 'Approved'",
     "Private endpoint connection not approved", "Medium", PE_STATE,
     "Approve the connection on the target resource, or delete the endpoint"),
] + [(t, "tobool(properties.enabled) == false", "Alert rule disabled", "Low", "''",
      "Turn it back on, or delete it if it is no longer needed") for t in ALERT_TYPES]

OLD_SIZES = (r"(?i)^(basic_a\d+|standard_a\d+m?(_v2)?|standard_d\d+(_v2)?|standard_ds\d+(-\d+)?(_v2)?|"
             r"standard_fs?\d+s?|standard_gs?\d+(-\d+)?|standard_n[cdv]\d+r?|standard_h\d+[a-z]*|standard_l\d+s)$")

PERFORMANCE = [
    ("microsoft.compute/virtualmachines", f"{VM_SIZE} matches regex @'{OLD_SIZES}'",
     "Older-generation VM size", "Low", VM_SIZE, "Resize to a current generation for better price-performance"),
    ("microsoft.compute/disks",
     "tostring(sku.name) =~ 'Standard_LRS' and tostring(properties.diskState) in~ ('Attached', 'Reserved')",
     "Disk on Standard HDD", "Low", "strcat(tostring(properties.diskSizeGB), ' GB')",
     "Use Standard SSD or Premium SSD for anything sensitive to latency"),
    ("microsoft.network/networkinterfaces",
     "isnotempty(tostring(properties.virtualMachine.id)) and tobool(properties.enableAcceleratedNetworking) != true",
     "Accelerated networking off", "Low", "''",
     "Turn on accelerated networking (most sizes with two or more vCPUs support it)"),
    ("microsoft.storage/storageaccounts", "kind in~ ('Storage', 'BlobStorage')",
     "Legacy storage account kind (general-purpose v1 or BlobStorage)", "Low", "kind",
     "Upgrade to general-purpose v2"),
    ("microsoft.web/serverfarms", "tostring(sku.tier) in~ ('Premium', 'PremiumV2')",
     "App Service plan on Premium v2 or older", "Low", SKU, "Move to Premium v3: faster cores at a lower price per core"),
    ("microsoft.containerservice/managedclusters",
     "tostring(properties.agentPoolProfiles) !contains '\"enableAutoScaling\":true'",
     "AKS cluster with no autoscaling node pool", "Low", "''", "Turn on the cluster autoscaler for user node pools"),
    ("microsoft.containerservice/managedclusters",
     "tostring(properties.agentPoolProfiles) contains '\"osDiskType\":\"Managed\"'",
     "AKS node pool on managed rather than ephemeral OS disks", "Low", "''",
     "Use ephemeral OS disks where the VM size allows: lower latency and faster scaling"),
] + [(t, "tostring(sku.tier) =~ 'Burstable'", "PostgreSQL or MySQL flexible server on the Burstable tier", "Low",
      SKU, "Burstable is for development and light loads (CPU is throttled once credits run out); use General Purpose")
     for t in FLEXIBLE_SERVERS]

for _checks in (RELIABILITY, SECURITY, COST, OPERATIONS, PERFORMANCE):
    for _c in _checks:
        assert "'" not in _c[2] + _c[3] + _c[5], _c


def findings(checks):
    """One row per resource and failed check."""
    types = ", ".join(f"'{t}'" for t in sorted({c[0] for c in checks}))
    packs = ",\n    ".join(
        f"iff(type =~ '{t}' and ({cond}), pack('Finding', '{finding}', 'Severity', '{sev}', 'Detail', {detail}, "
        f"'Fix', '{fix}'), dynamic(null))"
        for t, cond, finding, sev, detail, fix in checks)
    return f"""
resources
| where type in~ ({types})
{SCOPE}
| extend Findings = pack_array(
    {packs})
| mv-expand f = Findings
| where isnotempty(tostring(f.Finding))
| project Severity = tostring(f.Severity), Finding = tostring(f.Finding), id, Detail = tostring(f.Detail),
    Fix = tostring(f.Fix), Type = type, ResourceGroup = resourceGroup, subscriptionId
"""


SEVERITY_ORDER = "case(Severity == 'High', 0, Severity == 'Medium', 1, 2)"
SEVERITY = status_fmt("Severity", warn=["Medium"], bad=["High"], neutral=["Low"])
IMPACT = status_fmt("Impact", warn=["Medium"], bad=["High"], neutral=["Low"])
# Defender for Cloud alerts (High to Informational) and Azure Monitor alerts (Sev0 to Sev4) in one column.
SEVERITY_ANY = status_fmt("Severity", warn=["Medium", "Sev2"], bad=["High", "Sev0", "Sev1"],
                          neutral=["Low", "Informational", "Sev3", "Sev4"])

# ---------------------------------------------------------------------------
# The pillars: (tab key, name as Advisor's pillar, checks, intro)
# ---------------------------------------------------------------------------

PILLARS = [
    ("reliability", "Reliability", RELIABILITY,
     "Can the workload survive the failure of a zone, an instance or a dependency, and recover its data? The "
     "checks look for single instances, resources not spread across availability zones, locally redundant data "
     "and SKUs Azure has retired. A resource in a region without availability zones is flagged too: record it as "
     "accepted if so."),
    ("security", "Security", SECURITY,
     "Is the workload's data and access protected? The checks look for public network access, anonymous access, "
     "old TLS versions and key-based authentication where Entra ID could be used. The NSG rules and other "
     "internet exposure are on the **Azure Policy compliance** workbook's *Public exposure* tab."),
    ("cost", "Cost Optimization", COST,
     "Is the workload paying for anything it does not use? The checks look for idle resources, licences paid "
     "in the VM price and data kept longer than needed. Advisor's right-sizing, reservation and savings plan "
     "recommendations carry its estimated savings a year. Resource Graph holds no spend: use Cost Management for "
     "what the workload costs."),
    ("operations", "Operational Excellence", OPERATIONS,
     "Is the workload observable and maintained? The checks look for machines without the Azure Monitor Agent, "
     "patching that is not assessed, AKS clusters with no monitoring or upgrades, retired Application Insights, "
     "disabled alerting, and changes made by hand in the portal rather than through a pipeline."),
    ("performance", "Performance Efficiency", PERFORMANCE,
     "Can the workload scale and does it use current hardware? The checks look for older VM sizes, Standard HDD "
     "disks, accelerated networking turned off, legacy storage and App Service tiers, and compute with no "
     "autoscale."),
]

# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

# Advisor score is held per subscription, so the workload filter does not apply to it.
ADVISOR_SCORE_Q = r"""
advisorresources
| where type =~ 'microsoft.advisor/advisorscore'
| extend Pillar = case(name =~ 'Advisor', 'Advisor score', name =~ 'HighAvailability', 'Reliability',
        name =~ 'Cost', 'Cost Optimization', name =~ 'OperationalExcellence', 'Operational Excellence',
        name =~ 'Performance', 'Performance Efficiency', name),
    Score = todouble(properties.lastRefreshedScore.score)
| where isnotnull(Score)
| summarize Score = round(avg(Score), 0), Subscriptions = dcount(subscriptionId) by Pillar
| project Signal = Pillar, Value = Score, Detail = strcat('average of ', Subscriptions, ' subscriptions'),
    State = case(Score >= 80, 'Available', Score >= 60, 'Degraded', 'Unavailable'),
    Order = case(Pillar == 'Advisor score', 0, Pillar == 'Reliability', 1, Pillar == 'Security', 2,
        Pillar == 'Cost Optimization', 3, Pillar == 'Operational Excellence', 4, 5)
| order by Order asc
| project-away Order
"""


def pillar_tile_q(name, checks):
    return findings(checks) + f"""| summarize Findings = count(), High = countif(Severity == 'High'), Resources = dcount(id)
| extend k = 1
| join kind=leftouter (
    {ADVISOR.strip().replace(chr(10), chr(10) + '    ')}
    | where Pillar == '{name}'
    | summarize Advisor = count(), AdvisorHigh = countif(Impact =~ 'High')
    | extend k = 1
  ) on k
| extend Advisor = coalesce(Advisor, 0), AdvisorHigh = coalesce(AdvisorHigh, 0)
| project Signal = '{name}', Value = Findings + Advisor,
    Detail = strcat(High + AdvisorHigh, ' high · ', Advisor, ' from Advisor'),
    State = case(High + AdvisorHigh > 0, 'Unavailable', Findings + Advisor > 0, 'Degraded', 'Available')
"""


ADVISOR_BY_PILLAR_Q = ADVISOR + """| summarize High = countif(Impact =~ 'High'), Medium = countif(Impact =~ 'Medium'),
    Low = countif(Impact =~ 'Low') by Pillar
| order by Pillar asc
"""

OVERVIEW_NOTE = """\
**How to use this.** Pick the workload at the top (the **Workload tag** names the tag that identifies one), then
work through the pillar tabs. Each pillar tile counts the configuration checks that fail plus Azure Advisor's
recommendations for that pillar; red means at least one is high severity. *Advisor score* is Microsoft's own
0-100 score per pillar, averaged across the selected subscriptions; it is not narrowed to the workload. The checks
here are the settings a reviewer would otherwise open each resource to find. Pick a **Log Analytics workspace**
to add what only logs show (heartbeats, failed requests, refused access, resources sending no logs, ingestion, CPU
and memory). Design, process and recovery testing are not in any setting: answer them on the **Assessment** tab,
which follows the same checklist as the
[Azure Well-Architected Review](https://learn.microsoft.com/assessments/azure-architecture-review/)."""

# ---------------------------------------------------------------------------
# Extra panels per pillar
# ---------------------------------------------------------------------------

_VM_WHERE = "| where type =~ 'microsoft.compute/virtualmachines'\n"
assert VM_PROTECTION.count(_VM_WHERE) == 1
BACKUP_Q = VM_PROTECTION.replace(_VM_WHERE, _VM_WHERE + SCOPE + "\n") + """
| where Protection == 'Not protected' and isempty(Replication)
| project id, OS, Power, ResourceGroup, Location
| order by ResourceGroup asc
"""

HEALTH_Q = r"""
healthresources
| where type =~ 'microsoft.resourcehealth/availabilitystatuses'
| extend State = tostring(properties.availabilityState)
| where State in~ ('Unavailable', 'Degraded')
| extend rid = tostring(split(tolower(id), '/providers/microsoft.resourcehealth/')[0])
""" + in_workload("rid") + """| project id = rid, State, Reason = tostring(properties.reasonType), Summary = tostring(properties.summary),
    Since = todatetime(coalesce(tostring(properties.occurredTime), tostring(properties.occuredTime)))
| order by case(State =~ 'Unavailable', 0, 1) asc, Since asc
"""

DEFENDER_Q = r"""
securityresources
| where type =~ 'microsoft.security/assessments'
| where tostring(properties.status.code) =~ 'Unhealthy'
| extend rid = tolower(tostring(properties.resourceDetails.Id)), Severity = tostring(properties.metadata.severity)
""" + in_workload("rid") + """| summarize Resources = dcount(rid) by Recommendation = tostring(properties.displayName), Severity
| order by case(Severity =~ 'High', 0, Severity =~ 'Medium', 1, 2) asc, Resources desc
"""

SECURE_SCORE_Q = r"""
securityresources
| where type =~ 'microsoft.security/securescores'
| project subscriptionId, ScorePct = round(100 * toreal(properties.score.percentage), 0)
""" + SUBSCRIPTION_NAMES + """| project Subscription = coalesce(Subscription, subscriptionId), ScorePct
| order by ScorePct asc
"""

AGENTS_Q = machine_agents(SCOPE) + """| project id, Agent, Kind, OS, Power, ResourceGroup
| order by case(Agent == 'Azure Monitor Agent', 1, 0) asc, Agent asc, ResourceGroup asc
"""

PATCH_Q = r"""
resources
| where type in~ ('microsoft.compute/virtualmachines', 'microsoft.hybridcompute/machines')
""" + SCOPE + r"""
| project id = tolower(id), ResourceGroup = resourceGroup
| join kind=leftouter (
    patchassessmentresources
    | where type in~ ('microsoft.compute/virtualmachines/patchassessmentresults', 'microsoft.hybridcompute/machines/patchassessmentresults')
    | project id = tostring(split(tolower(id), '/patchassessmentresults/')[0]),
        Assessed = todatetime(properties.lastModifiedDateTime),
        Critical = coalesce(toint(properties.availablePatchCountByClassification.critical), 0),
        Security = coalesce(toint(properties.availablePatchCountByClassification.security), 0),
        RebootPending = tostring(properties.rebootPending)
  ) on id
| extend Status = case(isnull(Assessed), 'Not assessed', Assessed < ago(7d), 'Stale', Critical + Security > 0, 'Updates due', 'Up to date')
| project id, Status, Critical, Security, RebootPending, Assessed, ResourceGroup
| order by case(Status == 'Up to date', 1, 0) asc, Critical desc, Security desc
"""

CHANGES = r"""
resourcechanges
| extend rid = tolower(tostring(properties.targetResourceId)), ChangeType = tostring(properties.changeType),
    Client = tostring(properties.changeAttributes.clientType), ChangedBy = tostring(properties.changeAttributes.changedBy),
    Time = todatetime(properties.changeAttributes.timestamp)
| where ChangeType != 'Update' or tostring(properties.changes) contains '"changeCategory":"User"'
| extend Client = iff(isempty(Client) or Client =~ 'Unspecified', '(not recorded)', Client)
""" + in_workload("rid")

CHANGE_CLIENTS_Q = CHANGES + "| summarize Changes = count() by Client\n| top 8 by Changes desc\n"

PORTAL_CHANGES_Q = CHANGES + """| where Client has 'portal'
| project Time, id = rid, ChangeType, ChangedBy
| order by Time desc
"""

RETIREMENTS_Q = ADVISOR + r"""| where tostring(properties.extendedProperties.recommendationSubCategory) =~ 'ServiceUpgradeAndRetirement'
| extend Retires = todatetime(properties.extendedProperties.retirementDate),
    Retiring = coalesce(tostring(properties.extendedProperties.retirementFeatureName), Problem)
| summarize Resources = dcount(rid) by Retiring, Retires, Action = Solution
| project Retiring, RetirementDate = Retires, DaysLeft = datetime_diff('day', Retires, now()), Resources, Action
| order by RetirementDate asc
"""

# Compute that can scale out: scale sets (not the ones AKS manages, which its cluster autoscaler scales) and App
# Service plans on tiers that support autoscale.
AUTOSCALE_Q = r"""
resources
| where type in~ ('microsoft.compute/virtualmachinescalesets', 'microsoft.web/serverfarms')
""" + SCOPE + r"""
| where (type =~ 'microsoft.compute/virtualmachinescalesets' and not(tostring(tags) contains 'aks-managed'))
    or tolower(tostring(sku.tier)) in ('standard', 'premium', 'premiumv2', 'premiumv3', 'premium0v3', 'premiummv3', 'isolatedv2')
| project id = tolower(id), Kind = iff(type =~ 'microsoft.web/serverfarms', 'App Service plan', 'Scale set'),
    Sku = tostring(sku.name), Instances = toint(sku.capacity), Elastic = tobool(properties.elasticScaleEnabled),
    ResourceGroup = resourceGroup
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.insights/autoscalesettings'
    | project id = tolower(tostring(properties.targetResourceUri)), Enabled = tobool(properties.enabled),
        Min = toint(properties.profiles[0].capacity.minimum), Max = toint(properties.profiles[0].capacity.maximum)
  ) on id
| extend Autoscale = case(Elastic == true, 'Automatic scaling', isnull(Enabled), 'None', Enabled, 'On', 'Off')
| project id, Autoscale, Kind, Sku, Instances, Min, Max, ResourceGroup
| order by case(Autoscale in ('On', 'Automatic scaling'), 1, 0) asc, Kind asc
"""

# Alerts and security alerts held in Resource Graph: 30 days of each.
FIRED_ALERTS_Q = r"""
alertsmanagementresources
| where type =~ 'microsoft.alertsmanagement/alerts'
| extend e = properties.essentials
| extend rid = tolower(tostring(e.targetResource)), FiredAt = todatetime(e.startDateTime)
| where FiredAt > ago(30d)
""" + in_workload("rid") + """| summarize Fired = count(), Open = countif(tostring(e.monitorCondition) =~ 'Fired'), Resources = dcount(rid),
    Last = max(FiredAt) by Alert = name, Severity = tostring(e.severity)
| order by Fired desc
| take 200
"""

DEFENDER_ALERTS_Q = r"""
securityresources
| where type =~ 'microsoft.security/locations/alerts'
| extend rid = tolower(tostring(properties.resourceIdentifiers[0].azureResourceId)),
    Time = todatetime(properties.timeGeneratedUtc)
| where Time > ago(30d)
""" + in_workload("rid") + """| project Time, Severity = tostring(properties.severity), Alert = tostring(properties.alertDisplayName), id = rid,
    Status = tostring(properties.status)
| order by Time desc
| take 500
"""

# ---------------------------------------------------------------------------
# Log Analytics: shown once a workspace is picked. Logs carry no tags, so a hidden parameter holds the ids of the
# workload's resources (only the types the panels below read, to keep it short) and each query keeps the rows whose
# resource is in it. Rows are matched on the top-level resource (the first nine segments of the id), so a storage
# account's blob service or a SQL server's databases count as the account or the server. With every workload
# selected the list is empty and nothing is filtered.
# ---------------------------------------------------------------------------

MACHINE_TYPES = ["microsoft.compute/virtualmachines", "microsoft.hybridcompute/machines"]
LOGGABLE_TYPES = [
    "microsoft.apimanagement/service", "microsoft.app/managedenvironments", "microsoft.appconfiguration/configurationstores",
    "microsoft.cache/redis", "microsoft.cdn/profiles", "microsoft.cognitiveservices/accounts",
    "microsoft.containerregistry/registries", "microsoft.containerservice/managedclusters",
    "microsoft.datafactory/factories", "microsoft.dbformysql/flexibleservers", "microsoft.dbforpostgresql/flexibleservers",
    "microsoft.documentdb/databaseaccounts", "microsoft.eventgrid/topics", "microsoft.eventhub/namespaces",
    "microsoft.insights/components", "microsoft.keyvault/vaults", "microsoft.logic/workflows",
    "microsoft.network/applicationgateways", "microsoft.network/azurefirewalls", "microsoft.network/bastionhosts",
    "microsoft.network/frontdoors", "microsoft.network/virtualnetworkgateways", "microsoft.recoveryservices/vaults",
    "microsoft.search/searchservices", "microsoft.servicebus/namespaces", "microsoft.signalrservice/signalr",
    "microsoft.sql/servers", "microsoft.storage/storageaccounts", "microsoft.web/sites",
]

WORKLOAD_IDS_Q = f"""
resources
| where not('*' in ({{Workload}}))
| where tostring(tags['{{WorkloadTag}}']) in ({{Workload}})
| where type in~ ({", ".join(f"'{t}'" for t in MACHINE_TYPES + LOGGABLE_TYPES)})
| project value = tolower(id), label = name
"""

TOP_ID = "strcat_array(array_slice(split(tolower(_ResourceId), '/'), 0, 8), '/')"
LA_SCOPE = "| where '*' in ({Workload}) or set_has_element(dynamic([{WorkloadIds}]), rid)"
WORKLOAD_LIST = """print rid = dynamic([{WorkloadIds}])
| mv-expand rid to typeof(string)
| where isnotempty(rid)"""
IS_MACHINE = "(rid contains '/microsoft.compute/virtualmachines/' or rid contains '/microsoft.hybridcompute/machines/')"

# Hours with at least one heartbeat, against the hours in the range since the machine was first seen. Machines of
# the workload that sent nothing at all show at 0%.
HEARTBEAT_Q = f"""let Start = todatetime('{{TimeRange:startISO}}');
let End = min_of(now(), todatetime('{{TimeRange:endISO}}'));
let Beats = Heartbeat
    | where isnotempty(_ResourceId)
    | extend rid = {TOP_ID}
    {LA_SCOPE}
    | summarize by rid, Computer, Hour = bin(TimeGenerated, 1h)
    | summarize Hours = count(), First = min(Hour), LastSeen = max(Hour) by rid, Computer;
let Machines = {WORKLOAD_LIST.replace(chr(10), chr(10) + '    ')}
    | where {IS_MACHINE};
Machines
| join kind=fullouter Beats on rid
| extend id = coalesce(rid1, rid), Hours = coalesce(Hours, 0)
| extend Expected = max_of(1, datetime_diff('hour', End, max_of(Start, coalesce(First, Start))))
| project id, Computer, Availability = round(min_of(100.0, 100.0 * Hours / Expected), 1), Hours, Expected, LastSeen
| order by Availability asc
"""

APP_REQUESTS_Q = f"""AppRequests
| extend rid = {TOP_ID}
{LA_SCOPE}
| summarize Requests = sum(ItemCount), Failed = sumif(ItemCount, Success == false),
    P95 = percentile(DurationMs, 95) by id = rid, App = AppRoleName
| project id, App, Requests, Failed, FailedPct = round(100.0 * Failed / Requests, 2), P95Ms = round(P95)
| order by FailedPct desc, Requests desc
"""

# Forbidden (403) only: a Key Vault client's first call answers 401 by design, to ask for a token.
DENIED_Q = f"""union isfuzzy=true
    (datatable(TimeGenerated: datetime, _ResourceId: string, Status: int, Caller: string, Operation: string)[]),
    (AZKVAuditLogs
    | where HttpStatusCode == 403
    | project TimeGenerated, _ResourceId, Status = toint(HttpStatusCode), Caller = CallerIpAddress, Operation = OperationName),
    (AzureDiagnostics
    | where ResourceProvider == 'MICROSOFT.KEYVAULT'
    | where toint(column_ifexists('httpStatusCode_d', real(null))) == 403
    | project TimeGenerated, _ResourceId, Status = 403, Caller = tostring(column_ifexists('CallerIPAddress', '')),
        Operation = OperationName),
    (StorageBlobLogs
    | where StatusCode == 403
    | project TimeGenerated, _ResourceId, Status = toint(StatusCode), Caller = tostring(split(CallerIpAddress, ':')[0]),
        Operation = OperationName)
| extend rid = {TOP_ID}
{LA_SCOPE}
| summarize Denied = count(), Callers = dcount(Caller), Last = max(TimeGenerated) by id = rid, Operation
| order by Denied desc
| take 200
"""

# Every table, for a day: which of the workload's resources wrote anything at all (resource logs, metrics sent by a
# diagnostic setting, or agent data from a machine).
NO_LOGS_Q = f"""let Logged = union *
    | where TimeGenerated > ago(1d)
    | where isnotempty(_ResourceId)
    | summarize by rid = {TOP_ID};
{WORKLOAD_LIST}
| join kind=leftanti Logged on rid
| project id = rid, Type = extract(@'/providers/([^/]+/[^/]+)/', 1, rid)
| order by Type asc, id asc
"""

INGESTION_Q = f"""let ByTable = union withsource=WafSourceTable_ *
    | where _IsBillable == true and isnotempty(_ResourceId)
    | extend rid = {TOP_ID}
    {LA_SCOPE}
    | summarize GB = sum(_BilledSize) / 1e9 by rid, Table = WafSourceTable_;
ByTable
| summarize TotalGB = round(sum(GB), 2), Tables = count() by rid
| join kind=inner (ByTable | summarize arg_max(GB, Table) by rid) on rid
| project id = rid, TotalGB, LargestTable = Table, LargestGB = round(GB, 2), Tables
| order by TotalGB desc
| take 200
"""

# CPU and memory from the performance counters (Perf) or VM insights (InsightsMetrics), whichever the machine sends.
SIZING_Q = f"""union isfuzzy=true
    (datatable(TimeGenerated: datetime, _ResourceId: string, Metric: string, Value: real)[]),
    (Perf
    | where ObjectName in ('Processor', 'Processor Information') and CounterName == '% Processor Time'
        and InstanceName in ('_Total', 'total')
    | project TimeGenerated, _ResourceId, Metric = 'Cpu', Value = CounterValue),
    (Perf
    | where ObjectName == 'Memory' and CounterName in ('% Committed Bytes In Use', '% Used Memory')
    | project TimeGenerated, _ResourceId, Metric = 'Memory', Value = CounterValue),
    (InsightsMetrics
    | where Namespace == 'Processor' and Name == 'UtilizationPercentage'
    | project TimeGenerated, _ResourceId, Metric = 'Cpu', Value = Val),
    (InsightsMetrics
    | where Namespace == 'Memory' and Name == 'AvailableMB'
    | extend Total = todouble(parse_json(Tags)['vm.azm.ms/memorySizeMB'])
    | where Total > 0
    | project TimeGenerated, _ResourceId, Metric = 'Memory', Value = 100.0 * (1 - Val / Total))
| where isnotempty(_ResourceId)
| extend rid = {TOP_ID}
{LA_SCOPE}
| summarize CpuAvg = round(avgif(Value, Metric == 'Cpu'), 1),
    CpuP95 = round(percentile(iff(Metric == 'Cpu', Value, real(null)), 95), 1),
    MemoryP95 = round(percentile(iff(Metric == 'Memory', Value, real(null)), 95), 1) by id = rid
| extend Fit = case(CpuP95 > 85 or MemoryP95 > 90, 'Under pressure',
    CpuP95 < 20 and (isnull(MemoryP95) or MemoryP95 < 50), 'Possibly oversized', 'Within range')
| project id, Fit, CpuAvg, CpuP95, MemoryP95
| order by case(Fit == 'Within range', 1, 0) asc, CpuP95 desc
"""

NO_WORKSPACE = ("Pick a **Log Analytics workspace** at the top to add the checks only logs can answer on this tab. "
                "They read the workspace the workload sends its logs to; pick several if its logs are split.")


def la_note(key):
    return text(f"{P}-{key}-la-note", NO_WORKSPACE, "info", visible_when=WORKSPACE_UNSET)


# ---------------------------------------------------------------------------
# Workloads: every workload's findings side by side. Each check is reduced to a two-letter code (pillar, severity)
# to keep the query short enough for Resource Graph.
# ---------------------------------------------------------------------------

PILLAR_CODES = {"Reliability": "R", "Security": "S", "Cost Optimization": "C", "Operational Excellence": "O",
                "Performance Efficiency": "P"}


def workload_summary_q():
    checks = [(PILLAR_CODES[name] + c[3][0], c) for _, name, cs, _ in PILLARS for c in cs]
    types = ", ".join(f"'{t}'" for t in sorted({c[0] for _, c in checks}))
    flags = ",\n    ".join(f"iff(type =~ '{c[0]}' and ({c[1]}), '{code}', '')" for code, c in checks)
    counts = ", ".join(f"{name.split()[0]} = countif(f startswith '{code}')" for name, code in PILLAR_CODES.items())
    return f"""
resources
{SCOPE}
| extend Workload = tostring(tags['{{WorkloadTag}}'])
| extend Workload = iff(isempty(Workload), '(untagged)', Workload)
| summarize TotalResources = count() by Workload
| join kind=leftouter (
    resources
    | where type in~ ({types})
    {SCOPE}
    | extend Workload = tostring(tags['{{WorkloadTag}}'])
    | extend Workload = iff(isempty(Workload), '(untagged)', Workload)
    | extend F = pack_array(
    {flags})
    | mv-expand f = F
    | extend f = tostring(f)
    | where isnotempty(f)
    | summarize Findings = count(), High = countif(f endswith 'H'), Affected = dcount(id), {counts} by Workload
  ) on Workload
| join kind=leftouter (
    {ADVISOR_RECS.strip().replace(chr(10), chr(10) + '    ')}
    | join kind=inner (resources | project rid = tolower(id), Workload = tostring(tags['{{WorkloadTag}}'])) on rid
    | extend Workload = iff(isempty(Workload), '(untagged)', Workload)
    | summarize Advisor = count(), AdvisorHigh = countif(Impact =~ 'High') by Workload
  ) on Workload
| project Workload, TotalResources, Affected = coalesce(Affected, 0), Findings = coalesce(Findings, 0),
    High = coalesce(High, 0), {", ".join(f"{n.split()[0]} = coalesce({n.split()[0]}, 0)" for n in PILLAR_CODES)},
    Advisor = coalesce(Advisor, 0), AdvisorHigh = coalesce(AdvisorHigh, 0)
| order by High desc, Findings desc
"""


# ---------------------------------------------------------------------------
# Assessment: the Well-Architected checklist for each pillar, answered by the reviewer. Each answer is a parameter,
# so it is kept when the workbook is saved. (code, short label, question, where this workbook has evidence for it)
# Questions go into KQL strings, so they must not contain a single quote.
# ---------------------------------------------------------------------------

CHECKLIST_URL = "https://learn.microsoft.com/azure/well-architected/{}/checklist"

QUESTIONS = {
    "Reliability": ("reliability", [
        ("RE01", "Simplicity", "Is the design kept as simple as the business requirements allow, with nothing that does not add value?", ""),
        ("RE02", "Critical flows", "Have the user and system flows been identified and rated by how critical they are?", ""),
        ("RE03", "Failure modes", "Has a failure mode analysis been done for each critical flow and its dependencies?", ""),
        ("RE04", "Targets", "Are availability and recovery targets (SLO, RTO, RPO) defined and agreed with the business?",
         "Monthly availability report workbook"),
        ("RE05", "Redundancy", "Is there redundancy at every layer, across availability zones and, where the targets need it, regions?",
         "Reliability tab: zone and single-instance checks"),
        ("RE06", "Scaling", "Does the workload scale in time to meet demand, automatically where it can?",
         "Performance Efficiency tab: autoscale"),
        ("RE07", "Self-healing", "Do components cope with transient faults and failed dependencies (retries, timeouts, circuit breakers, queues)?",
         "Reliability tab: request failures"),
        ("RE08", "Resilience testing", "Is resilience tested, for example with fault injection or Azure Chaos Studio?", ""),
        ("RE09", "Disaster recovery", "Is there a documented disaster recovery plan, with restores and failover tested against the targets?",
         "Reliability tab: backup; Backup and Recovery workbook"),
        ("RE10", "Health model", "Is health measured and modelled, with alerts on the signals that show the workload is degraded?",
         "Reliability tab: Resource Health and heartbeats"),
    ]),
    "Security": ("security", [
        ("SE01", "Baseline", "Is there a security baseline for the workload, aligned to its compliance requirements?",
         "Azure Policy compliance workbook"),
        ("SE02", "Secure development", "Is software built through a secure development lifecycle, with dependencies and the supply chain checked?", ""),
        ("SE03", "Data classification", "Is the data the workload handles classified and labelled by sensitivity?", ""),
        ("SE04", "Segmentation", "Is the workload segmented, with deliberate boundaries between components and environments?", ""),
        ("SE05", "Identity and access", "Is access granted to identities with least privilege, conditional access and an audit trail, rather than by keys?",
         "Security tab: local authentication checks; Privileged access workbook"),
        ("SE06", "Network controls", "Is network traffic isolated and filtered, with private endpoints for data services?",
         "Security tab: public network access checks"),
        ("SE07", "Encryption", "Is data encrypted in transit and at rest with current standards (TLS 1.2 or later)?",
         "Security tab: TLS and HTTP checks"),
        ("SE08", "Hardening", "Are components hardened, with unused features, ports and accounts removed?",
         "Security tab: Defender for Cloud recommendations"),
        ("SE09", "Secrets", "Are secrets, keys and certificates kept in Key Vault, rotated, and never in code or configuration?",
         "Expiry workbook"),
        ("SE10", "Threat detection", "Is the workload monitored for threats, with alerts going to people who respond?",
         "Security tab: Defender alerts and denied access"),
        ("SE11", "Security testing", "Is the workload tested for security (penetration tests, code scanning) on a schedule?", ""),
        ("SE12", "Incident response", "Is there a tested incident response plan for a security breach of this workload?", ""),
    ]),
    "Cost Optimization": ("cost-optimization", [
        ("CO01", "Accountability", "Does the team know what the workload costs and who is accountable for it?", ""),
        ("CO02", "Cost model", "Is there a cost model that estimates cost from expected usage and growth?", ""),
        ("CO03", "Cost data", "Is cost data collected, tagged by workload and reviewed regularly?", "FinOps hubs workbook"),
        ("CO04", "Guardrails", "Are there budgets, alerts and policies that catch unexpected spend?", ""),
        ("CO05", "Best rates", "Are the best rates in use: reservations, savings plans, Azure Hybrid Benefit, dev/test pricing?",
         "Cost Optimization tab: Advisor and licence checks"),
        ("CO06", "Billing increments", "Is usage aligned to how each service bills (instance sizes, hourly units, tiers)?", ""),
        ("CO07", "Component costs", "Are idle or oversized components removed or resized?",
         "Cost Optimization tab: idle resources; Performance Efficiency tab: CPU and memory"),
        ("CO08", "Environment costs", "Do non-production environments cost less than production (smaller sizes, shut down out of hours)?", ""),
        ("CO09", "Flow costs", "Is spending prioritised by the business value of each flow?", ""),
        ("CO10", "Data costs", "Are storage tiers, retention and log ingestion matched to how the data is used?",
         "Cost Optimization tab: workspace retention and log ingestion"),
        ("CO11", "Code costs", "Is code efficient in the resources it uses (calls, compute, data transfer)?", ""),
        ("CO12", "Scaling costs", "Does capacity scale in as readily as it scales out, so it follows demand?", ""),
        ("CO13", "Personnel time", "Is the time people spend running the workload measured and reduced?", ""),
        ("CO14", "Consolidation", "Are resources and responsibilities consolidated where that lowers cost without adding risk?", ""),
    ]),
    "Operational Excellence": ("operational-excellence", [
        ("OE01", "Team and culture", "Does the team have clear roles, shared standards and a habit of learning from incidents?", ""),
        ("OE02", "Operational tasks", "Are routine, as-needed and emergency operational tasks documented and repeatable?", ""),
        ("OE03", "Planning", "Is new work planned, prioritised and tracked in a backlog?", ""),
        ("OE04", "Quality", "Are development and testing standardised, with automated tests in the delivery pipeline?", ""),
        ("OE05", "Infrastructure as code", "Is all infrastructure deployed from code kept in source control?",
         "Operational Excellence tab: changes made in the portal"),
        ("OE06", "Pipelines", "Do all changes go through a pipeline, with the same steps for every environment?",
         "Operational Excellence tab: changes by tool"),
        ("OE07", "Monitoring", "Is there a monitoring system with logs, metrics and alerts for every component?",
         "Operational Excellence tab: agents, resources sending no logs, alerts fired"),
        ("OE08", "Incident management", "Is there a structured incident process, with on-call, runbooks and post-incident reviews?", ""),
        ("OE09", "Automation", "Are repetitive tasks (patching, scaling, certificate renewal) automated?",
         "Operational Excellence tab: patching"),
        ("OE10", "Automation by design", "Was automation designed in from the start rather than added later?", ""),
        ("OE11", "Safe deployment", "Are deployments progressive (rings, canary, blue-green) with a tested rollback?", ""),
    ]),
    "Performance Efficiency": ("performance-efficiency", [
        ("PE01", "Targets", "Are performance targets (response times, throughput) defined for the critical flows?", ""),
        ("PE02", "Capacity planning", "Is capacity planned against expected demand, including peaks and growth?", ""),
        ("PE03", "Service selection", "Were the services, SKUs and tiers chosen against the performance targets?",
         "Performance Efficiency tab: older sizes and tiers"),
        ("PE04", "Performance data", "Is performance data collected for every component and flow?",
         "Performance Efficiency tab: CPU and memory; Reliability tab: response times"),
        ("PE05", "Scaling and partitioning", "Can the workload scale out, and partition its data, where load requires?",
         "Performance Efficiency tab: autoscale"),
        ("PE06", "Performance testing", "Is performance tested (load and stress tests) before release?", ""),
        ("PE07", "Code and infrastructure", "Are code and infrastructure tuned for performance, on current hardware?",
         "Performance Efficiency tab: configuration checks"),
        ("PE08", "Data performance", "Is data access optimised (indexing, caching, partitioning)?", ""),
        ("PE09", "Critical flows", "Do the critical flows get priority for capacity and performance?", ""),
        ("PE10", "Operational tasks", "Are operational tasks (backups, scans, deployments) timed so they do not slow the workload?", ""),
        ("PE11", "Live issues", "Is there a process to find and fix performance problems in production?", ""),
        ("PE12", "Continuous improvement", "Is performance reviewed and improved continuously, not only when it fails?", ""),
    ]),
}

for _, _qs in QUESTIONS.values():
    for _q in _qs:
        assert "'" not in _q[2] + _q[3], _q

ANSWERS = [("yes", "Yes"), ("partly", "Partly"), ("no", "No"), ("na", "Not applicable")]
ANSWER_FMT = status_fmt("Answer", good=["Yes"], warn=["Partly"], bad=["No"], neutral=["Not applicable"])
PILLAR_ORDER = "case(Pillar == 'Reliability', 1, Pillar == 'Security', 2, Pillar == 'Cost Optimization', 3, " \
               "Pillar == 'Operational Excellence', 4, 5)"


def answers_q():
    """One row per checklist question with its answer, from the answer parameters. Resource Graph needs a table to
    start from, so the rows are expanded from a single subscription."""
    rows = ",\n    ".join(
        f"pack('Pillar', '{pillar}', 'Id', '{code[:2]}:{code[2:]}', 'Topic', '{topic}', 'Question', '{question}', "
        f"'Evidence', '{evidence}', 'Answer', '{{{code}}}')"
        for pillar, (_, qs) in QUESTIONS.items() for code, topic, question, evidence in qs)
    return f"""
resourcecontainers
| where type =~ 'microsoft.resources/subscriptions'
| take 1
| mv-expand q = pack_array(
    {rows})
| project Pillar = tostring(q.Pillar), Id = tostring(q.Id), Topic = tostring(q.Topic), Question = tostring(q.Question),
    Answer = case(tostring(q.Answer) == 'yes', 'Yes', tostring(q.Answer) == 'partly', 'Partly',
        tostring(q.Answer) == 'no', 'No', tostring(q.Answer) == 'na', 'Not applicable', 'Not answered'),
    Evidence = tostring(q.Evidence)
"""


# Yes scores 2 and Partly 1, out of 2 for every question answered other than Not applicable.
ASSESSMENT_TILES_Q = answers_q() + f"""| summarize Yes = countif(Answer == 'Yes'), Partly = countif(Answer == 'Partly'), No = countif(Answer == 'No'),
    NA = countif(Answer == 'Not applicable'), Questions = count() by Pillar
| extend Scored = Yes + Partly + No
| extend Score = iff(Scored == 0, real(null), round(100.0 * (2 * Yes + Partly) / (2 * Scored), 0))
| project Signal = Pillar, Value = Score,
    Detail = iff(Scored + NA == 0, 'not answered yet', strcat(Scored + NA, ' of ', Questions, ' answered · ', No, ' no')),
    State = case(isnull(Score), 'Unknown', Score >= 80, 'Available', Score >= 50, 'Degraded', 'Unavailable'),
    Order = {PILLAR_ORDER}
| order by Order asc
| project-away Order
"""

GAPS_Q = answers_q() + f"""| where Answer in ('No', 'Partly')
| order by case(Answer == 'No', 0, 1) asc, {PILLAR_ORDER} asc, Id asc
| project Answer, Pillar, Id, Topic, Question, Evidence
"""


def extras(key):
    if key == "reliability":
        return [
            arg(f"{P}-backup", "VMs with no backup or replication", BACKUP_Q, formatters=[resource_link()],
                labels={"id": "Virtual machine", "ResourceGroup": "Resource group"},
                no_data="Every VM is backed up or replicated."),
            arg(f"{P}-health", "Resources currently unavailable or degraded (Resource Health)", HEALTH_Q,
                formatters=[resource_link(), status_fmt("State", warn=["Degraded"], bad=["Unavailable"])],
                labels={"id": "Resource"}, no_data="Resource Health reports nothing unavailable or degraded."),
            text(f"{P}-backup-note", "Recovery is the part of reliability settings show least: the **Backup & "
                 "Recovery** workbook has failed jobs, stale backups and test failovers. Record a recovery time "
                 "and recovery point target for the workload, and test a restore against them.", "info"),
            la_note(key),
            la(f"{P}-heartbeat", "Machine availability from heartbeats (hours reporting in the time range)", HEARTBEAT_Q,
               formatters=[resource_link(), high_is_good("Availability", 99.9, 99, digits=1)],
               labels={"id": "Machine", "Availability": "Availability %", "Hours": "Hours reporting",
                       "Expected": "Hours expected", "LastSeen": "Last heartbeat"},
               no_data="No heartbeats from the workload's machines in the selected workspaces."),
            la(f"{P}-requests", "Application requests: failures and response time (Application Insights)",
               APP_REQUESTS_Q,
               formatters=[resource_link(), low_is_good("FailedPct", 1, 5, digits=2), low_is_good("P95Ms", 1000, 3000)],
               labels={"id": "Application Insights", "FailedPct": "Failed %", "P95Ms": "95th percentile ms"},
               no_data="No requests from workspace-based Application Insights in the workload."),
            text(f"{P}-heartbeat-note", "A machine is counted for the hours since it was first seen in the range, so a "
                 "new machine is not marked down for the time before it existed; a machine shut down on purpose still "
                 "counts as down. A workload machine at 0% may send its heartbeats to a workspace not selected.",
                 visible_when={"parameterName": "Workspace", "comparison": "isNotEqualTo", "value": ""}),
        ]
    if key == "security":
        return [
            arg(f"{P}-defender", "Defender for Cloud recommendations for the workload", DEFENDER_Q, width=65,
                formatters=[status_fmt("Severity", warn=["Medium"], bad=["High"], neutral=["Low"])],
                no_data="No unhealthy Defender for Cloud recommendations (or Defender is not reporting)."),
            arg(f"{P}-secure-score", "Secure score by subscription", SECURE_SCORE_Q, width=35,
                formatters=[pct_bar("ScorePct")], labels={"ScorePct": "Score %"},
                no_data="No secure score: Defender for Cloud is not reporting for the selected subscriptions."),
            arg(f"{P}-defender-alerts", "Defender for Cloud security alerts on the workload (last 30 days)",
                DEFENDER_ALERTS_Q, formatters=[resource_link(), SEVERITY_ANY],
                labels={"id": "Resource"}, no_data="No Defender for Cloud alerts on the workload in the last 30 days."),
            la_note(key),
            la(f"{P}-denied", "Requests refused to Key Vault and Storage (403 Forbidden)", DENIED_Q,
               formatters=[resource_link()], labels={"id": "Resource", "Callers": "Caller addresses"},
               no_data="No refused requests in the time range (or the vaults and accounts send no logs here)."),
        ]
    if key == "cost":
        return [
            text(f"{P}-cost-note", "Savings are Azure Advisor's own estimate for a year. The **Cloud Center of "
                 "Excellence** workbook's *Cost* tab rolls the same savings and idle resources up by "
                 "subscription.", "info"),
            la_note(key),
            when_set(group(f"{P}-ingestion-group", [
                la(f"{P}-ingestion", "Billable log ingestion by resource in the time range", INGESTION_Q,
                   formatters=[resource_link()],
                   labels={"id": "Resource", "TotalGB": "GB", "LargestTable": "Largest table",
                           "LargestGB": "Largest table GB"},
                   no_data="The workload's resources sent no billable logs to the selected workspaces."),
            ], load_button="Measure log ingestion for the workload (reads every table)"), "Workspace"),
        ]
    if key == "operations":
        return [
            arg(f"{P}-agents", "Monitoring agent on machines", AGENTS_Q, formatters=[resource_link(), AGENT_STATUS],
                labels={"id": "Machine", "ResourceGroup": "Resource group"},
                no_data="No VMs or Arc servers in the workload."),
            arg(f"{P}-patch", "Patching (Azure Update Manager)", PATCH_Q,
                formatters=[resource_link(), status_fmt("Status", good=["Up to date"], warn=["Updates due", "Stale"],
                                                        neutral=["Not assessed"])],
                labels={"id": "Machine", "RebootPending": "Reboot pending", "ResourceGroup": "Resource group"},
                no_data="No VMs or Arc servers in the workload."),
            arg(f"{P}-clients", "Changes by tool (last 14 days)", CHANGE_CLIENTS_Q, vis="piechart", width=35,
                no_data="No changes in the last 14 days."),
            arg(f"{P}-portal", "Changes made in the Azure portal (last 14 days)", PORTAL_CHANGES_Q, width=65,
                formatters=[resource_link()], labels={"id": "Resource", "ChangeType": "Change", "ChangedBy": "Changed by"},
                no_data="No changes were made in the portal in the last 14 days."),
            arg(f"{P}-retirements", "Azure retirements affecting the workload (Azure Advisor)", RETIREMENTS_Q,
                formatters=[high_is_good("DaysLeft", 90, 30)],
                labels={"RetirementDate": "Retirement date", "DaysLeft": "Days left"},
                no_data="Advisor reports no retirements for the workload."),
            arg(f"{P}-fired", "Alerts fired on the workload (last 30 days)", FIRED_ALERTS_Q,
                formatters=[SEVERITY_ANY, low_is_good("Fired", 10, 50)],
                labels={"Open": "Still firing"},
                no_data="No alerts fired on the workload in the last 30 days."),
            text(f"{P}-fired-note", "An alert that fires often and is never acted on trains people to ignore alerts: "
                 "tune its threshold, or remove it. A workload with no alerts at all may simply have none set up.",
                 "info"),
            la_note(key),
            when_set(group(f"{P}-nologs-group", [
                text(f"{P}-nologs-intro", "Diagnostic settings are not in Resource Graph, so this looks at the "
                     "workspaces instead: the workload's resources (of the types that can send resource logs, and its "
                     "machines) that wrote nothing to any selected workspace in the last day. It needs a workload "
                     "picked at the top: with *All* there is no list to compare against."),
                la(f"{P}-nologs", "Workload resources that sent nothing to the selected workspaces (last 24 hours)",
                   NO_LOGS_Q, time=False, formatters=[resource_link()], labels={"id": "Resource"},
                   no_data="Every resource of the workload sent logs, or no single workload is picked."),
            ], load_button="Find resources sending no logs (reads every table)"), "Workspace"),
        ]
    if key == "performance":
        return [
            arg(f"{P}-autoscale", "Autoscale on scale sets and App Service plans", AUTOSCALE_Q,
                formatters=[resource_link(), status_fmt("Autoscale", good=["On", "Automatic scaling"],
                                                        warn=["None", "Off"])],
                labels={"id": "Resource", "ResourceGroup": "Resource group"},
                no_data="No scale sets or App Service plans that can autoscale in the workload."),
            la_note(key),
            la(f"{P}-sizing", "Machine CPU and memory in the time range (right-sizing)", SIZING_Q,
               formatters=[resource_link(), status_fmt("Fit", good=["Within range"], warn=["Possibly oversized"],
                                                       bad=["Under pressure"]),
                           low_is_good("CpuP95", 70, 85, digits=1), low_is_good("MemoryP95", 80, 90, digits=1)],
               labels={"id": "Machine", "CpuAvg": "CPU average %", "CpuP95": "CPU 95th percentile %",
                       "MemoryP95": "Memory used 95th percentile %"},
               no_data="No CPU or memory counters from the workload's machines in the selected workspaces."),
            text(f"{P}-sizing-note", "*Possibly oversized* is a 95th percentile CPU under 20% with memory under 50%: "
                 "check the busiest period of the month before resizing. Memory on Windows is committed bytes in use.",
                 visible_when={"parameterName": "Workspace", "comparison": "isNotEqualTo", "value": ""}),
        ]
    return []


# ---------------------------------------------------------------------------
# Parameters and tabs
# ---------------------------------------------------------------------------

TABS = ([("overview", "Overview"), ("workloads", "Workloads")] + [(key, name) for key, name, _, _ in PILLARS]
        + [("assessment", "Assessment")])


def workload_param():
    return {
        "id": gid(f"{P}-param-Workload"), "version": "KqlParameterItem/1.0", "name": "Workload", "label": "Workload",
        "type": 2, "isRequired": True, "multiSelect": True, "quote": "'", "delimiter": ",",
        "query": WORKLOAD_Q.strip(), "crossComponentResources": ["{Subscription}"],
        "typeSettings": {"additionalResourceOptions": ["value::all"], "selectAllValue": "*", "showDefault": False},
        "defaultValue": "value::all", "value": ["value::all"],
        "queryType": 1, "resourceType": "microsoft.resourcegraph/resources",
        "description": "The workloads to review, from the values of the workload tag. All includes untagged resources.",
    }


def global_params():
    return params(f"{P}-params", [
        subscription_param(P),
        free_text_param(P, "WorkloadTag", "Workload tag",
                        "The tag whose value names the workload a resource belongs to. Tag names here match case.",
                        "workload"),
        workload_param(),
        workspace_param(P, "Optional. The workspaces the workload sends its logs to. Adds the checks only logs can "
                           "answer: heartbeats, request failures, refused access, resources sending no logs, "
                           "ingestion, and CPU and memory."),
        time_param(P, 7 * DAY_MS, (DAY_MS, 3 * DAY_MS, 7 * DAY_MS, 14 * DAY_MS, 30 * DAY_MS),
                   "The period the log-based panels cover. The Resource Graph panels show the current state."),
        {"id": gid(f"{P}-param-WorkloadIds"), "version": "KqlParameterItem/1.0", "name": "WorkloadIds",
         "type": 2, "isRequired": False, "multiSelect": True, "quote": "'", "delimiter": ",",
         "query": WORKLOAD_IDS_Q.strip(), "crossComponentResources": ["{Subscription}"],
         "typeSettings": {"additionalResourceOptions": ["value::all"], "showDefault": False},
         "defaultValue": "value::all", "value": ["value::all"], "isHiddenWhenLocked": True,
         "queryType": 1, "resourceType": "microsoft.resourcegraph/resources"},
        {"id": gid(f"{P}-param-selectedTab"), "version": "KqlParameterItem/1.0", "name": "selectedTab", "type": 1,
         "value": "overview", "isHiddenWhenLocked": True},
    ])


def tabs():
    return {"type": 11, "content": {"version": "LinkItem/1.0", "style": "tabs", "links": [
        {"id": gid(f"{P}-tab-" + key), "cellValue": "selectedTab", "linkTarget": "parameter",
         "linkLabel": label, "subTarget": key, "style": "link"} for key, label in TABS
    ]}, "name": f"{P}-tabs"}


def overview_tab():
    return group(f"{P}-tab-overview", [
        text(f"{P}-pillars-h", "### Pillars"),
        *[arg(f"{P}-tile-{key}", "", pillar_tile_q(name, checks), vis="tiles", tiles=TILES, fixed_px=ONE_TILE)
          for key, name, checks, _ in PILLARS],
        text(f"{P}-score-h", "### Advisor score"),
        arg(f"{P}-advisor-score", "", ADVISOR_SCORE_Q, vis="tiles", tiles=TILES,
            no_data="Advisor score is not available for the selected subscriptions."),
        text(f"{P}-self-h", "### Self-assessment score\nFrom the answers on the **Assessment** tab: Yes scores 2, "
             "Partly 1 and No 0, out of every question answered other than Not applicable."),
        arg(f"{P}-self-score", "", ASSESSMENT_TILES_Q, vis="tiles", tiles=PCT_TILES),
        text(f"{P}-overview-note", OVERVIEW_NOTE, "info"),
        arg(f"{P}-advisor-pillars", "Azure Advisor recommendations by pillar and impact", ADVISOR_BY_PILLAR_Q,
            vis="barchart",
            chart={"seriesLabelSettings": [{"seriesName": "High", "color": "redBright"},
                                           {"seriesName": "Medium", "color": "orange"},
                                           {"seriesName": "Low", "color": "blue"}]},
            no_data="Advisor has no recommendations for the workload."),
    ], tab="overview")


def pillar_tab(key, name, checks, intro):
    rec_param = f"{key.capitalize()}Rec"
    found = findings(checks)
    advisor = ADVISOR + f"| where Pillar == '{name}'\n"
    savings = ", Savings = round(sum(Savings), 0), Currency = take_anyif(Currency, isnotempty(Currency))" if key == "cost" else ""
    savings_cols = ", Savings, Currency" if key == "cost" else ""
    tiles_q = found + f"""| summarize High = countif(Severity == 'High'), Medium = countif(Severity == 'Medium'),
    Low = countif(Severity == 'Low'), Resources = dcount(id), Checks = dcount(Finding)
| extend rows = pack_array(
    pack('Signal', 'High severity', 'Value', High, 'Detail', 'findings', 'State', iff(High > 0, 'Unavailable', 'Available')),
    pack('Signal', 'Medium severity', 'Value', Medium, 'Detail', 'findings', 'State', iff(Medium > 0, 'Degraded', 'Available')),
    pack('Signal', 'Low severity', 'Value', Low, 'Detail', 'findings', 'State', iff(Low > 0, 'Degraded', 'Available')),
    pack('Signal', 'Resources affected', 'Value', Resources, 'Detail', strcat('failing ', Checks, ' of {len({c[2] for c in checks})} checks'),
        'State', iff(Resources > 0, 'Degraded', 'Available')))
| mv-expand r = rows
| project Signal = tostring(r.Signal), Value = toint(r.Value), Detail = tostring(r.Detail), State = tostring(r.State)
"""
    advisor_tile_q = advisor + """| summarize Recs = count(), High = countif(Impact =~ 'High'), Resources = dcount(rid)
| project Signal = 'Advisor recommendations', Value = Recs, Detail = strcat(High, ' high impact · ', Resources, ' resources'),
    State = case(High > 0, 'Unavailable', Recs > 0, 'Degraded', 'Available')
"""
    advisor_q = advisor + f"""| summarize Resources = dcount(rid){savings} by RecType, Problem, Solution, Impact
| project Recommendation = Problem, Impact, Resources{savings_cols}, Action = Solution, RecType
| order by case(Impact =~ 'High', 0, Impact =~ 'Medium', 1, 2) asc, Resources desc
"""
    advisor_detail_q = advisor + f"""| where RecType == '{{{rec_param}}}'
{SUBSCRIPTION_NAMES.strip()}
| project id = rid, Impact, Subscription = coalesce(Subscription, subscriptionId),
    Updated = todatetime(properties.lastUpdated)
| order by id asc
"""
    summary_q = found + f"""| summarize Resources = dcount(id), Types = strcat_array(make_set(Type, 5), ', ') by Finding, Severity, Fix
| project Severity, Finding, Resources, Fix, Types
| order by {SEVERITY_ORDER} asc, Resources desc
"""
    list_q = found + SUBSCRIPTION_NAMES + f"""| project Finding, Severity, id, Detail, ResourceGroup, Subscription = coalesce(Subscription, subscriptionId)
| order by {SEVERITY_ORDER} asc, Finding asc, id asc
"""
    return group(f"{P}-tab-{key}", [
        text(f"{P}-{key}-intro", f"### {name}\n{intro}"),
        arg(f"{P}-{key}-tiles", "", tiles_q, vis="tiles", tiles=TILES),
        arg(f"{P}-{key}-advisor-tile", "", advisor_tile_q, vis="tiles", tiles=TILES, fixed_px=ONE_TILE),
        export_row(arg(f"{P}-{key}-advisor", f"Azure Advisor: {name} (select a row for the resources)", advisor_q,
                       formatters=[IMPACT, hidden("RecType")],
                       no_data=f"Advisor has no {name} recommendations for the workload."), "RecType", rec_param),
        when_set(arg(f"{P}-{key}-advisor-detail", "Resources for the selected recommendation", advisor_detail_q,
                     formatters=[resource_link()], labels={"id": "Resource"}), rec_param),
        arg(f"{P}-{key}-summary", "Configuration checks that fail", summary_q, formatters=[SEVERITY],
            labels={"Fix": "What to do", "Types": "Resource types"},
            no_data="Every configuration check passes for the workload."),
        arg(f"{P}-{key}-findings", "Findings by resource", list_q, formatters=[SEVERITY, resource_link()],
            labels={"id": "Resource", "ResourceGroup": "Resource group"}, group_by="Finding",
            no_data="Every configuration check passes for the workload."),
        *extras(key),
    ], tab=key)


def checks_reference():
    """A table of every check, so a reviewer can see what is and is not looked at."""
    seen = {}
    for _, name, checks, _ in PILLARS:
        for t, _, finding, sev, _, _ in checks:
            seen.setdefault((name, finding, sev), []).append(f"`{t}`")
    rows = "\n".join(f"| {name} | {finding} | {sev} | {', '.join(types)} |"
                     for (name, finding, sev), types in seen.items())
    return text(f"{P}-checks", "### What the configuration checks cover\n\n"
                "| Pillar | Check | Severity | Resource types |\n|---|---|---|---|\n" + rows +
                "\n\nThe idle-resource checks under Cost Optimization are the same ones the **Cloud Center of "
                "Excellence** workbook counts.")


PILLAR_COLS = [n.split()[0] for n in PILLAR_CODES]


def workloads_tab():
    return group(f"{P}-tab-workloads", [
        text(f"{P}-workloads-intro", "### Workloads\nEvery workload side by side: the configuration checks that fail "
             "for each, by pillar, and its Azure Advisor recommendations. Workloads are the values of the "
             "**Workload tag**; set **Workload** to *All* to compare them all, and pick one to review it on the "
             "pillar tabs. *(untagged)* is every resource without the tag, which a review cannot assign to anyone."),
        arg(f"{P}-workloads", "Findings by workload", workload_summary_q(),
            formatters=[low_is_good("High", 1, 1), low_is_good("Findings", 1, 20),
                        *[low_is_good(c, 1, 10) for c in PILLAR_COLS], low_is_good("AdvisorHigh", 1, 1)],
            labels={"TotalResources": "Resources", "Affected": "Resources with findings", "High": "High severity",
                    "Cost": "Cost Optimization", "Operational": "Operational Excellence",
                    "Performance": "Performance Efficiency", "Advisor": "Advisor recommendations",
                    "AdvisorHigh": "Advisor high impact"},
            no_data="No resources in the selected subscriptions."),
    ], tab="workloads")


def assessment_params(pillar, qs):
    plist = [{
        "id": gid(f"{P}-param-{code}"), "version": "KqlParameterItem/1.0", "name": code,
        "label": f"{code[:2]}:{code[2:]} {topic}", "type": 2, "isRequired": False,
        "jsonData": json.dumps([{"value": v, "label": l} for v, l in ANSWERS]),
        "typeSettings": {"showDefault": False}, "description": question,
    } for code, topic, question, _ in qs]
    plist.append(free_text_param(P, f"{qs[0][0][:2]}Notes", "Notes",
                                 f"Accepted risks, owners and dates for {pillar}, kept with the saved workbook."))
    return params(f"{P}-assess-{qs[0][0][:2].lower()}-params", plist)


ASSESSMENT_INTRO = """\
### Assessment
The questions of the Well-Architected checklist for each pillar, for the design, process and testing that no
setting shows. Answer each for the workload being reviewed: **Yes**, **Partly**, **No** or **Not applicable**
(hover over a question's name for the whole question). Each pillar is scored from its answers, and every No or
Partly is listed at the bottom as the gaps to act on. Where this workbook has evidence for a question, the table
says where to look.

The answers are workbook parameters: to keep them, **Save** the workbook once answered (or **Save As** a copy per
workload, and per review date). Export the tables to Excel for the review record."""


def assessment_tab():
    items = [text(f"{P}-assess-intro", ASSESSMENT_INTRO, "info"),
             arg(f"{P}-assess-score", "", ASSESSMENT_TILES_Q, vis="tiles", tiles=PCT_TILES)]
    for pillar, (slug, qs) in QUESTIONS.items():
        prefix = qs[0][0][:2]
        items += [
            text(f"{P}-assess-{prefix.lower()}-h", f"### {pillar}\nThe [{pillar} checklist]"
                 f"({CHECKLIST_URL.format(slug)}) explains each question and what good looks like."),
            assessment_params(pillar, qs),
            arg(f"{P}-assess-{prefix.lower()}", "", answers_q() + f"| where Pillar == '{pillar}'\n"
                "| project Id, Topic, Answer, Question, Evidence\n",
                formatters=[ANSWER_FMT], labels={"Evidence": "Evidence in this workbook"}),
            text(f"{P}-assess-{prefix.lower()}-notes", f"**Notes:** {{{prefix}Notes}}",
                 visible_when={"parameterName": f"{prefix}Notes", "comparison": "isNotEqualTo", "value": ""}),
        ]
    items.append(arg(f"{P}-assess-gaps", "Gaps to act on (every No and Partly)", GAPS_Q, formatters=[ANSWER_FMT],
                     labels={"Evidence": "Evidence in this workbook"},
                     no_data="Nothing answered No or Partly yet."))
    return group(f"{P}-tab-assessment", items, tab="assessment")


def workbook():
    return notebook([
        text(f"{P}-header", "# Well-Architected Framework\n"
             "A workload's gaps against the five pillars of the Azure Well-Architected Framework: Reliability, "
             "Security, Cost Optimization, Operational Excellence and Performance Efficiency. Each pillar combines "
             "Azure Advisor's recommendations with configuration checks read from Azure Resource Graph, so no "
             "workspace is needed; picking one adds the checks only logs can answer. The Assessment tab records the "
             "answers to the Well-Architected checklist and scores each pillar."),
        global_params(),
        tabs(),
        overview_tab(),
        workloads_tab(),
        *[pillar_tab(key, name, checks, intro) for key, name, checks, intro in PILLARS],
        assessment_tab(),
        group(f"{P}-reference", [checks_reference()], tab="overview"),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
