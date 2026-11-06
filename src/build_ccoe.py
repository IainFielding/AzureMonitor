"""Generates the Cloud Center of Excellence workbook: one scorecard across governance, security, cost and operations.

Run:  python src/build_ccoe.py
Out:  workbook/cloud-center-of-excellence.workbook.json

The view a Cloud Center of Excellence (or cloud governance board) takes once a month: a tile per measure, grouped by
the Cloud Adoption Framework's disciplines, a scorecard per subscription, and on each tab the subscriptions that are
behind. It answers "where are we, and who needs to act", not "what exactly is wrong": the detail behind each
measure is in the other workbooks (Azure Policy compliance, Platform health, Privileged access, FinOps hubs), which
each tab names. Everything comes from Azure Resource Graph, so no workspace is needed. Built from the helpers in
build_workbook.py so the workbooks look alike.
"""

import pathlib

from build_workbook import (ADVISOR_RECS, GOVERNANCE_TILES, ONE_TILE, SUBSCRIPTION_NAMES, arg,
                            big_number_tiles, free_text_param, gid, group, hidden, high_is_good, low_is_good,
                            machine_agents, notebook, params, pct_bar, resource_link, status_fmt, subscription_param,
                            text, waste, when_set, write_workbook)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "cloud-center-of-excellence.workbook.json"

P = "ccoe"

TABS = [
    ("scorecard", "Scorecard"),
    ("landingzones", "Landing zones"),
    ("governance", "Governance & tagging"),
    ("cost", "Cost"),
    ("security", "Security & identity"),
    ("operations", "Operations"),
]

TILES = big_number_tiles("Signal", "State", "Value", "Detail")
PCT_TILES = big_number_tiles("Signal", "State", "Value", "Detail", "%")
GOV = {key: (unit, q) for key, unit, q in GOVERNANCE_TILES}

# ---------------------------------------------------------------------------
# Subscriptions and where they sit
# ---------------------------------------------------------------------------

# managementGroupAncestorsChain runs from the parent up to the tenant root group, so a chain of one means the
# subscription sits directly under the root: outside every landing zone management group.
SUBS = r"""
resourcecontainers
| where type =~ 'microsoft.resources/subscriptions'
| extend chain = properties.managementGroupAncestorsChain
| project subscriptionId, Subscription = name, SubState = tostring(properties.state),
    ParentMG = iff(array_length(chain) > 0, tostring(chain[0].displayName), '(none)'),
    Depth = coalesce(array_length(chain), 0),
    Offer = tostring(split(tostring(properties.subscriptionPolicies.quotaId), '_')[0]),
    Owner = extract(@'(?i)"{OwnerTag}":"([^"]*)"', 1, tostring(tags))
| extend Placement = case(Depth == 0, 'No management group', Depth == 1, 'Directly under tenant root', 'In a management group')
"""

PLACEMENT = status_fmt("Placement", good=["In a management group"], warn=["Directly under tenant root"],
                       bad=["No management group"])
SUB_STATE = status_fmt("SubState", good=["Enabled"], warn=["Warned", "PastDue"], bad=["Disabled", "Deleted"])

# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

# Types created by the platform itself, which nobody tags: counting them would only lower every score.
UNTAGGED_BY_DESIGN = ", ".join(f"'{t}'" for t in [
    "microsoft.compute/virtualmachines/extensions", "microsoft.hybridcompute/machines/extensions",
    "microsoft.network/networkwatchers", "microsoft.network/networkwatchers/flowlogs",
    "microsoft.alertsmanagement/smartdetectoralertrules", "microsoft.compute/restorepointcollections",
])

RESOURCES = f"""
resources
| where type !in~ ({UNTAGGED_BY_DESIGN})
"""


def tag_rows(source):
    """One row per item and required tag, with whether the item carries it. Tag names compare without case, as
    Azure treats them."""
    return source + r"""| extend tagText = tolower(tostring(tags)), required = split(tolower('{RequiredTags}'), ',')
| mv-expand tag = required
| extend tag = trim(' ', tostring(tag))
| where isnotempty(tag)
| extend HasTag = tagText contains strcat('"', tag, '":')
"""


def missing_tags(source, by):
    return tag_rows(source) + f"| summarize Missing = make_set_if(tag, not(HasTag)) by {by}\n"


RES_TAGS = missing_tags(RESOURCES, "id, type, subscriptionId, resourceGroup")
RG_TAGS = missing_tags("resourcecontainers\n| where type =~ 'microsoft.resources/subscriptions/resourcegroups'\n",
                       "id, subscriptionId, resourceGroup")
SUB_TAGS = missing_tags("resourcecontainers\n| where type =~ 'microsoft.resources/subscriptions'\n",
                        "subscriptionId, Subscription = name")

# Regions: summarised by region first, so the approved list is only expanded once per region.
OUTSIDE_REGIONS = r"""
resources
| where isnotempty(location) and location !~ 'global'
| summarize Resources = count() by location = tolower(location), subscriptionId
| extend approved = split(tolower('{ApprovedRegions}'), ',')
| mv-expand a = approved
| extend a = trim(' ', tostring(a))
| summarize Approved = countif(a == location), Listed = countif(isnotempty(a)) by location, subscriptionId, Resources
| where Listed > 0 and Approved == 0
"""

# ---------------------------------------------------------------------------
# Privileged access, retirements, patching
# ---------------------------------------------------------------------------

