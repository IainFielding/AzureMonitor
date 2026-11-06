"""Generates the Well-Architected Framework workbook: a workload's gaps against the five pillars.

Run:  python src/build_well_architected.py
Out:  workbook/well-architected.workbook.json

A Well-Architected review is done per workload, so everything can be narrowed to one or more workloads, found by a
tag (`workload` unless changed). Each pillar has a tab with Azure Advisor's recommendations for it (Advisor's
categories are the pillars) and a set of configuration checks read from Resource Graph: the settings a reviewer
would otherwise look up resource by resource (zones, redundancy, SKUs being retired, public access, TLS, local
authentication, idle resources, monitoring agents, older VM sizes). It is a starting point for a review, not the
review itself: the Azure Well-Architected Review assessment asks the design questions no setting can answer.
Built from the helpers in build_workbook.py so the workbooks look alike.
"""

import pathlib

from build_backup import VM_PROTECTION
from build_workbook import (ADVISOR_RECS, AGENT_STATUS, ONE_TILE, SUBSCRIPTION_NAMES, WASTE_CHECKS, arg,
                            big_number_tiles, export_row, free_text_param, gid, group, hidden, high_is_good,
                            machine_agents, notebook, params, pct_bar, resource_link, status_fmt,
                            subscription_param, text, when_set, write_workbook)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "well-architected.workbook.json"

P = "waf"

TILES = big_number_tiles("Signal", "State", "Value", "Detail")

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
                    "microsoft.appconfiguration/configurationstores", "microsoft.signalrservice/signalr"]
VM_SIZE = "tostring(properties.hardwareProfile.vmSize)"
SKU = "tostring(sku.name)"

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
] + [(t, cond, kind, "Medium", detail, fix) for t, cond, kind, detail, fix in WASTE_CHECKS]

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
]

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
here are the settings a reviewer would otherwise open each resource to find; they do not replace the
[Azure Well-Architected Review](https://learn.microsoft.com/assessments/azure-architecture-review/), which asks
about design, process and recovery testing that no setting shows."""

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
        ]
    if key == "security":
        return [
            arg(f"{P}-defender", "Defender for Cloud recommendations for the workload", DEFENDER_Q, width=65,
                formatters=[status_fmt("Severity", warn=["Medium"], bad=["High"], neutral=["Low"])],
                no_data="No unhealthy Defender for Cloud recommendations (or Defender is not reporting)."),
            arg(f"{P}-secure-score", "Secure score by subscription", SECURE_SCORE_Q, width=35,
                formatters=[pct_bar("ScorePct")], labels={"ScorePct": "Score %"},
                no_data="No secure score: Defender for Cloud is not reporting for the selected subscriptions."),
        ]
    if key == "cost":
        return [text(f"{P}-cost-note", "Savings are Azure Advisor's own estimate for a year. The **Cloud Center of "
                     "Excellence** workbook's *Cost* tab rolls the same savings and idle resources up by "
                     "subscription.", "info")]
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
            text(f"{P}-ops-note", "Diagnostic settings are not in Resource Graph, so resources that send no logs "
                 "are not checked here: the **Platform health** *Monitoring* tab lists them.", "info"),
        ]
    if key == "performance":
        return [arg(f"{P}-autoscale", "Autoscale on scale sets and App Service plans", AUTOSCALE_Q,
                    formatters=[resource_link(), status_fmt("Autoscale", good=["On", "Automatic scaling"],
                                                            warn=["None", "Off"])],
                    labels={"id": "Resource", "ResourceGroup": "Resource group"},
                    no_data="No scale sets or App Service plans that can autoscale in the workload.")]
    return []


# ---------------------------------------------------------------------------
# Parameters and tabs
# ---------------------------------------------------------------------------

TABS = [("overview", "Overview")] + [(key, name) for key, name, _, _ in PILLARS]


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


def workbook():
    return notebook([
        text(f"{P}-header", "# Well-Architected Framework\n"
             "A workload's gaps against the five pillars of the Azure Well-Architected Framework: Reliability, "
             "Security, Cost Optimization, Operational Excellence and Performance Efficiency. Each pillar combines "
             "Azure Advisor's recommendations with configuration checks read from Azure Resource Graph, so no "
             "workspace is needed."),
        global_params(),
        tabs(),
        overview_tab(),
        *[pillar_tab(key, name, checks, intro) for key, name, checks, intro in PILLARS],
        group(f"{P}-reference", [checks_reference()], tab="overview"),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