# Owner, User Access Administrator and Role Based Access Control Administrator: the roles that can grant access.
# Resource Graph returns an inherited assignment once per subscription, so they are de-duplicated first.
PRIVILEGED = r"""
authorizationresources
| where type =~ 'microsoft.authorization/roleassignments'
| extend roleId = tolower(tostring(split(tostring(properties.roleDefinitionId), '/')[-1])),
    scope = tolower(tostring(properties.scope))
| where roleId in ('8e3af657-a8ff-443c-a75c-2fe8c4bcb635', '18d7d88d-d35e-4fb5-a5c3-7773c20a72d9', 'f58310d9-a9f6-439a-9e8d-f62e7b41a168')
| extend Role = case(roleId startswith '8e3af657', 'Owner', roleId startswith '18d7d88d', 'User Access Administrator',
        'RBAC Administrator'),
    ScopeLevel = case(scope == '/', 'Tenant root', scope startswith '/providers/microsoft.management/managementgroups/', 'Management group',
        array_length(split(scope, '/')) == 3, 'Subscription', array_length(split(scope, '/')) == 5, 'Resource group', 'Resource')
| summarize by scope, ScopeLevel, Role, principalType = tostring(properties.principalType), principalId = tostring(properties.principalId)
"""

RETIREMENTS = ADVISOR_RECS + r"""| where tostring(properties.extendedProperties.recommendationSubCategory) =~ 'ServiceUpgradeAndRetirement'
| extend Retires = todatetime(properties.extendedProperties.retirementDate),
    Retiring = coalesce(tostring(properties.extendedProperties.retirementFeatureName), Problem)
| where Retires < now() + 180d
"""

COST_RECS = ADVISOR_RECS + "| where Pillar == 'Cost Optimization'\n"

# ---------------------------------------------------------------------------
# Scorecard tiles: one row each, Signal / Value / Detail / State
# ---------------------------------------------------------------------------

TAG_TILE_Q = RES_TAGS + """| summarize Total = count(), Full = countif(array_length(Missing) == 0)
| project Signal = 'Tag coverage', Value = iff(Total == 0, real(null), round(100.0 * Full / Total, 1)),
    Detail = strcat(Total - Full, ' resources missing a required tag'),
    State = case(Total == 0, 'Unknown', Full == Total, 'Available', Full >= 0.8 * Total, 'Degraded', 'Unavailable')
"""

PLACEMENT_TILE_Q = SUBS + """| summarize Total = count(), Outside = countif(Placement != 'In a management group')
| project Signal = 'Subscriptions at the tenant root', Value = Outside, Detail = strcat('of ', Total, ' subscriptions'),
    State = iff(Outside > 0, 'Degraded', 'Available')
"""

REGION_TILE_Q = OUTSIDE_REGIONS + """| summarize Resources = sum(Resources), Regions = dcount(location)
| project Signal = 'Resources outside approved regions', Value = coalesce(Resources, 0),
    Detail = strcat('in ', coalesce(Regions, 0), ' regions'), State = iff(coalesce(Resources, 0) > 0, 'Degraded', 'Available')
"""

OWNERS_TILE_Q = PRIVILEGED + """| where ScopeLevel in ('Tenant root', 'Management group', 'Subscription')
| summarize Direct = countif(principalType =~ 'User'), Total = count()
| project Signal = 'Privileged roles held by users directly', Value = Direct,
    Detail = strcat('of ', Total, ' at subscription scope or above'), State = iff(Direct > 0, 'Degraded', 'Available')
"""

SAVINGS_TILE_Q = COST_RECS + """| summarize Savings = sum(Savings), Recs = count(), Currency = take_anyif(Currency, isnotempty(Currency))
| project Signal = 'Advisor savings a year', Value = round(coalesce(Savings, 0.0), 0),
    Detail = strcat(coalesce(Currency, ''), ' · ', Recs, ' recommendations'), State = iff(Recs > 0, 'Degraded', 'Available')
"""

WASTE_TILE_Q = waste() + """| summarize Resources = count(), Kinds = dcount(Waste)
| project Signal = 'Idle resources', Value = Resources, Detail = strcat(Kinds, ' kinds · see Cost'),
    State = iff(Resources > 0, 'Degraded', 'Available')
"""

AGENT_TILE_Q = machine_agents() + """| summarize Total = count(), Gaps = countif(Agent in ('Legacy agent only', 'No agent')),
    Legacy = countif(Agent == 'Legacy agent only')
| project Signal = 'Machines without Azure Monitor Agent', Value = Gaps,
    Detail = strcat('of ', Total, ' · ', Legacy, ' on the legacy agent'),
    State = case(Total == 0, 'Unknown', Gaps > 0, 'Degraded', 'Available')
"""

RETIREMENT_TILE_Q = RETIREMENTS + """| summarize Features = dcount(Retiring), Resources = dcount(rid)
| project Signal = 'Retiring within 180 days', Value = Features, Detail = strcat(Resources, ' resources affected'),
    State = iff(Features > 0, 'Degraded', 'Available')
"""

# The per-subscription scorecard: three joins, the most Resource Graph allows.
def nested(query):
    """A query indented to sit inside a join's brackets."""
    return "    " + query.strip().replace("\n", "\n    ")


SCORECARD_Q = SUBS + """| join kind=leftouter (
""" + nested(RES_TAGS) + """
    | summarize Resources = count(), Tagged = countif(array_length(Missing) == 0) by subscriptionId
  ) on subscriptionId
| join kind=leftouter (
    policyresources
    | where type =~ 'microsoft.policyinsights/policystates'
    | summarize Evaluated = dcount(tostring(properties.resourceId)),
        NonCompliant = dcountif(tostring(properties.resourceId), tostring(properties.complianceState) =~ 'NonCompliant')
        by subscriptionId
  ) on subscriptionId
| join kind=leftouter (
    securityresources
    | where type =~ 'microsoft.security/securescores'
    | project subscriptionId, SecureScorePct = round(100 * toreal(properties.score.percentage), 0)
  ) on subscriptionId
| project Subscription, ParentMG, Placement, Owner, Resources = coalesce(Resources, 0),
    TagPct = iff(Resources > 0, round(100.0 * Tagged / Resources, 0), real(null)),
    PolicyPct = iff(Evaluated > 0, round(100.0 * (Evaluated - NonCompliant) / Evaluated, 0), real(null)),
    SecureScorePct, subscriptionId
| order by PolicyPct asc
"""

SCORE_LABELS = {"ParentMG": "Parent management group", "TagPct": "Tag coverage %", "PolicyPct": "Policy compliance %",
                "SecureScorePct": "Secure score %", "subscriptionId": "Subscription ID"}

SCORECARD_NOTE = """\
**How to read this.** Each tile is one measure the CCoE owns; a green tick means nothing needs action, amber means
some subscriptions are behind. *Policy compliance* is the share of evaluated resources with no failing policy (as in
the Azure portal). *Tag coverage* counts resources that carry every tag in **Required tags**, ignoring the
platform's own types that nobody tags (extensions, Network Watcher). *Privileged roles* are Owner, User Access
Administrator and RBAC Administrator assigned to a user rather than a group. *Idle resources* are unattached disks,
unused public IPs, stopped but billed VMs, empty App Service plans, unused load balancers and NAT gateways, and old
snapshots. *Advisor savings* is Azure Advisor's own estimate, a year. Advisor high-impact issues and the Defender for
Cloud secure score are the same figures as on the Platform health overview."""

# ---------------------------------------------------------------------------
# Landing zones
# ---------------------------------------------------------------------------

BY_MG_Q = SUBS + """| summarize Subscriptions = count() by ParentMG
| order by Subscriptions desc
"""

BY_OFFER_Q = SUBS + "| summarize Subscriptions = count() by Offer = iff(isempty(Offer), '(unknown)', Offer)\n"

INVENTORY_Q = SUBS + """| join kind=leftouter (
    resources
    | summarize Resources = count(), ResourceGroups = dcount(resourceGroup), Regions = dcount(location) by subscriptionId
  ) on subscriptionId
| project Subscription, SubState, Placement, ParentMG, Owner, Offer, Resources = coalesce(Resources, 0),
    ResourceGroups = coalesce(ResourceGroups, 0), Regions = coalesce(Regions, 0), subscriptionId
| order by case(Placement == 'In a management group', 1, 0) asc, ParentMG asc, Subscription asc
"""

GROWTH_Q = r"""
resourcechanges
| extend Time = todatetime(properties.changeAttributes.timestamp), ChangeType = tostring(properties.changeType)
| where ChangeType in ('Create', 'Delete')
| summarize Created = countif(ChangeType == 'Create'), Deleted = countif(ChangeType == 'Delete')
    by Day = format_datetime(startofday(Time), 'yyyy-MM-dd')
| order by Day asc
"""

TOP_TYPES_Q = r"""
resources
| summarize Resources = count(), Subscriptions = dcount(subscriptionId), Regions = dcount(location) by Type = tolower(type)
| top 25 by Resources desc
"""

BY_REGION_Q = r"""
resources
| where isnotempty(location)
| summarize Resources = count() by Region = tolower(location)
| top 15 by Resources desc
"""

# ---------------------------------------------------------------------------
# Governance and tagging
# ---------------------------------------------------------------------------

POLICY_BY_SUB_Q = r"""
policyresources
| where type =~ 'microsoft.policyinsights/policystates'
| summarize Evaluated = dcount(tostring(properties.resourceId)),
    NonCompliant = dcountif(tostring(properties.resourceId), tostring(properties.complianceState) =~ 'NonCompliant'),
    FailingPolicies = dcountif(tostring(properties.policyDefinitionId), tostring(properties.complianceState) =~ 'NonCompliant')
    by subscriptionId
| join kind=inner (
""" + nested(SUBS) + r"""
  ) on subscriptionId
| project Subscription, ParentMG, Owner, Evaluated, NonCompliant, FailingPolicies,
    CompliancePct = round(100.0 * (Evaluated - NonCompliant) / Evaluated, 1)
| order by CompliancePct asc
"""

TAG_BY_NAME_Q = tag_rows(RESOURCES) + """| summarize Resources = count(), Tagged = countif(HasTag) by Tag = tag
| extend CoveragePct = round(100.0 * Tagged / Resources, 1)
| project Tag, CoveragePct, Tagged, Missing = Resources - Tagged
| order by CoveragePct asc
"""

TAG_BY_SUB_Q = RES_TAGS + """| summarize Resources = count(), Tagged = countif(array_length(Missing) == 0) by subscriptionId
""" + SUBSCRIPTION_NAMES + """| project Subscription = coalesce(Subscription, subscriptionId), CoveragePct = round(100.0 * Tagged / Resources, 1),
    Untagged = Resources - Tagged, Resources
| order by CoveragePct asc
"""

TAG_GAPS_SUB_Q = SUB_TAGS + """| where array_length(Missing) > 0
| project Subscription, Missing = strcat_array(Missing, ', '), subscriptionId
| order by Subscription asc
"""

TAG_GAPS_RG_Q = RG_TAGS + """| where array_length(Missing) > 0
""" + SUBSCRIPTION_NAMES + """| project id, Missing = strcat_array(Missing, ', '), Subscription = coalesce(Subscription, subscriptionId)
| order by Subscription asc, id asc
"""

TAG_GAPS_RES_Q = RES_TAGS + """| where array_length(Missing) > 0
""" + SUBSCRIPTION_NAMES + """| project id, Type = type, Missing = strcat_array(Missing, ', '), MissingCount = array_length(Missing),
    ResourceGroup = resourceGroup, Subscription = coalesce(Subscription, subscriptionId)
| order by MissingCount desc, Type asc
"""

OUTSIDE_REGIONS_Q = OUTSIDE_REGIONS + SUBSCRIPTION_NAMES + """| project Region = location, Subscription = coalesce(Subscription, subscriptionId), Resources
| order by Resources desc
"""

# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------

COST_TILES_Q = COST_RECS + """| summarize Savings = sum(Savings), Recs = count(), Resources = dcount(rid),
    Commitments = countif(Problem has_any ('reserved instance', 'reservation', 'savings plan')),
    CommitmentSavings = sumif(Savings, Problem has_any ('reserved instance', 'reservation', 'savings plan')),
    Currency = take_anyif(Currency, isnotempty(Currency))
| extend rows = pack_array(
    pack('Signal', 'Advisor savings a year', 'Value', round(coalesce(Savings, 0.0), 0), 'Detail', strcat(Currency, ' · all cost recommendations')),
    pack('Signal', 'From reservations and savings plans', 'Value', round(coalesce(CommitmentSavings, 0.0), 0), 'Detail', strcat(Currency, ' · ', Commitments, ' recommendations')),
    pack('Signal', 'Resources to right-size or remove', 'Value', Resources, 'Detail', strcat(Recs, ' recommendations')))
| mv-expand r = rows
| project Signal = tostring(r.Signal), Value = todouble(r.Value), Detail = tostring(r.Detail),
    State = iff(todouble(r.Value) > 0, 'Degraded', 'Available')
"""

SAVINGS_BY_SUB_Q = COST_RECS + """| summarize Savings = round(sum(Savings), 0), Recommendations = count(),
    Currency = take_anyif(Currency, isnotempty(Currency)) by subscriptionId
""" + SUBSCRIPTION_NAMES + """| project Subscription = coalesce(Subscription, subscriptionId), Savings, Currency, Recommendations
| order by Savings desc
"""

SAVINGS_BY_REC_Q = COST_RECS + """| summarize Savings = round(sum(Savings), 0), Resources = dcount(rid), Subscriptions = dcount(subscriptionId),
    Currency = take_anyif(Currency, isnotempty(Currency)) by Problem, Solution, Impact
| project Recommendation = Problem, Savings, Currency, Resources, Subscriptions, Impact, Action = Solution
| order by Savings desc
"""

WASTE_BY_SUB_Q = waste() + """| summarize Idle = count(), Kinds = strcat_array(make_set(Waste), ', ') by subscriptionId
""" + SUBSCRIPTION_NAMES + """| project Subscription = coalesce(Subscription, subscriptionId), Idle, Kinds
| order by Idle desc
"""

WASTE_Q = waste() + SUBSCRIPTION_NAMES + """| project id, Waste, Detail, Fix, ResourceGroup, Subscription = coalesce(Subscription, subscriptionId)
| order by Waste asc, Subscription asc
"""

# Windows Server VMs with no licence type pay for Windows in the VM price; with Software Assurance or a
# subscription licence, Azure Hybrid Benefit removes that charge. Windows client VMs (AVD) need Windows_Client.
HYBRID_BENEFIT_Q = r"""
resources
| where type in~ ('microsoft.compute/virtualmachines', 'microsoft.sqlvirtualmachine/sqlvirtualmachines')
| extend Gap = case(
    type =~ 'microsoft.compute/virtualmachines' and tostring(properties.storageProfile.osDisk.osType) =~ 'Windows'
        and isempty(tostring(properties.licenseType)), 'Windows VM with no licence type',
    type =~ 'microsoft.sqlvirtualmachine/sqlvirtualmachines' and tostring(properties.sqlServerLicenseType) =~ 'PAYG',
        'SQL Server VM paying for SQL licence',
    '')
| where isnotempty(Gap)
| summarize Machines = count() by Gap, subscriptionId
""" + SUBSCRIPTION_NAMES + """| project Subscription = coalesce(Subscription, subscriptionId), Gap, Machines
| order by Machines desc
"""

# ---------------------------------------------------------------------------
# Security and identity
# ---------------------------------------------------------------------------

SECURE_SCORE_Q = r"""
securityresources
| where type =~ 'microsoft.security/securescores'
| project subscriptionId, ScorePct = round(100 * toreal(properties.score.percentage), 0),
    Current = round(toreal(properties.score.current), 1), Max = toreal(properties.score.max)
""" + SUBSCRIPTION_NAMES + """| project Subscription = coalesce(Subscription, subscriptionId), ScorePct, Current, Max
| order by ScorePct asc
"""

DEFENDER_PLANS_Q = r"""
securityresources
| where type =~ 'microsoft.security/pricings'
| where not(tobool(properties.deprecated))
| extend isOn = tostring(properties.pricingTier) =~ 'Standard'
| summarize PlansOn = countif(isOn), PlansOff = countif(not(isOn)), Off = make_set_if(name, not(isOn)) by subscriptionId
""" + SUBSCRIPTION_NAMES + """| project Subscription = coalesce(Subscription, subscriptionId), CoveragePct = round(100.0 * PlansOn / (PlansOn + PlansOff), 0),
    PlansOn, PlansOff, Off = strcat_array(Off, ', ')
| order by CoveragePct asc
"""

HIGH_RECS_Q = r"""
securityresources
| where type =~ 'microsoft.security/assessments'
| where tostring(properties.status.code) =~ 'Unhealthy' and tostring(properties.metadata.severity) =~ 'High'
| summarize Resources = dcount(tolower(tostring(properties.resourceDetails.Id))),
    Recommendations = dcount(tostring(properties.displayName)) by subscriptionId
""" + SUBSCRIPTION_NAMES + """| project Subscription = coalesce(Subscription, subscriptionId), Recommendations, Resources
| order by Resources desc
"""

PRIVILEGED_SUMMARY_Q = PRIVILEGED + """| summarize Users = countif(principalType =~ 'User'), Groups = countif(principalType =~ 'Group'),
    ServicePrincipals = countif(principalType =~ 'ServicePrincipal') by ScopeLevel, Role
| order by case(ScopeLevel == 'Tenant root', 0, ScopeLevel == 'Management group', 1, ScopeLevel == 'Subscription', 2,
    ScopeLevel == 'Resource group', 3, 4) asc, Role asc
"""

PRIVILEGED_USERS_Q = PRIVILEGED + """| where principalType =~ 'User' and ScopeLevel in ('Tenant root', 'Management group', 'Subscription')
| extend subscriptionId = iff(ScopeLevel == 'Subscription', tostring(split(scope, '/')[2]), '')
""" + SUBSCRIPTION_NAMES + """| project ScopeLevel, Scope = case(ScopeLevel == 'Subscription', coalesce(Subscription, subscriptionId),
        ScopeLevel == 'Management group', tostring(split(scope, '/')[4]), '/'),
    Role, PrincipalId = principalId
| order by case(ScopeLevel == 'Tenant root', 0, ScopeLevel == 'Management group', 1, 2) asc, Scope asc
"""

# A custom role with '*' among its actions can do anything a built-in Owner or Contributor can, often more widely
# than intended; a provider wildcard ('Microsoft.Compute/*') is common and usually deliberate.
CUSTOM_ROLES_Q = r"""
authorizationresources
| where type =~ 'microsoft.authorization/roledefinitions'
| where tostring(properties.type) =~ 'CustomRole'
| mv-expand perm = properties.permissions
| mv-expand action = perm.actions
| extend action = tostring(action)
| where action contains '*'
| summarize Wildcards = make_set(action, 10), Full = countif(action == '*')
    by id, Role = tostring(properties.roleName), Scopes = strcat_array(properties.assignableScopes, ', ')
| project Role, Wildcard = iff(Full > 0, 'All actions (*)', 'Provider wildcards'), Actions = strcat_array(Wildcards, ', '), Scopes
| order by Wildcard asc, Role asc
"""

# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

AGENTS_BY_SUB_Q = machine_agents() + """| summarize Machines = count(), Ama = countif(Agent startswith 'Azure Monitor Agent'),
    LegacyOnly = countif(Agent == 'Legacy agent only'), NoAgent = countif(Agent == 'No agent') by subscriptionId
""" + SUBSCRIPTION_NAMES + """| project Subscription = coalesce(Subscription, subscriptionId), CoveragePct = round(100.0 * Ama / Machines, 0),
    Machines, LegacyOnly, NoAgent
| order by CoveragePct asc
"""

AGENTS_PIE_Q = machine_agents() + "| summarize Machines = count() by Agent\n"

PATCH_BY_SUB_Q = r"""
resources
| where type in~ ('microsoft.compute/virtualmachines', 'microsoft.hybridcompute/machines')
| project id = tolower(id), subscriptionId
| join kind=leftouter (
    patchassessmentresources
    | where type in~ ('microsoft.compute/virtualmachines/patchassessmentresults', 'microsoft.hybridcompute/machines/patchassessmentresults')
    | project id = tostring(split(tolower(id), '/patchassessmentresults/')[0]),
        Assessed = todatetime(properties.lastModifiedDateTime),
        Critical = coalesce(toint(properties.availablePatchCountByClassification.critical), 0),
        Security = coalesce(toint(properties.availablePatchCountByClassification.security), 0),
        Reboot = tobool(properties.rebootPending)
  ) on id
| summarize Machines = count(), Pending = countif(Critical > 0 or Security > 0), Reboot = countif(Reboot),
    NotAssessed = countif(isnull(Assessed) or Assessed < ago(7d)) by subscriptionId
""" + SUBSCRIPTION_NAMES + """| project Subscription = coalesce(Subscription, subscriptionId), Machines,
    UpToDatePct = round(100.0 * (Machines - Pending - NotAssessed) / Machines, 0), Pending, NotAssessed, Reboot
| order by UpToDatePct asc
"""

ADVISOR_BY_SUB_Q = ADVISOR_RECS + """| where Impact =~ 'High'
| summarize Reliability = countif(Pillar == 'Reliability'), Security = countif(Pillar == 'Security'),
    Cost = countif(Pillar == 'Cost Optimization'), Operations = countif(Pillar == 'Operational Excellence'),
    Performance = countif(Pillar == 'Performance Efficiency'), Total = count() by subscriptionId
""" + SUBSCRIPTION_NAMES + """| project Subscription = coalesce(Subscription, subscriptionId), Total, Reliability, Security, Cost, Operations, Performance
| order by Total desc
"""

# A change is a user change when any of its properties is (system changes are the platform's own bookkeeping).
CHANGE_CLIENTS = r"""
resourcechanges
| extend ChangeType = tostring(properties.changeType), Client = tostring(properties.changeAttributes.clientType)
| where ChangeType != 'Update' or tostring(properties.changes) contains '"changeCategory":"User"'
| extend Client = iff(isempty(Client) or Client =~ 'Unspecified', '(not recorded)', Client)
"""

CHANGE_CLIENT_PIE_Q = CHANGE_CLIENTS + "| summarize Changes = count() by Client\n| top 8 by Changes desc\n"

CHANGE_PORTAL_Q = CHANGE_CLIENTS + """| summarize Changes = count(), Portal = countif(Client has 'portal') by subscriptionId
""" + SUBSCRIPTION_NAMES + """| project Subscription = coalesce(Subscription, subscriptionId), PortalPct = round(100.0 * Portal / Changes, 0), Portal, Changes
| order by PortalPct desc
"""

RETIREMENTS_Q = RETIREMENTS + """| summarize Resources = dcount(rid), Subscriptions = dcount(subscriptionId) by Retiring, Retires, Action = Solution
| project Retiring, RetirementDate = Retires, DaysLeft = datetime_diff('day', Retires, now()), Resources, Subscriptions, Action
| order by RetirementDate asc
"""

HEALTH_Q = r"""
healthresources
| where type =~ 'microsoft.resourcehealth/availabilitystatuses'
| extend State = tostring(properties.availabilityState)
| where State in~ ('Unavailable', 'Degraded')
| project id = tostring(split(tolower(id), '/providers/microsoft.resourcehealth/')[0]), State,
    Reason = tostring(properties.reasonType), Summary = tostring(properties.summary),
    Since = todatetime(coalesce(tostring(properties.occurredTime), tostring(properties.occuredTime))), subscriptionId
""" + SUBSCRIPTION_NAMES + """| project id, State, Reason, Since, Summary, Subscription = coalesce(Subscription, subscriptionId)
| order by case(State =~ 'Unavailable', 0, 1) asc, Since asc
"""

# ---------------------------------------------------------------------------
# Parameters and tabs
# ---------------------------------------------------------------------------


def global_params():
    return params(f"{P}-params", [
        subscription_param(P),
        free_text_param(P, "RequiredTags", "Required tags",
                        "Comma-separated tag names every resource should carry, as your tagging policy sets out. "
                        "Compared without case.", "owner,costcenter,environment"),
        free_text_param(P, "OwnerTag", "Owner tag", "The tag on a subscription that names its owner, shown beside "
                        "each subscription.", "owner"),
        free_text_param(P, "ApprovedRegions", "Approved regions",
                        "Optional. Comma-separated Azure region names (for example uksouth,ukwest). Resources "
                        "elsewhere are counted on the Scorecard and listed on Governance & tagging."),
        {"id": gid(f"{P}-param-selectedTab"), "version": "KqlParameterItem/1.0", "name": "selectedTab", "type": 1,
         "value": "scorecard", "isHiddenWhenLocked": True},
    ])


def tabs():
    return {"type": 11, "content": {"version": "LinkItem/1.0", "style": "tabs", "links": [
        {"id": gid(f"{P}-tab-" + key), "cellValue": "selectedTab", "linkTarget": "parameter",
         "linkLabel": label, "subTarget": key, "style": "link"} for key, label in TABS
    ]}, "name": f"{P}-tabs"}


def tile(name, query, pct=False, **kw):
    return arg(f"{P}-{name}", "", query, vis="tiles", tiles=PCT_TILES if pct else TILES, fixed_px=ONE_TILE, **kw)


def gov_tile(key):
    unit, q = GOV[key]
    return tile(f"tile-{key}", q, pct=unit == "%")


def scorecard_tab():
    return group(f"{P}-tab-scorecard", [
        text(f"{P}-govern-h", "### Govern"),
        gov_tile("policy"),
        tile("tile-tags", TAG_TILE_Q, pct=True),
        tile("tile-placement", PLACEMENT_TILE_Q),
        when_set(tile("tile-regions", REGION_TILE_Q), "ApprovedRegions"),
        text(f"{P}-secure-h", "### Secure"),
        gov_tile("defender"),
        tile("tile-owners", OWNERS_TILE_Q),
        text(f"{P}-cost-h", "### Manage cost"),
        tile("tile-savings", SAVINGS_TILE_Q),
        tile("tile-waste", WASTE_TILE_Q),
        text(f"{P}-operate-h", "### Operate"),
        gov_tile("advisor"),
        tile("tile-agents", AGENT_TILE_Q),
        tile("tile-retirements", RETIREMENT_TILE_Q),
        text(f"{P}-scorecard-note", SCORECARD_NOTE, "info"),
        arg(f"{P}-scorecard", "Scorecard by subscription", SCORECARD_Q,
            formatters=[PLACEMENT, pct_bar("TagPct"), pct_bar("PolicyPct"), pct_bar("SecureScorePct"),
                        hidden("subscriptionId")],
            labels=SCORE_LABELS, no_data="No subscriptions selected."),
    ], tab="scorecard")


def landing_zones_tab():
    return group(f"{P}-tab-landingzones", [
        text(f"{P}-lz-intro", "Where subscriptions sit in the management group hierarchy, and how the estate is "
             "growing. In an Azure landing zone every subscription belongs under a landing zone, platform, sandbox or "
             "decommissioned management group; one *directly under the tenant root* gets none of the policies or "
             "access set on those groups."),
        arg(f"{P}-by-mg", "Subscriptions by parent management group", BY_MG_Q, vis="barchart", width=50),
        arg(f"{P}-by-offer", "Subscriptions by offer", BY_OFFER_Q, vis="piechart", width=50),
        arg(f"{P}-inventory", "Subscriptions", INVENTORY_Q,
            formatters=[PLACEMENT, SUB_STATE, hidden("subscriptionId")],
            labels={"SubState": "State", "ParentMG": "Parent management group", "ResourceGroups": "Resource groups"},
            no_data="No subscriptions selected."),
        arg(f"{P}-growth", "Resources created and deleted per day (last 14 days)", GROWTH_Q, vis="barchart",
            chart={"seriesLabelSettings": [{"seriesName": "Created", "color": "green"},
                                           {"seriesName": "Deleted", "color": "redBright"}]},
            no_data="No resources created or deleted in the last 14 days."),
        arg(f"{P}-types", "Most common resource types", TOP_TYPES_Q, width=60),
        arg(f"{P}-regions", "Resources by region", BY_REGION_Q, vis="piechart", width=40),
        text(f"{P}-lz-note", "Resource Graph keeps 14 days of change history, so growth is shown for that window "
             "only. For a resource-by-resource view of the changes, use the **What changed?** workbook.", "info"),
    ], tab="landingzones")


def governance_tab():
    return group(f"{P}-tab-governance", [
        text(f"{P}-gov-intro", "Policy compliance and tagging by subscription. For the detail behind a low score "
             "(which policies fail, exemptions, regulatory initiatives) open the **Azure Policy compliance** "
             "workbook."),
        arg(f"{P}-policy-subs", "Azure Policy compliance by subscription", POLICY_BY_SUB_Q,
            formatters=[pct_bar("CompliancePct")],
            labels={"ParentMG": "Parent management group", "NonCompliant": "Non-compliant resources",
                    "FailingPolicies": "Failing policies", "CompliancePct": "Compliance %"},
            no_data="No policy evaluation results in the selected subscriptions."),
        text(f"{P}-tags-h", "### Tagging\nMeasured against **Required tags** at the top. Tags inherited from a "
             "resource group by policy (*Inherit a tag from the resource group*) are written to the resource and "
             "count; tags only on the resource group do not."),
        arg(f"{P}-tags-by-name", "Coverage by tag", TAG_BY_NAME_Q, width=40, formatters=[pct_bar("CoveragePct")],
            labels={"CoveragePct": "Coverage %", "Missing": "Resources without it"},
            no_data="Set Required tags at the top."),
        arg(f"{P}-tags-by-sub", "Coverage by subscription", TAG_BY_SUB_Q, width=60, formatters=[pct_bar("CoveragePct")],
            labels={"CoveragePct": "Coverage %", "Untagged": "Missing a tag"},
            no_data="Set Required tags at the top."),
        arg(f"{P}-tags-subs", "Subscriptions missing required tags", TAG_GAPS_SUB_Q, width=40,
            formatters=[hidden("subscriptionId")], no_data="Every subscription carries every required tag."),
        arg(f"{P}-tags-rgs", "Resource groups missing required tags", TAG_GAPS_RG_Q, width=60,
            formatters=[resource_link()], labels={"id": "Resource group"},
            no_data="Every resource group carries every required tag."),
        arg(f"{P}-tags-resources", "Resources missing required tags", TAG_GAPS_RES_Q,
            formatters=[resource_link(), hidden("MissingCount")], labels={"id": "Resource", "ResourceGroup": "Resource group"},
            no_data="Every resource carries every required tag."),
        when_set(text(f"{P}-regions-h", "### Regions"), "ApprovedRegions"),
        when_set(arg(f"{P}-outside-regions", "Resources outside the approved regions", OUTSIDE_REGIONS_Q,
                     no_data="Every resource is in an approved region (or is global)."), "ApprovedRegions"),
    ], tab="governance")


def cost_tab():
    return group(f"{P}-tab-cost", [
        text(f"{P}-cost-intro", "Savings the CCoE can chase, by subscription. Resource Graph holds no spend: for "
             "actual and forecast cost use Cost Management, or the **FinOps hubs** data, which this workbook does "
             "not read."),
        arg(f"{P}-cost-tiles", "", COST_TILES_Q, vis="tiles", tiles=TILES),
        arg(f"{P}-savings-subs", "Advisor savings by subscription (a year)", SAVINGS_BY_SUB_Q, width=40,
            no_data="Advisor has no cost recommendations for the selected subscriptions."),
        arg(f"{P}-savings-recs", "Advisor cost recommendations", SAVINGS_BY_REC_Q, width=60,
            formatters=[status_fmt("Impact", warn=["Medium"], bad=["High"], neutral=["Low"])],
            no_data="Advisor has no cost recommendations for the selected subscriptions."),
        text(f"{P}-waste-h", "### Idle resources"),
        arg(f"{P}-waste-subs", "Idle resources by subscription", WASTE_BY_SUB_Q, width=40,
            no_data="No idle resources found."),
        arg(f"{P}-hybrid", "Licences paid in the VM price (Azure Hybrid Benefit not used)", HYBRID_BENEFIT_Q, width=60,
            no_data="Every Windows and SQL Server VM uses Azure Hybrid Benefit."),
        arg(f"{P}-waste", "Idle resources", WASTE_Q, formatters=[resource_link()], group_by="Waste",
            labels={"id": "Resource", "ResourceGroup": "Resource group", "Waste": "Kind", "Fix": "What to do"},
            no_data="No idle resources found."),
        text(f"{P}-hybrid-note", "Azure Hybrid Benefit only applies where you hold Windows Server or SQL Server "
             "licences with Software Assurance (or subscriptions); check with whoever manages licensing before "
             "switching it on. Windows client VMs (Azure Virtual Desktop) need the licence type *Windows_Client*.",
             "info"),
    ], tab="cost")


def security_tab():
    return group(f"{P}-tab-security", [
        text(f"{P}-sec-intro", "Security posture and privileged access by subscription. The **Platform health** "
             "Security tab has the alerts and recommendations behind these figures; the **Privileged access** "
             "workbook has activations, approvals and sign-ins."),
        arg(f"{P}-secure-score", "Defender for Cloud secure score", SECURE_SCORE_Q, width=50,
            formatters=[pct_bar("ScorePct")], labels={"ScorePct": "Score %", "Current": "Points", "Max": "Out of"},
            no_data="No secure score: Defender for Cloud is not reporting for the selected subscriptions."),
        arg(f"{P}-defender-plans", "Defender for Cloud plans", DEFENDER_PLANS_Q, width=50,
            formatters=[pct_bar("CoveragePct")],
            labels={"CoveragePct": "Plans on %", "PlansOn": "On", "PlansOff": "Off", "Off": "Plans off"},
            no_data="No Defender for Cloud plans found."),
        arg(f"{P}-high-recs", "High-severity recommendations by subscription", HIGH_RECS_Q, width=40,
            no_data="No unhealthy high-severity recommendations."),
        arg(f"{P}-privileged", "Roles that can grant access, by scope", PRIVILEGED_SUMMARY_Q, width=60,
            labels={"ScopeLevel": "Scope", "ServicePrincipals": "Service principals"}),
        arg(f"{P}-privileged-users", "Assigned to users directly, at subscription scope or above", PRIVILEGED_USERS_Q,
            width=50, labels={"ScopeLevel": "Scope level", "PrincipalId": "User object ID"},
            no_data="Every privileged role at subscription scope or above is assigned to a group or identity."),
        arg(f"{P}-custom-roles", "Custom roles with wildcard actions", CUSTOM_ROLES_Q, width=50,
            formatters=[status_fmt("Wildcard", warn=["Provider wildcards"], bad=["All actions (*)"])],
            labels={"Scopes": "Assignable scopes"}, no_data="No custom roles use wildcard actions."),
        text(f"{P}-sec-note", "Resource Graph has object IDs, not names: look a user up in Entra ID, or use the "
             "**Privileged access** workbook, which reads names from the sign-in logs. Assigning roles to groups "
             "(made eligible through PIM) keeps access reviewable.", "info"),
    ], tab="security")


def operations_tab():
    return group(f"{P}-tab-operations", [
        text(f"{P}-ops-intro", "How well the estate is run, by subscription: monitoring, patching, Advisor's "
             "high-impact issues, changes made by hand, and what Azure is retiring. The **Platform health** "
             "Monitoring and Governance tabs list the machines behind these figures."),
        arg(f"{P}-agents-pie", "Monitoring agent on machines", AGENTS_PIE_Q, vis="piechart", width=35,
            chart={"seriesLabelSettings": [{"seriesName": "Azure Monitor Agent", "color": "green"},
                                           {"seriesName": "Azure Monitor Agent and legacy agent", "color": "yellow"},
                                           {"seriesName": "Legacy agent only", "color": "orange"},
                                           {"seriesName": "No agent", "color": "redBright"}]},
            no_data="No VMs or Arc servers in the selected subscriptions."),
        arg(f"{P}-agents-subs", "Azure Monitor Agent coverage by subscription", AGENTS_BY_SUB_Q, width=65,
            formatters=[pct_bar("CoveragePct")],
            labels={"CoveragePct": "Coverage %", "LegacyOnly": "Legacy agent only", "NoAgent": "No agent"},
            no_data="No VMs or Arc servers in the selected subscriptions."),
        arg(f"{P}-patch-subs", "Patching by subscription (Azure Update Manager)", PATCH_BY_SUB_Q, width=50,
            formatters=[pct_bar("UpToDatePct")],
            labels={"UpToDatePct": "Up to date %", "Pending": "Critical or security due",
                    "NotAssessed": "Not assessed in 7 days", "Reboot": "Reboot pending"},
            no_data="No VMs or Arc servers in the selected subscriptions."),
        arg(f"{P}-advisor-subs", "Advisor high-impact recommendations by subscription", ADVISOR_BY_SUB_Q, width=50,
            no_data="Advisor has no high-impact recommendations."),
        arg(f"{P}-clients-pie", "Changes by tool (last 14 days)", CHANGE_CLIENT_PIE_Q, vis="piechart", width=35,
            no_data="No changes recorded in the last 14 days."),
        arg(f"{P}-portal-subs", "Changes made in the Azure portal, by subscription (last 14 days)", CHANGE_PORTAL_Q,
            width=65, formatters=[low_is_good("PortalPct", 20, 50)],
            labels={"PortalPct": "Made in the portal %", "Portal": "Portal changes"},
            no_data="No changes recorded in the last 14 days."),
        arg(f"{P}-retirements", "Azure retirements within 180 days (Azure Advisor)", RETIREMENTS_Q,
            formatters=[high_is_good("DaysLeft", 90, 30)],
            labels={"RetirementDate": "Retirement date", "DaysLeft": "Days left"},
            no_data="Advisor reports no retirements in the next 180 days."),
        arg(f"{P}-health", "Resources currently unavailable or degraded (Resource Health)", HEALTH_Q,
            formatters=[resource_link(), status_fmt("State", warn=["Degraded"], bad=["Unavailable"])],
            labels={"id": "Resource"}, no_data="Resource Health reports nothing unavailable or degraded."),
        text(f"{P}-ops-note", "A high share of changes made in the portal means changes are bypassing the "
             "pipelines (infrastructure as code) the platform relies on. Some portal changes are expected: "
             "incident fixes and sandbox subscriptions.", "info"),
    ], tab="operations")


def workbook():
    return notebook([
        text(f"{P}-header", "# Cloud Center of Excellence\n"
             "One scorecard for the team that sets cloud standards: governance and tagging, landing zone "
             "placement, security posture and privileged access, savings and idle resources, monitoring, patching "
             "and retirements, by subscription. Read from Azure Resource Graph: no workspace needed. You need "
             "**Reader** across the subscriptions (at the tenant root management group to see everything)."),
        global_params(),
        tabs(),
        scorecard_tab(),
        landing_zones_tab(),
        governance_tab(),
        cost_tab(),
        security_tab(),
        operations_tab(),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
