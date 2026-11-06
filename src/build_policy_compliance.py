"""Generates the Azure Policy compliance workbook: compliance, exemptions, frameworks, remediation and hygiene.

Run:  python src/build_policy_compliance.py
Out:  workbook/policy-compliance.workbook.json

Reports Azure Policy compliance across the tenant from Azure Resource Graph (no workspace needed): compliance by
state, category, effect, management group and subscription; per policy and per assignment; per resource; resources
reachable from the internet, read from their live configuration; the exemption register and what expires soon;
control pass/fail for any assigned initiative that maps policies to controls (CIS, NIST, ISO 27001, MCSB); the
remediation backlog; and governance gaps such as DoNotEnforce assignments, exclusions, deprecated policies and
unused custom definitions.

Every tab shares one set of filters (management group, subscription, resource category, policy category, effect,
initiative, compliance state). The filtered, enriched policy-state rows are built once in STATES and reused by
every query, so a change to the filters is made in one place.
"""

import json
import pathlib
import uuid

from build_workbook import notebook, write_workbook

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "policy-compliance.workbook.json"

ARG = {"queryType": 1, "resourceType": "microsoft.resources/tenants",
       "crossComponentResources": ["value::tenant"]}

def gid(seed):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "policy-workbook/" + seed))

# ---------------------------------------------------------------- KQL snippets
CATEGORY = r"""
| extend rp = tolower(tostring(split(resourceType, '/')[0]))
| extend ResourceCategory = case(
    rp in ('microsoft.compute', 'microsoft.classiccompute', 'microsoft.batch', 'microsoft.desktopvirtualization', 'microsoft.avs', 'microsoft.servicefabric', 'microsoft.virtualmachineimages', 'microsoft.devtestlab', 'microsoft.compute.admin'), 'Compute',
    rp in ('microsoft.containerservice', 'microsoft.containerregistry', 'microsoft.containerinstance', 'microsoft.app', 'microsoft.redhatopenshift', 'microsoft.kubernetesconfiguration'), 'Containers',
    rp in ('microsoft.network', 'microsoft.classicnetwork', 'microsoft.cdn', 'microsoft.networkfunction', 'microsoft.peering'), 'Networking',
    rp in ('microsoft.storage', 'microsoft.classicstorage', 'microsoft.storagesync', 'microsoft.netapp', 'microsoft.elasticsan', 'microsoft.storagecache', 'microsoft.datashare'), 'Storage',
    rp in ('microsoft.sql', 'microsoft.sqlvirtualmachine', 'microsoft.dbformysql', 'microsoft.dbforpostgresql', 'microsoft.dbformariadb', 'microsoft.documentdb', 'microsoft.cache', 'microsoft.azurearcdata'), 'Databases',
    rp in ('microsoft.synapse', 'microsoft.databricks', 'microsoft.datafactory', 'microsoft.hdinsight', 'microsoft.kusto', 'microsoft.streamanalytics', 'microsoft.purview', 'microsoft.powerbidedicated', 'microsoft.fabric', 'microsoft.datalakestore', 'microsoft.datalakeanalytics'), 'Analytics',
    rp in ('microsoft.cognitiveservices', 'microsoft.machinelearningservices', 'microsoft.search', 'microsoft.botservice'), 'AI + Machine Learning',
    rp in ('microsoft.web', 'microsoft.apimanagement', 'microsoft.signalrservice', 'microsoft.appconfiguration', 'microsoft.appplatform', 'microsoft.communication'), 'Web & App Services',
    rp in ('microsoft.servicebus', 'microsoft.eventhub', 'microsoft.eventgrid', 'microsoft.relay', 'microsoft.logic', 'microsoft.notificationhubs'), 'Integration',
    rp in ('microsoft.keyvault', 'microsoft.security', 'microsoft.managedidentity', 'microsoft.aad', 'microsoft.azureactivedirectory', 'microsoft.securityinsights', 'microsoft.attestation', 'microsoft.hardwaresecuritymodules'), 'Security & Identity',
    rp in ('microsoft.insights', 'microsoft.operationalinsights', 'microsoft.operationsmanagement', 'microsoft.automation', 'microsoft.alertsmanagement', 'microsoft.dashboard', 'microsoft.monitor', 'microsoft.maintenance', 'microsoft.guestconfiguration', 'microsoft.portal'), 'Monitoring & Management',
    rp in ('microsoft.recoveryservices', 'microsoft.dataprotection'), 'Backup & Recovery',
    rp in ('microsoft.devices', 'microsoft.iotcentral', 'microsoft.digitaltwins', 'microsoft.timeseriesinsights'), 'IoT',
    rp in ('microsoft.hybridcompute', 'microsoft.kubernetes', 'microsoft.azurestackhci', 'microsoft.connectedvmwarevsphere', 'microsoft.scvmm', 'microsoft.extendedlocation'), 'Hybrid & Arc',
    rp in ('microsoft.resources', 'microsoft.authorization', 'microsoft.management', 'microsoft.subscription', 'microsoft.policyinsights', 'microsoft.costmanagement', 'microsoft.billing'), 'Governance & Subscriptions',
    'Other')"""

CATEGORIES = ["Compute", "Containers", "Networking", "Storage", "Databases", "Analytics",
              "AI + Machine Learning", "Web & App Services", "Integration", "Security & Identity",
              "Monitoring & Management", "Backup & Recovery", "IoT", "Hybrid & Arc",
              "Governance & Subscriptions", "Other"]

EFFECTS = [("deny", "Deny"), ("audit", "Audit"), ("auditifnotexists", "AuditIfNotExists"),
           ("deployifnotexists", "DeployIfNotExists"), ("modify", "Modify"), ("append", "Append"),
           ("denyaction", "DenyAction"), ("manual", "Manual")]

# Subscriptions in scope (MG + subscription filters), with name and parent MG.
SUBSCOPE = r"""(
    resourcecontainers
    | where type =~ 'microsoft.resources/subscriptions'
    | where '*' in ({Subscription}) or subscriptionId in~ ({Subscription})
    | extend chain = properties.managementGroupAncestorsChain
    | extend chain = iff(array_length(chain) > 0, chain, pack_array(pack('name', '__none__', 'displayName', '(no management group)')))
    | mv-expand mg = chain
    | summarize mgHit = countif('*' in ({ManagementGroup}) or tostring(mg.name) in~ ({ManagementGroup})) by subscriptionId, subscriptionName = name, parentMG = tostring(chain[0].displayName)
    | where mgHit > 0
    | project subscriptionId, subscriptionName, parentMG
)"""

# Scope keys in scope: every in-scope subscription ID plus every management group above it.
# Used for items that can live at MG scope (assignments, exemptions, definitions).
SCOPEKEYS = r"""(
    resourcecontainers
    | where type =~ 'microsoft.resources/subscriptions'
    | where '*' in ({Subscription}) or subscriptionId in~ ({Subscription})
    | extend chain = properties.managementGroupAncestorsChain
    | extend chain = iff(array_length(chain) > 0, chain, pack_array(pack('name', '__none__')))
    | mv-expand mg = chain
    | extend mgName = tolower(tostring(mg.name))
    | summarize mgs = make_set(mgName), mgHit = countif('*' in ({ManagementGroup}) or mgName in~ ({ManagementGroup})) by subscriptionId
    | where mgHit > 0
    | extend keys = array_concat(pack_array(tolower(subscriptionId)), mgs)
    | mv-expand scopeKey = keys
    | project scopeKey = tostring(scopeKey)
    | distinct scopeKey
)"""

DEFS = r"""(
    policyresources
    | where type =~ 'microsoft.authorization/policydefinitions'
    | extend dn = tostring(properties.displayName)
    | project definitionId = tolower(id), policyName = dn,
              policyCategory = tostring(properties.metadata.category),
              policyType = tostring(properties.policyType),
              definitionStatus = case(dn startswith '[Deprecated', 'Deprecated', tostring(properties.metadata.deprecated) =~ 'true', 'Deprecated',
                                      dn startswith '[Preview', 'Preview', tostring(properties.metadata.preview) =~ 'true', 'Preview', 'GA')
)"""

SETDEFS = r"""(
    policyresources
    | where type =~ 'microsoft.authorization/policysetdefinitions'
    | project setDefinitionId = tolower(id), initiativeName = tostring(properties.displayName), initiativeType = tostring(properties.policyType)
)"""

# Base policy-state rows, fully filtered and enriched. Uses 2 joins (ARG allows 3).
STATES = r"""policyresources
| where type =~ 'microsoft.policyinsights/policystates'
| where '*' in ({Subscription}) or subscriptionId in~ ({Subscription})
| extend p = properties
| extend complianceState = tostring(p.complianceState),
         resourceId = tolower(tostring(p.resourceId)),
         resourceType = tolower(tostring(p.resourceType)),
         resourceGroup = tolower(tostring(p.resourceGroup)),
         resourceLocation = tolower(tostring(p.resourceLocation)),
         assignmentId = tolower(tostring(p.policyAssignmentId)),
         assignmentName = tostring(p.policyAssignmentName),
         definitionId = tolower(tostring(p.policyDefinitionId)),
         definitionRefId = tostring(p.policyDefinitionReferenceId),
         setDefinitionId = tolower(tostring(p.policySetDefinitionId)),
         effect = tolower(tostring(p.policyDefinitionAction)),
         groupNames = p.policyDefinitionGroupNames,
         evaluatedOn = todatetime(p.timestamp)
| project subscriptionId, complianceState, resourceId, resourceType, resourceGroup, resourceLocation, assignmentId, assignmentName,
          definitionId, definitionRefId, setDefinitionId, effect, groupNames, evaluatedOn""" + CATEGORY + r"""
| where '*' in ({ResourceCategory}) or ResourceCategory in ({ResourceCategory})
| where '*' in ({Effect}) or effect in~ ({Effect})
| where '*' in ({Initiatives}) or iff(isempty(setDefinitionId), 'none', setDefinitionId) in~ ({Initiatives})
| where '*' in ({ComplianceState}) or complianceState in~ ({ComplianceState})
| join kind=inner """ + SUBSCOPE + r""" on subscriptionId
| join kind=leftouter """ + DEFS + r""" on definitionId
| extend policyName = iff(isempty(policyName), iff(isempty(definitionRefId), tostring(split(definitionId, '/')[-1]), definitionRefId), policyName)
| where '*' in ({PolicyCategory}) or policyCategory in ({PolicyCategory})"""

# Same as STATES but with only one join, leaving room for two more.
STATES_LIGHT = STATES.replace("| join kind=leftouter " + DEFS + r""" on definitionId
| extend policyName = iff(isempty(policyName), iff(isempty(definitionRefId), tostring(split(definitionId, '/')[-1]), definitionRefId), policyName)
| where '*' in ({PolicyCategory}) or policyCategory in ({PolicyCategory})""", "")
assert STATES_LIGHT != STATES

PER_RESOURCE = r"""
| summarize nc = countif(complianceState =~ 'NonCompliant'), cmp = countif(complianceState =~ 'Compliant'), ex = countif(complianceState =~ 'Exempt')"""

PCT = "iff(Resources == 0, real(null), round(100.0 * (Resources - NonCompliant) / Resources, 1))"

ASSIGNMENTS = r"""policyresources
| where type =~ 'microsoft.authorization/policyassignments'
| extend p = properties
| extend assignmentId = tolower(id),
         assignmentName = iff(isempty(tostring(p.displayName)), name, tostring(p.displayName)),
         assignedDefinitionId = tolower(tostring(p.policyDefinitionId)),
         enforcementMode = tostring(p.enforcementMode),
         assignmentScope = tolower(tostring(p.scope)),
         identityType = tostring(identity.type),
         ncMessages = array_length(p.nonComplianceMessages),
         notScopes = p.notScopes,
         description = tostring(p.description)
| extend assignmentKind = iff(assignedDefinitionId has '/policysetdefinitions/', 'Initiative', 'Policy'),
         scopeLevel = case(assignmentScope has '/resourcegroups/', 'Resource group', assignmentScope startswith '/subscriptions/', 'Subscription', 'Management group'),
         scopeKey = iff(isnotempty(subscriptionId), tolower(subscriptionId), tolower(extract(@'(?i)managementgroups/([^/]+)', 1, assignmentScope)))
| where '*' in ({Initiatives}) or iff(assignmentKind == 'Initiative', assignedDefinitionId, 'none') in~ ({Initiatives})
| join kind=inner """ + SCOPEKEYS + r""" on scopeKey"""

EXEMPTIONS = r"""policyresources
| where type =~ 'microsoft.authorization/policyexemptions'
| extend p = properties
| extend exemptionId = tolower(id),
         exemptionName = iff(isempty(tostring(p.displayName)), name, tostring(p.displayName)),
         exemptionCategory = tostring(p.exemptionCategory),
         expiresOn = todatetime(p.expiresOn),
         assignmentId = tolower(tostring(p.policyAssignmentId)),
         refIds = p.policyDefinitionReferenceIds,
         description = tostring(p.description),
         metadata = tostring(p.metadata),
         exemptionScope = tolower(substring(id, 0, indexof(tolower(id), '/providers/microsoft.authorization/policyexemptions/')))
| extend scopeLevel = case(exemptionScope matches regex @'/resourcegroups/[^/]+/providers/', 'Resource',
                           exemptionScope has '/resourcegroups/', 'Resource group',
                           exemptionScope startswith '/subscriptions/', 'Subscription', 'Management group'),
         resourceType = tolower(extract(@'/providers/([^/]+/[^/]+)/[^/]+$', 1, exemptionScope)),
         daysToExpiry = iff(isnull(expiresOn), int(null), toint(datetime_diff('day', expiresOn, now())))
| extend expiryStatus = case(isnull(expiresOn), 'No expiry',
                             expiresOn < now(), 'Expired',
                             daysToExpiry <= 7, 'Expires within 7 days',
                             daysToExpiry <= 30, 'Expires within 30 days',
                             daysToExpiry <= 90, 'Expires within 90 days',
                             'More than 90 days'),
         scopeKey = iff(isnotempty(subscriptionId), tolower(subscriptionId), tolower(extract(@'(?i)managementgroups/([^/]+)', 1, exemptionScope)))""" + CATEGORY + r"""
| where '*' in ({ResourceCategory}) or scopeLevel != 'Resource' or ResourceCategory in ({ResourceCategory})
| join kind=inner """ + SCOPEKEYS + r""" on scopeKey
| join kind=leftouter (
    policyresources
    | where type =~ 'microsoft.authorization/policyassignments'
    | project assignmentId = tolower(id), assignmentName = iff(isempty(tostring(properties.displayName)), name, tostring(properties.displayName)), assignmentEnforcement = tostring(properties.enforcementMode), assignedDefinitionId = tolower(tostring(properties.policyDefinitionId))
) on assignmentId
| where '*' in ({Initiatives}) or iff(assignedDefinitionId has '/policysetdefinitions/', assignedDefinitionId, 'none') in~ ({Initiatives})
| join kind=leftouter (
    resourcecontainers
    | where type =~ 'microsoft.resources/subscriptions'
    | project subscriptionId, subscriptionName = name
) on subscriptionId
| extend assignmentStatus = iff(isempty(assignmentId1), 'Orphaned (assignment deleted)', 'OK'),
         policiesCovered = iff(array_length(refIds) > 0, strcat(tostring(array_length(refIds)), ' policy reference(s)'), 'Whole assignment')"""

EXEMPTIONS_TAB = EXEMPTIONS + r"""
| where '*' in ({ExpiryStatus}) or expiryStatus in ({ExpiryStatus})
| where '*' in ({ExemptionCategory}) or exemptionCategory in~ ({ExemptionCategory})"""

# ---------------------------------------------------------------- item helpers
def text(name, md, style=None):
    c = {"json": md}
    if style:
        c["style"] = style
    return {"type": 1, "content": c, "name": name}

def query(name, title, kql, viz="table", size=0, width=None, grid=None, chart=None,
          tiles=None, visible=None, nodata=None, export=None, extra=None):
    c = {"version": "KqlItem/1.0", "query": kql.strip(), "size": size, "title": title,
         "showExportToExcel": viz == "table", **ARG, "visualization": viz}
    if nodata:
        c["noDataMessage"] = nodata
    if grid:
        c["gridSettings"] = grid
    if chart:
        c["chartSettings"] = chart
    if tiles:
        c["tileSettings"] = tiles
    if export:
        field, param = export
        c["exportFieldName"] = field
        c["exportParameterName"] = param
        c["exportDefaultValue"] = "none"
    if extra:
        c.update(extra)
    item = {"type": 3, "content": c, "name": name}
    if width:
        item["customWidth"] = str(width)
    if visible:
        item["conditionalVisibility"] = visible
    return item

def group(name, items, tab=None, title=None):
    c = {"version": "NotebookGroup/1.0", "groupType": "editable", "items": items}
    if title:
        c["title"] = title
    g = {"type": 12, "content": c, "name": name}
    if tab:
        g["conditionalVisibility"] = {"parameterName": "selectedTab", "comparison": "isEqualTo", "value": tab}
    return g

def params(name, plist):
    return {"type": 9, "content": {"version": "KqlParameterItem/1.0", "parameters": plist,
                                   "style": "pills", **ARG}, "name": name}

def dropdown(name, label, kql=None, json_data=None, multi=True, all_opt=True, required=True, desc=None):
    p = {"id": gid("param/" + name), "version": "KqlParameterItem/1.0", "name": name, "label": label,
         "type": 2, "isRequired": required, "multiSelect": multi}
    if multi:
        p["quote"] = "'"
        p["delimiter"] = ","
    if kql:
        p["query"] = kql.strip()
        p.update(ARG)
    if json_data is not None:
        p["jsonData"] = json.dumps(json_data)
    ts = {"showDefault": False}
    if all_opt:
        ts["additionalResourceOptions"] = ["value::all"]
        ts["selectAllValue"] = "*"
        p["defaultValue"] = "value::all"
    p["typeSettings"] = ts
    if desc:
        p["description"] = desc
    return p

def static(values):
    return [{"value": v, "label": l} for v, l in values]

# formatter helpers
def bar_pct(col):
    return {"columnMatch": col, "formatter": 4, "formatOptions": {"min": 0, "max": 100, "palette": "redGreen"},
            "numberFormat": {"unit": 1, "options": {"style": "decimal", "maximumFractionDigits": 1}}}

def bar(col, palette="redBright"):
    return {"columnMatch": col, "formatter": 4, "formatOptions": {"palette": palette}}

def hidden(col):
    return {"columnMatch": col, "formatter": 5}

def res(col):
    return {"columnMatch": col, "formatter": 13, "formatOptions": {"linkTarget": "Resource", "showIcon": True}}

def dt(col):
    return {"columnMatch": col, "formatter": 6, "dateFormat": {"showUtcTime": None, "formatName": "shortDateTimePattern"}}

def date_only(col):
    return {"columnMatch": col, "formatter": 6, "dateFormat": {"showUtcTime": None, "formatName": "shortDatePattern"}}

def colors(col, rules, default="gray"):
    grid = [{"operator": "==", "thresholdValue": v, "representation": c, "text": "{0}{1}"} for v, c in rules]
    grid.append({"operator": "Default", "thresholdValue": None, "representation": default, "text": "{0}{1}"})
    return {"columnMatch": col, "formatter": 18, "formatOptions": {"thresholdsOptions": "colors", "thresholdsGrid": grid}}

def icons(col, rules, default="success"):
    grid = [{"operator": op, "thresholdValue": v, "representation": c, "text": "{0}{1}"} for op, v, c in rules]
    grid.append({"operator": "Default", "thresholdValue": None, "representation": default, "text": "{0}{1}"})
    return {"columnMatch": col, "formatter": 18, "formatOptions": {"thresholdsOptions": "icons", "thresholdsGrid": grid}}

def grid(formatters=None, labels=None, sort=None, row_limit=None, filter=True):
    g = {"formatters": formatters or [], "filter": filter}
    if row_limit:
        g["rowLimit"] = row_limit
    if labels:
        g["labelSettings"] = [{"columnId": k, "label": v} for k, v in labels.items()]
    if sort:
        col, desc = sort
        g["sortBy"] = [{"itemKey": col, "sortOrder": 2 if desc else 1}]
    return g

def tiles_settings():
    return {"titleContent": {"columnMatch": "Metric", "formatter": 1},
            "leftContent": {"columnMatch": "Value", "formatter": 12, "formatOptions": {"palette": "auto"},
                            "numberFormat": {"unit": 17, "options": {"style": "decimal", "maximumFractionDigits": 1}}},
            "subtitleContent": {"columnMatch": "Note", "formatter": 1},
            "showBorder": True, "size": "auto"}

def tiles_from(pairs):
    """pairs: list of (metric, valueExpr, note). Builds pack_array + mv-expand tail."""
    packs = ",\n    ".join(f"pack('Metric', '{m}', 'Value', todouble({v}), 'Note', '{n}', 'Order', {i})"
                           for i, (m, v, n) in enumerate(pairs))
    return f"""
| project Tiles = pack_array(
    {packs})
| mv-expand t = Tiles
| project Metric = tostring(t.Metric), Value = todouble(t.Value), Note = tostring(t.Note), Order = toint(t.Order)
| order by Order asc"""

STATE_COLORS = {"seriesLabelSettings": [
    {"seriesName": "Compliant", "color": "green"},
    {"seriesName": "Non-compliant", "color": "redBright"},
    {"seriesName": "Exempt", "color": "blue"},
    {"seriesName": "Unknown", "color": "gray"},
    {"seriesName": "Other", "color": "yellow"}]}

COMMON_LABELS = {"NonCompliant": "Non-compliant", "Compliance": "Compliance %", "LastEvaluated": "Last evaluated",
                 "subscriptionName": "Subscription", "parentMG": "Parent MG", "resourceGroup": "Resource group",
                 "resourceId": "Resource", "resourceType": "Resource type", "ResourceCategory": "Category",
                 "policyName": "Policy", "policyCategory": "Policy category", "policyType": "Type",
                 "assignmentId": "Assignment", "assignmentName": "Assignment", "effect": "Effect",
                 "evaluatedOn": "Evaluated", "complianceState": "State", "resourceLocation": "Location"}

def L(*keys, **extra):
    d = {k: COMMON_LABELS[k] for k in keys}
    d.update(extra)
    return d

# ================================================================ header + params
items = []
items.append(text("header", """# Azure Policy Compliance
Compliance, exemptions, regulatory frameworks, remediation and governance hygiene across the tenant, using **Azure Resource Graph**. Data is the latest evaluation result for each resource (Azure Policy re-evaluates about every 24 hours, and after a resource changes).

**Compliance %** is the share of evaluated resources with no non-compliant policy states. Exempt and unknown count as compliant, as in the Azure portal. You need **Reader** on the tenant root management group to see everything."""))

MG_Q = r"""resourcecontainers
| where type =~ 'microsoft.management/managementgroups'
| extend chain = properties.details.managementGroupAncestorsChain
| extend parent = iff(array_length(chain) > 0, tostring(chain[0].displayName), 'tenant root')
| project value = name, label = strcat(tostring(properties.displayName), '  (under ', parent, ')')
| order by label asc"""

SUB_Q = r"""resourcecontainers
| where type =~ 'microsoft.resources/subscriptions'
| extend chain = properties.managementGroupAncestorsChain
| extend chain = iff(array_length(chain) > 0, chain, pack_array(pack('name', '__none__')))
| mv-expand mg = chain
| where '*' in ({ManagementGroup}) or tostring(mg.name) in~ ({ManagementGroup})
| summarize by value = subscriptionId, label = name
| order by label asc"""

PCAT_Q = r"""policyresources
| where type =~ 'microsoft.authorization/policydefinitions'
| extend c = tostring(properties.metadata.category)
| where isnotempty(c)
| summarize by value = c, label = c
| order by label asc"""

items.append(params("globalParameters", [
    dropdown("ManagementGroup", "Management group", kql=MG_Q,
             desc="Includes everything under the selected management groups, plus policies inherited from above them."),
    dropdown("Subscription", "Subscription", kql=SUB_Q, desc="Lists only subscriptions under the selected management groups."),
    dropdown("ResourceCategory", "Resource category", json_data=static([(c, c) for c in CATEGORIES]),
             desc="Groups resource types by service area, based on the resource provider."),
    dropdown("PolicyCategory", "Policy category", kql=PCAT_Q, desc="Policy definition metadata category (e.g. Storage, Security Center)."),
    dropdown("Effect", "Effect", json_data=static(EFFECTS)),
    "__INITIATIVES__",
    dropdown("ComplianceState", "Compliance state", json_data=static([("Compliant", "Compliant"), ("NonCompliant", "Non-compliant"), ("Exempt", "Exempt"), ("Unknown", "Unknown")]),
             desc="Filters individual policy evaluation results (one per resource and policy). Choosing Non-compliant shows only failing results."),
]))

items.append({"type": 11, "content": {"version": "LinkItem/1.0", "style": "tabs", "links": [
    {"id": gid("tab/" + t), "cellValue": "selectedTab", "linkTarget": "parameter", "linkLabel": label,
     "subTarget": t, "style": "link"}
    for t, label in [("overview", "Overview"), ("policies", "Policies & assignments"), ("resources", "Resources"), ("exposure", "Public exposure"),
                     ("exemptions", "Exemptions"), ("regulatory", "Regulatory frameworks"),
                     ("remediation", "Remediation"), ("hygiene", "Governance hygiene")]]}, "name": "tabs"})

# ================================================================ OVERVIEW
ov = []
ov.append(query("ov-tiles-resources", "", STATES + PER_RESOURCE + r""" by resourceId
| summarize Resources = count(), NonCompliant = countif(nc > 0), Exempt = countif(nc == 0 and cmp == 0 and ex > 0)
| extend Compliance = """ + PCT + tiles_from([
    ("Resource compliance %", "Compliance", "of evaluated resources"),
    ("Resources evaluated", "Resources", "in current filter"),
    ("Non-compliant resources", "NonCompliant", "at least one failing policy"),
    ("Fully exempt resources", "Exempt", "exempt from every policy that applies")]),
    viz="tiles", size=3, tiles=tiles_settings()))

ov.append(query("ov-tiles-policies", "", STATES + r"""
| summarize NcPolicies = dcountif(definitionId, complianceState =~ 'NonCompliant'),
            Policies = dcount(definitionId),
            NcAssignments = dcountif(assignmentId, complianceState =~ 'NonCompliant'),
            Assignments = dcount(assignmentId),
            Subs = dcount(subscriptionId)""" + tiles_from([
    ("Non-compliant policies", "NcPolicies", "distinct definitions failing"),
    ("Policies evaluated", "Policies", "distinct definitions"),
    ("Non-compliant assignments", "NcAssignments", "of assignments evaluated"),
    ("Subscriptions", "Subs", "with evaluation results")]),
    viz="tiles", size=3, tiles=tiles_settings()))

ov.append(query("ov-tiles-exemptions", "", EXEMPTIONS + r"""
| summarize Active = countif(expiryStatus != 'Expired'),
            Expiring30 = countif(expiryStatus in ('Expires within 7 days', 'Expires within 30 days')),
            Expired = countif(expiryStatus == 'Expired'),
            NoExpiry = countif(expiryStatus == 'No expiry')""" + tiles_from([
    ("Active exemptions", "Active", "not yet expired"),
    ("Expiring in 30 days", "Expiring30", "review or renew"),
    ("Expired exemptions", "Expired", "no longer in effect - clean up"),
    ("Exemptions with no expiry", "NoExpiry", "permanent - review")]),
    viz="tiles", size=3, tiles=tiles_settings()))

ov.append(query("ov-state-pie", "Resources by compliance state", STATES + PER_RESOURCE + r""" by resourceId
| extend State = case(nc > 0, 'Non-compliant', cmp > 0, 'Compliant', ex > 0, 'Exempt', 'Unknown')
| summarize Resources = count() by State""", viz="piechart", width=33, chart=STATE_COLORS))

ov.append(query("ov-category-bar", "Resources by category", STATES + PER_RESOURCE + r""" by resourceId, ResourceCategory
| summarize Compliant = countif(nc == 0), NonCompliant = countif(nc > 0) by ResourceCategory
| order by NonCompliant desc""", viz="barchart", width=34,
    chart={"seriesLabelSettings": [{"seriesName": "Compliant", "color": "green"},
                                   {"seriesName": "NonCompliant", "label": "Non-compliant", "color": "redBright"}]}))

ov.append(query("ov-effect-pie", "Non-compliant resources by effect", STATES + r"""
| where complianceState =~ 'NonCompliant'
| summarize Resources = dcount(resourceId) by Effect = effect""", viz="piechart", width=33))

ov.append(query("ov-mg", "Compliance by management group (includes child groups)", STATES + PER_RESOURCE + r""" by resourceId, subscriptionId
| summarize Resources = count(), NonCompliant = countif(nc > 0) by subscriptionId
| join kind=inner (
    resourcecontainers
    | where type =~ 'microsoft.resources/subscriptions'
    | mv-expand mg = properties.managementGroupAncestorsChain
    | project subscriptionId, ManagementGroup = tostring(mg.displayName), mgName = tostring(mg.name)
) on subscriptionId
| summarize Subscriptions = dcount(subscriptionId), Resources = sum(Resources), NonCompliant = sum(NonCompliant) by ManagementGroup, mgName
| extend Compliance = """ + PCT + r"""
| project ManagementGroup, Subscriptions, Resources, NonCompliant, Compliance, mgName
| order by Resources desc""", width=50,
    grid=grid([bar_pct("Compliance"), bar("NonCompliant"), hidden("mgName")],
              L("NonCompliant", "Compliance", ManagementGroup="Management group"))))

ov.append(query("ov-subs", "Compliance by subscription", STATES + PER_RESOURCE + r""", lastEval = max(evaluatedOn) by resourceId, subscriptionId, subscriptionName, parentMG
| summarize Resources = count(), NonCompliant = countif(nc > 0), LastEvaluated = max(lastEval) by subscriptionId, subscriptionName, parentMG
| extend Compliance = """ + PCT + r"""
| project subscriptionName, parentMG, Resources, NonCompliant, Compliance, LastEvaluated, subscriptionId
| order by Compliance asc""", width=50,
    grid=grid([bar_pct("Compliance"), bar("NonCompliant"), dt("LastEvaluated"), hidden("subscriptionId")],
              L("subscriptionName", "parentMG", "NonCompliant", "Compliance", "LastEvaluated"))))

ov.append(query("ov-top-policies", "Top 15 non-compliant policies", STATES + r"""
| where complianceState =~ 'NonCompliant'
| summarize NonCompliant = dcount(resourceId), Assignments = dcount(assignmentId), Effects = make_set(effect) by policyName, policyCategory
| extend Effects = strcat_array(Effects, ', ')
| top 15 by NonCompliant desc""", width=50,
    grid=grid([bar("NonCompliant")], L("policyName", "policyCategory", NonCompliant="Non-compliant resources"))))

ov.append(query("ov-top-rgs", "Top 15 resource groups by non-compliant resources", STATES + PER_RESOURCE + r""" by resourceId, resourceGroup, subscriptionName
| summarize Resources = count(), NonCompliant = countif(nc > 0) by resourceGroup, subscriptionName
| extend Compliance = """ + PCT + r"""
| where NonCompliant > 0
| top 15 by NonCompliant desc""", width=50,
    grid=grid([bar_pct("Compliance"), bar("NonCompliant")], L("resourceGroup", "subscriptionName", "NonCompliant", "Compliance"))))

items.append(group("tab-overview", ov, tab="overview"))

# ================================================================ POLICIES & ASSIGNMENTS
po = []
po.append(text("po-intro", "Click a policy to list its non-compliant resources. The assignments table covers assignments at, above or below the selected scope."))
po.append(query("po-policies", "Policy compliance (click a row for details)", STATES + r"""
| summarize Resources = dcount(resourceId),
            NonCompliant = dcountif(resourceId, complianceState =~ 'NonCompliant'),
            Exempt = dcountif(resourceId, complianceState =~ 'Exempt'),
            Assignments = dcount(assignmentId),
            Effects = make_set(effect)
            by definitionId, policyName, policyCategory, policyType, definitionStatus
| extend Compliance = """ + PCT + r""", Effects = strcat_array(Effects, ', ')
| project policyName, policyCategory, policyType, definitionStatus, Effects, Assignments, Resources, NonCompliant, Exempt, Compliance, definitionId
| order by NonCompliant desc""",
    grid=grid([bar_pct("Compliance"), bar("NonCompliant"), hidden("definitionId"),
               colors("definitionStatus", [("Deprecated", "redBright"), ("Preview", "orange")], "green")],
              L("policyName", "policyCategory", "policyType", "NonCompliant", "Compliance", definitionStatus="Status"),
              row_limit=1000),
    export=("definitionId", "SelectedPolicy")))
po.append(query("po-policy-detail", "Non-compliant resources for the selected policy", STATES + r"""
| where definitionId == '{SelectedPolicy}' and complianceState =~ 'NonCompliant'
| project resourceId, resourceType, ResourceCategory, subscriptionName, resourceGroup, effect, assignmentId, evaluatedOn
| order by subscriptionName asc""",
    grid=grid([res("resourceId"), res("assignmentId"), dt("evaluatedOn")],
              L("resourceId", "resourceType", "ResourceCategory", "subscriptionName", "resourceGroup", "effect", "assignmentId", "evaluatedOn")),
    visible={"parameterName": "SelectedPolicy", "comparison": "isNotEqualTo", "value": "none"}))

po.append(query("po-category", "Non-compliant resources by policy category", STATES + r"""
| where complianceState =~ 'NonCompliant'
| summarize NonCompliant = dcount(resourceId) by policyCategory = iff(isempty(policyCategory), '(none)', policyCategory)
| top 20 by NonCompliant desc""", viz="barchart", width=50,
    chart={"seriesLabelSettings": [{"seriesName": "NonCompliant", "label": "Non-compliant resources", "color": "redBright"}]}))

po.append(query("po-scope-pie", "Assignments by scope level and type", ASSIGNMENTS + r"""
| summarize Assignments = count() by Scope = strcat(scopeLevel, ' - ', assignmentKind)""", viz="piechart", width=50))

po.append(query("po-assignments", "Policy assignments", ASSIGNMENTS + r"""
| join kind=leftouter (
    policyresources
    | where type =~ 'microsoft.policyinsights/policystates'
    | where '*' in ({Subscription}) or subscriptionId in~ ({Subscription})
    | join kind=inner """ + SUBSCOPE + r""" on subscriptionId
    | extend assignmentId = tolower(tostring(properties.policyAssignmentId)), resourceId = tolower(tostring(properties.resourceId)), complianceState = tostring(properties.complianceState)
    | summarize nc = countif(complianceState =~ 'NonCompliant') by assignmentId, resourceId
    | summarize Resources = count(), NonCompliant = countif(nc > 0) by assignmentId
) on assignmentId
| extend Resources = coalesce(Resources, 0), NonCompliant = coalesce(NonCompliant, 0)
| extend Compliance = """ + PCT + r""",
         Identity = iff(isempty(identityType) or identityType =~ 'None', 'None', identityType),
         Exclusions = array_length(notScopes),
         Messages = iff(ncMessages > 0, 'Yes', 'No')
| project assignmentName, assignmentKind, scopeLevel, assignmentScope, enforcementMode, Identity, Exclusions, Messages, Resources, NonCompliant, Compliance, assignmentId
| order by NonCompliant desc""",
    grid=grid([bar_pct("Compliance"), bar("NonCompliant"), res("assignmentId"),
               colors("enforcementMode", [("DoNotEnforce", "orange")], "green"),
               colors("Messages", [("No", "gray")], "blue")],
              L("assignmentName", "NonCompliant", "Compliance", assignmentId="Open", assignmentKind="Type", scopeLevel="Scope level",
                assignmentScope="Scope", enforcementMode="Enforcement", Messages="Non-compliance message"),
              row_limit=1000)))
items.append(group("tab-policies", po, tab="policies"))

# ================================================================ RESOURCES
rs = []
rs.append(query("rs-types", "Compliance by resource type", STATES + PER_RESOURCE + r""" by resourceId, resourceType, ResourceCategory
| summarize Resources = count(), NonCompliant = countif(nc > 0) by resourceType, ResourceCategory
| extend Compliance = """ + PCT + r"""
| order by NonCompliant desc""", width=50,
    grid=grid([bar_pct("Compliance"), bar("NonCompliant")], L("resourceType", "ResourceCategory", "NonCompliant", "Compliance"))))
rs.append(query("rs-location", "Non-compliant resources by region", STATES + PER_RESOURCE + r""" by resourceId, resourceLocation
| summarize Resources = count(), NonCompliant = countif(nc > 0) by resourceLocation = iff(isempty(resourceLocation), '(global)', resourceLocation)
| extend Compliance = """ + PCT + r"""
| order by NonCompliant desc""", width=50,
    grid=grid([bar_pct("Compliance"), bar("NonCompliant")], L("resourceLocation", "NonCompliant", "Compliance"))))
rs.append(query("rs-nc", "Resources (click a row to see every policy that applies to it)", STATES + r"""
| summarize NonCompliantPolicies = dcountif(definitionId, complianceState =~ 'NonCompliant'),
            CompliantN = countif(complianceState =~ 'Compliant'), ExemptN = countif(complianceState =~ 'Exempt'),
            Policies = make_set_if(policyName, complianceState =~ 'NonCompliant', 5),
            LastEvaluated = max(evaluatedOn)
            by resourceId, resourceType, ResourceCategory, subscriptionName, resourceGroup, resourceLocation
| extend Status = case(NonCompliantPolicies > 0, 'Non-compliant', CompliantN > 0, 'Compliant', ExemptN > 0, 'Exempt', 'Unknown'),
         Policies = strcat_array(Policies, ' | ')
| project Status, resourceId, resourceType, ResourceCategory, subscriptionName, resourceGroup, resourceLocation, NonCompliantPolicies, Policies, LastEvaluated, resourceKey = resourceId
| order by NonCompliantPolicies desc""",
    grid=grid([colors("Status", [("Non-compliant", "redBright"), ("Compliant", "green"), ("Exempt", "blue")]),
               res("resourceId"), bar("NonCompliantPolicies"), dt("LastEvaluated"), hidden("resourceKey")],
              L("resourceId", "resourceType", "ResourceCategory", "subscriptionName", "resourceGroup", "resourceLocation", "LastEvaluated",
                NonCompliantPolicies="Failing policies", Policies="Failing policies (first 5)"),
              row_limit=2000),
    export=("resourceKey", "SelectedResource")))
rs.append(query("rs-detail", "Policy states for the selected resource", STATES + r"""
| where resourceId == '{SelectedResource}'
| project complianceState, policyName, policyCategory, effect, assignmentId, definitionRefId, evaluatedOn
| order by complianceState desc""",
    grid=grid([icons("complianceState", [("==", "NonCompliant", "4"), ("==", "Exempt", "info"), ("==", "Unknown", "Unknown")]),
               res("assignmentId"), dt("evaluatedOn")],
              L("complianceState", "policyName", "policyCategory", "effect", "assignmentId", "evaluatedOn", definitionRefId="Reference ID")),
    visible={"parameterName": "SelectedResource", "comparison": "isNotEqualTo", "value": "none"}))
items.append(group("tab-resources", rs, tab="resources"))

# ================================================================ EXEMPTIONS
ex = []
ex.append(params("exemptionParameters", [
    dropdown("ExpiryStatus", "Expiry status", json_data=static([(s, s) for s in [
        "Expired", "Expires within 7 days", "Expires within 30 days", "Expires within 90 days",
        "More than 90 days", "No expiry"]])),
    dropdown("ExemptionCategory", "Exemption category", json_data=static([("Waiver", "Waiver"), ("Mitigated", "Mitigated")])),
]))
EXPIRY_COLORS = [("Expired", "redBright"), ("Expires within 7 days", "redBright"), ("Expires within 30 days", "orange"),
                 ("Expires within 90 days", "yellow"), ("More than 90 days", "green"), ("No expiry", "gray")]
ex.append(query("ex-tiles", "", EXEMPTIONS_TAB + r"""
| summarize Total = count(), Waiver = countif(exemptionCategory =~ 'Waiver'), Mitigated = countif(exemptionCategory =~ 'Mitigated'),
            Exp7 = countif(expiryStatus == 'Expires within 7 days'),
            Exp30 = countif(expiryStatus in ('Expires within 7 days', 'Expires within 30 days')),
            Expired = countif(expiryStatus == 'Expired'), NoExpiry = countif(expiryStatus == 'No expiry'),
            Orphaned = countif(assignmentStatus != 'OK')""" + tiles_from([
    ("Exemptions", "Total", "in current filter"),
    ("Waivers", "Waiver", "risk accepted"),
    ("Mitigated", "Mitigated", "compensating control"),
    ("Expiring in 7 days", "Exp7", "act now"),
    ("Expiring in 30 days", "Exp30", "plan renewal or fix"),
    ("Expired", "Expired", "delete or renew"),
    ("No expiry", "NoExpiry", "permanent exemptions"),
    ("Orphaned", "Orphaned", "assignment no longer exists")]),
    viz="tiles", size=3, tiles=tiles_settings()))
ex.append(query("ex-status-pie", "Exemptions by expiry status", EXEMPTIONS_TAB + r"""
| summarize Exemptions = count() by expiryStatus""", viz="piechart", width=33,
    chart={"seriesLabelSettings": [{"seriesName": s, "color": c} for s, c in EXPIRY_COLORS]}))
ex.append(query("ex-timeline", "Exemption expiries over the next 12 months", EXEMPTIONS_TAB + r"""
| where isnotnull(expiresOn) and expiresOn >= startofmonth(now()) and expiresOn < now() + 365d
| summarize Exemptions = count() by Month = format_datetime(startofmonth(expiresOn), 'yyyy-MM')
| order by Month asc""", viz="barchart", width=34,
    chart={"seriesLabelSettings": [{"seriesName": "Exemptions", "color": "orange"}]},
    nodata="No exemptions expire in the next 12 months."))
ex.append(query("ex-scope", "Exemptions by scope and subscription", EXEMPTIONS_TAB + r"""
| summarize Exemptions = count(), Waivers = countif(exemptionCategory =~ 'Waiver'), Mitigated = countif(exemptionCategory =~ 'Mitigated')
    by Subscription = iff(isempty(subscriptionName), '(management group)', subscriptionName), scopeLevel
| order by Exemptions desc""", width=33,
    grid=grid([bar("Exemptions", "blue")], {"scopeLevel": "Scope level"})))
ex.append(query("ex-soon", "Expiring within 30 days", EXEMPTIONS_TAB + r"""
| where daysToExpiry between (0 .. 30)
| project exemptionName, daysToExpiry, expiresOn, exemptionCategory, scopeLevel, exemptionScope, assignmentName, subscriptionName, exemptionId
| order by daysToExpiry asc""",
    grid=grid([icons("daysToExpiry", [("<=", "7", "4"), ("<=", "30", "2")]), date_only("expiresOn"),
               res("exemptionScope"), res("exemptionId")],
              {"exemptionName": "Exemption", "daysToExpiry": "Days left", "expiresOn": "Expires", "exemptionCategory": "Category",
               "scopeLevel": "Scope level", "exemptionScope": "Exempted scope", "assignmentName": "Assignment",
               "subscriptionName": "Subscription", "exemptionId": "Open"}),
    nodata="Nothing expires in the next 30 days."))
ex.append(query("ex-register", "Exemption register", EXEMPTIONS_TAB + r"""
| project exemptionName, expiryStatus, daysToExpiry, expiresOn, exemptionCategory, scopeLevel, exemptionScope, ResourceCategory = iff(scopeLevel == 'Resource', ResourceCategory, ''),
          assignmentName, assignmentStatus, policiesCovered, subscriptionName, description, metadata, exemptionId
| order by daysToExpiry asc nulls last""",
    grid=grid([colors("expiryStatus", EXPIRY_COLORS), date_only("expiresOn"), res("exemptionScope"), res("exemptionId"),
               colors("assignmentStatus", [("OK", "green")], "redBright"),
               colors("exemptionCategory", [("Waiver", "orange"), ("Mitigated", "blue")])],
              {"exemptionName": "Exemption", "expiryStatus": "Status", "daysToExpiry": "Days left", "expiresOn": "Expires",
               "exemptionCategory": "Category", "scopeLevel": "Scope level", "exemptionScope": "Exempted scope",
               "ResourceCategory": "Resource category", "assignmentName": "Assignment", "assignmentStatus": "Assignment status",
               "policiesCovered": "Covers", "subscriptionName": "Subscription", "description": "Justification",
               "metadata": "Metadata", "exemptionId": "Open"},
              row_limit=2000)))
ex.append(query("ex-exempt-assign", "Exempt resources by assignment (from evaluation results)", STATES_LIGHT + r"""
| where complianceState =~ 'Exempt'
| summarize ExemptResources = dcount(resourceId), Subscriptions = dcount(subscriptionId) by assignmentId
| order by ExemptResources desc""",
    grid=grid([res("assignmentId"), bar("ExemptResources", "blue")], {"assignmentId": "Assignment", "ExemptResources": "Exempt resources"})))
items.append(group("tab-exemptions", ex, tab="exemptions"))

# ================================================================ REGULATORY
INIT_Q = r"""policyresources
| where type =~ 'microsoft.authorization/policyassignments'
| extend setDefinitionId = tolower(tostring(properties.policyDefinitionId)), assignmentScope = tolower(tostring(properties.scope))
| where setDefinitionId has '/policysetdefinitions/'
| extend scopeKey = iff(isnotempty(subscriptionId), tolower(subscriptionId), tolower(extract(@'(?i)managementgroups/([^/]+)', 1, assignmentScope)))
| join kind=inner """ + SCOPEKEYS + r""" on scopeKey
| summarize by setDefinitionId
| join kind=leftouter """ + SETDEFS + r""" on setDefinitionId
| project value = setDefinitionId, label = iff(isempty(initiativeName), tostring(split(setDefinitionId, '/')[-1]), initiativeName)"""
INIT_GLOBAL_Q = INIT_Q + r"""
| union (
    policyresources
    | where type =~ 'microsoft.authorization/policyassignments'
    | where tolower(tostring(properties.policyDefinitionId)) has '/policydefinitions/'
    | take 1
    | project value = 'none', label = '(Standalone policies - not in an initiative)'
)
| order by label asc"""
INIT_Q = INIT_Q + r"""
| where '*' in ({Initiatives}) or value in~ ({Initiatives})
| order by label asc"""
_plist = items[1]["content"]["parameters"]
_plist[_plist.index("__INITIATIVES__")] = dropdown("Initiatives", "Initiative", kql=INIT_GLOBAL_Q,
    desc="Limits results to policies assigned through the selected initiatives. 'Standalone policies' covers policies assigned on their own.")
rg = []
rg.append(text("rg-intro", "Shows initiatives (policy sets) assigned in scope. Pick an initiative to see compliance for each control or group. Built-in regulatory initiatives such as CIS Azure Foundations, NIST SP 800-53 Rev. 5, ISO 27001 and Microsoft Cloud Security Benchmark map their policies to controls. Click a control to list its failing resources."))
rg.append(query("rg-initiatives", "Compliance by assigned initiative", STATES + r"""
| where isnotempty(setDefinitionId)
| summarize nc = countif(complianceState =~ 'NonCompliant') by setDefinitionId, resourceId
| summarize Resources = count(), NonCompliant = countif(nc > 0) by setDefinitionId
| join kind=leftouter """ + SETDEFS + r""" on setDefinitionId
| extend Initiative = iff(isempty(initiativeName), tostring(split(setDefinitionId, '/')[-1]), initiativeName),
         Compliance = """ + PCT + r"""
| project Initiative, initiativeType, Resources, NonCompliant, Compliance
| order by Compliance asc""",
    grid=grid([bar_pct("Compliance"), bar("NonCompliant")], L("NonCompliant", "Compliance", initiativeType="Type"))))
rg.append(params("regParameters", [dropdown("ControlInitiative", "Initiative (control view)", kql=INIT_Q, multi=False, all_opt=False, required=True)]))

CONTROLS = STATES + r"""
| where setDefinitionId == '{ControlInitiative}'
| mv-expand groupName = groupNames
| extend groupName = tolower(tostring(groupName))
| summarize nc = countif(complianceState =~ 'NonCompliant') by groupName, resourceId
| summarize Resources = count(), NonCompliant = countif(nc > 0) by groupName
| join kind=leftouter (
    policyresources
    | where type =~ 'microsoft.authorization/policysetdefinitions'
    | where tolower(id) == '{ControlInitiative}'
    | mv-expand g = properties.policyDefinitionGroups
    | project groupName = tolower(tostring(g.name)), Control = tostring(g.displayName), Domain = tostring(g.category)
) on groupName
| extend Control = iff(isempty(Control), groupName, Control),
         Compliance = """ + PCT + r""",
         Status = iff(NonCompliant > 0, 'Failing', 'Passing')"""
rg.append(query("rg-control-tiles", "", CONTROLS + r"""
| summarize Controls = count(), Passing = countif(Status == 'Passing'), Failing = countif(Status == 'Failing')
| extend PassRate = iff(Controls == 0, real(null), round(100.0 * Passing / Controls, 1))""" + tiles_from([
    ("Controls passing %", "PassRate", "controls with no failing resources"),
    ("Controls assessed", "Controls", "with evaluation results"),
    ("Passing controls", "Passing", ""),
    ("Failing controls", "Failing", "at least one non-compliant resource")]),
    viz="tiles", size=3, tiles=tiles_settings()))
rg.append(query("rg-domains", "Failing controls by domain", CONTROLS + r"""
| summarize Failing = countif(Status == 'Failing'), Passing = countif(Status == 'Passing') by Domain = iff(isempty(Domain), '(none)', Domain)
| order by Failing desc""", viz="barchart", width=40,
    chart={"seriesLabelSettings": [{"seriesName": "Failing", "color": "redBright"}, {"seriesName": "Passing", "color": "green"}]}))
rg.append(query("rg-controls", "Controls (click a row for failing resources)", CONTROLS + r"""
| project Status, Control, Domain, Resources, NonCompliant, Compliance, groupName
| order by NonCompliant desc""", width=60,
    grid=grid([colors("Status", [("Failing", "redBright")], "green"), bar_pct("Compliance"), bar("NonCompliant"),
               hidden("groupName")], L("NonCompliant", "Compliance"), row_limit=2000),
    export=("groupName", "SelectedControl")))
rg.append(query("rg-control-detail", "Failing resources for the selected control", STATES + r"""
| where setDefinitionId == '{ControlInitiative}' and complianceState =~ 'NonCompliant'
| mv-expand groupName = groupNames
| where tolower(tostring(groupName)) == '{SelectedControl}'
| project resourceId, resourceType, subscriptionName, resourceGroup, policyName, effect, evaluatedOn
| order by policyName asc""",
    grid=grid([res("resourceId"), dt("evaluatedOn")],
              L("resourceId", "resourceType", "subscriptionName", "resourceGroup", "policyName", "effect", "evaluatedOn")),
    visible={"parameterName": "SelectedControl", "comparison": "isNotEqualTo", "value": "none"}))
items.append(group("tab-regulatory", rg, tab="regulatory"))

# ================================================================ REMEDIATION
rm = []
rm.append(text("rm-intro", "Policies with **DeployIfNotExists** or **Modify** effects can fix non-compliant resources by running a remediation task. Assignments with no managed identity cannot remediate. Create tasks in [Policy > Remediation](https://portal.azure.com/#view/Microsoft_Azure_Policy/PolicyMenuBlade/~/Remediation). The other non-compliant resources need manual fixes or an exemption."))
rm.append(query("rm-tiles", "", STATES + r"""
| where complianceState =~ 'NonCompliant'
| summarize Remediable = dcountif(resourceId, effect in ('deployifnotexists', 'modify')),
            Manual = dcountif(resourceId, effect !in ('deployifnotexists', 'modify')),
            DenyNc = dcountif(resourceId, effect in ('deny', 'denyaction')),
            RemPolicies = dcountif(definitionId, effect in ('deployifnotexists', 'modify'))""" + tiles_from([
    ("Auto-remediable resources", "Remediable", "DeployIfNotExists / Modify"),
    ("Remediable policies", "RemPolicies", "with outstanding work"),
    ("Resources needing manual fixes", "Manual", "Audit / AuditIfNotExists / other"),
    ("Pre-existing Deny violations", "DenyNc", "created before the Deny policy")]),
    viz="tiles", size=3, tiles=tiles_settings()))
rm.append(query("rm-backlog", "Remediation backlog by assignment and policy", STATES + r"""
| where complianceState =~ 'NonCompliant' and effect in ('deployifnotexists', 'modify')
| summarize Resources = dcount(resourceId), Subscriptions = dcount(subscriptionId) by assignmentId, policyName, definitionRefId, effect
| join kind=leftouter (
    policyresources
    | where type =~ 'microsoft.authorization/policyassignments'
    | project assignmentId = tolower(id), assignmentDisplay = iff(isempty(tostring(properties.displayName)), name, tostring(properties.displayName)),
              identityType = tostring(identity.type), enforcementMode = tostring(properties.enforcementMode)
) on assignmentId
| extend Identity = iff(isempty(identityType) or identityType =~ 'None', 'Missing', identityType)
| project assignmentDisplay, policyName, effect, Resources, Subscriptions, Identity, enforcementMode, definitionRefId, assignmentId
| order by Resources desc""",
    grid=grid([bar("Resources", "orange"), colors("Identity", [("Missing", "redBright")], "green"),
               colors("enforcementMode", [("DoNotEnforce", "orange")], "green"), res("assignmentId")],
              L("policyName", "effect", assignmentDisplay="Assignment", Resources="Non-compliant resources",
                Identity="Managed identity", enforcementMode="Enforcement", definitionRefId="Reference ID (for remediation task)",
                assignmentId="Open")),
    nodata="No remediable non-compliance in the current filter."))
rm.append(query("rm-manual", "Top manual fixes (Audit / AuditIfNotExists / Deny)", STATES + r"""
| where complianceState =~ 'NonCompliant' and effect !in ('deployifnotexists', 'modify')
| summarize Resources = dcount(resourceId), ResourceTypes = make_set(resourceType, 5) by policyName, policyCategory, effect
| extend ResourceTypes = strcat_array(ResourceTypes, ', ')
| top 25 by Resources desc""",
    grid=grid([bar("Resources")], L("policyName", "policyCategory", "effect", Resources="Non-compliant resources", ResourceTypes="Resource types"))))
items.append(group("tab-remediation", rm, tab="remediation"))

# ================================================================ PUBLIC EXPOSURE
def RES(where, category_type="tolower(type)"):
    """Resources-table base: type filter, resource-category filter, MG/subscription scope."""
    return ("resources\n| where " + where + "\n| extend resourceType = " + category_type + CATEGORY +
            "\n| where '*' in ({ResourceCategory}) or ResourceCategory in ({ResourceCategory})"
            "\n| join kind=inner " + SUBSCOPE + " on subscriptionId")

# Generic PaaS exposure: anything exposing publicNetworkAccess or a network ACL default action.
PAAS_EXTEND = r"""
| extend pna = tostring(properties.publicNetworkAccess),
         defaultAction = coalesce(tostring(properties.networkAcls.defaultAction), tostring(properties.networkRuleSet.defaultAction)),
         privateEndpoints = array_length(properties.privateEndpointConnections)
| extend Exposure = case(pna =~ 'Disabled', 'Private only',
                         defaultAction =~ 'Deny', 'Public endpoint - firewall restricted',
                         defaultAction =~ 'Allow', 'Public endpoint - open to all networks',
                         pna =~ 'Enabled', 'Public endpoint - check firewall rules',
                         'Not determined')"""
PAAS_WHERE = ("(isnotempty(tostring(properties.publicNetworkAccess)) or isnotempty(tostring(properties.networkAcls.defaultAction)) "
              "or isnotempty(tostring(properties.networkRuleSet.defaultAction))) "
              "and type !~ 'microsoft.web/sites' and type !~ 'microsoft.containerservice/managedclusters'")

SENSITIVE = [(20, 21, "FTP"), (22, 22, "SSH"), (23, 23, "Telnet"), (135, 135, "RPC"), (137, 139, "NetBIOS"),
             (445, 445, "SMB"), (1433, 1434, "SQL Server"), (1521, 1521, "Oracle"), (2375, 2376, "Docker"),
             (3306, 3306, "MySQL"), (3389, 3389, "RDP"), (5432, 5432, "PostgreSQL"), (5985, 5986, "WinRM"),
             (6379, 6380, "Redis"), (9200, 9200, "Elasticsearch"), (27017, 27017, "MongoDB")]
HITS = "strcat(" + ", ".join(
    f"iff(lo <= {b} and hi >= {a}, '{n} {a if a == b else f'{a}-{b}'}; ', '')" for a, b, n in SENSITIVE) + ")"

NSG_RULES = RES("type =~ 'microsoft.network/networksecuritygroups'") + r"""
| extend attached = array_length(properties.subnets) + array_length(properties.networkInterfaces)
| mv-expand rule = properties.securityRules
| extend r = rule.properties
| where tostring(r.access) =~ 'Allow' and tostring(r.direction) =~ 'Inbound'
| extend source = iff(isnotempty(tostring(r.sourceAddressPrefix)), tostring(r.sourceAddressPrefix), strcat_array(r.sourceAddressPrefixes, ', '))
| extend srcList = strcat('"', tostring(r.sourceAddressPrefix), '"', tostring(r.sourceAddressPrefixes))
| where srcList contains '"*"' or srcList contains '"Internet"' or srcList contains '"0.0.0.0/0"' or srcList contains '"Any"'
| extend ports = iff(isnotempty(tostring(r.destinationPortRange)), pack_array(tostring(r.destinationPortRange)), r.destinationPortRanges)
| mv-expand port = ports
| extend port = tostring(port)
| extend lo = iff(port == '*', 0, toint(tostring(split(port, '-')[0]))),
         hi = iff(port == '*', 65535, toint(tostring(split(port, '-')[-1])))
| extend hits = """ + HITS + r"""
| summarize Ports = make_set(port), Hits = make_set_if(hits, isnotempty(hits)), AllPorts = countif(port == '*')
    by nsgId = id, nsgName = name, ruleName = tostring(rule.name), priority = toint(r.priority), source, attached, subscriptionName, resourceGroup
| extend Severity = case(AllPorts > 0, 'Critical - all ports', array_length(Hits) > 0, 'High - sensitive ports', 'Review - other ports'),
         Ports = strcat_array(Ports, ', '), SensitivePorts = strcat_array(Hits, ''),
         Attached = iff(attached > 0, 'Yes', 'No (unused NSG)')"""

SEVERITY_COLORS = [("Critical - all ports", "redBright"), ("High - sensitive ports", "orange"), ("Review - other ports", "yellow")]
EXPOSURE_COLORS = [("Public endpoint - open to all networks", "redBright"), ("Public API - open", "redBright"),
                   ("Public endpoint - check firewall rules", "orange"), ("Public API - IP restricted", "yellow"),
                   ("Public endpoint - firewall restricted", "yellow"), ("Private only", "green"), ("Private cluster", "green")]

px = []
px.append(text("px-intro", "Resources reachable from the internet, read from the live resource configuration (not from policy results). The **Management group**, **Subscription** and **Resource category** filters apply here. The policy filters (category, effect, initiative, state) apply only to the policy table at the bottom of this tab."))

px.append(query("px-tiles", "", RES(
    "type in~ ('microsoft.network/publicipaddresses', 'microsoft.network/networkinterfaces', 'microsoft.storage/storageaccounts', "
    "'microsoft.containerservice/managedclusters', 'microsoft.network/applicationgateways', 'microsoft.web/sites') or (" + PAAS_WHERE + ")",
    category_type="tolower(type)") + PAAS_EXTEND + r"""
| extend isPaas = type !~ 'microsoft.web/sites' and type !~ 'microsoft.containerservice/managedclusters' and (isnotempty(pna) or isnotempty(defaultAction))
| summarize PublicIPs = countif(type =~ 'microsoft.network/publicipaddresses'),
            Unattached = countif(type =~ 'microsoft.network/publicipaddresses' and isempty(tostring(properties.ipConfiguration.id)) and isempty(tostring(properties.natGateway.id))),
            VMsWithPip = dcountif(tolower(tostring(properties.virtualMachine.id)), type =~ 'microsoft.network/networkinterfaces' and tostring(properties.ipConfigurations) contains 'publicIPAddress' and isnotempty(tostring(properties.virtualMachine.id))),
            OpenPaas = countif(isPaas and Exposure == 'Public endpoint - open to all networks'),
            CheckPaas = countif(isPaas and Exposure == 'Public endpoint - check firewall rules'),
            AnonBlob = countif(type =~ 'microsoft.storage/storageaccounts' and tobool(properties.allowBlobPublicAccess) == true),
            AksOpen = countif(type =~ 'microsoft.containerservice/managedclusters' and tobool(properties.apiServerAccessProfile.enablePrivateCluster) != true and array_length(properties.apiServerAccessProfile.authorizedIPRanges) == 0),
            AppGwNoWaf = countif(type =~ 'microsoft.network/applicationgateways' and isempty(tostring(properties.firewallPolicy.id)) and tobool(properties.webApplicationFirewallConfiguration.enabled) != true)""" + tiles_from([
    ("Public IP addresses", "PublicIPs", "in scope"),
    ("VMs with a public IP", "VMsWithPip", "directly reachable"),
    ("PaaS open to all networks", "OpenPaas", "public, no firewall"),
    ("PaaS public - check firewall", "CheckPaas", "public, firewall rules not visible"),
    ("Anonymous blob access allowed", "AnonBlob", "storage accounts"),
    ("AKS public API, no IP limits", "AksOpen", "clusters"),
    ("App gateways without WAF", "AppGwNoWaf", "internet-facing L7"),
    ("Unattached public IPs", "Unattached", "clean up")]),
    viz="tiles", size=3, tiles=tiles_settings()))

px.append(query("px-nsg-tiles", "", NSG_RULES + r"""
| summarize Rules = count(), Critical = countif(Severity startswith 'Critical'), High = countif(Severity startswith 'High'), Nsgs = dcount(nsgId)""" + tiles_from([
    ("Internet-open inbound rules", "Rules", "source *, Internet or 0.0.0.0/0"),
    ("Rules open on all ports", "Critical", "critical"),
    ("Rules open on sensitive ports", "High", "SSH, RDP, SMB, databases..."),
    ("NSGs affected", "Nsgs", "")]),
    viz="tiles", size=3, tiles=tiles_settings()))

px.append(query("px-nsg", "NSG inbound rules open to the internet", NSG_RULES + r"""
| extend sevOrder = case(Severity startswith 'Critical', 1, Severity startswith 'High', 2, 3)
| project Severity, nsgName, ruleName, priority, source, Ports, SensitivePorts, Attached, subscriptionName, resourceGroup, nsgId, sevOrder
| order by sevOrder asc, priority asc""",
    grid=grid([colors("Severity", SEVERITY_COLORS), colors("Attached", [("Yes", "redBright")], "gray"), res("nsgId"), hidden("sevOrder")],
              L("subscriptionName", "resourceGroup", nsgName="NSG", ruleName="Rule", priority="Priority", source="Source",
                SensitivePorts="Sensitive ports", nsgId="Open"), row_limit=2000),
    nodata="No NSG rules allow inbound traffic from the internet."))

px.append(query("px-paas-pie", "PaaS network exposure", RES(PAAS_WHERE) + PAAS_EXTEND + r"""
| summarize Resources = count() by Exposure""", viz="piechart", width=33,
    chart={"seriesLabelSettings": [{"seriesName": s, "color": c} for s, c in EXPOSURE_COLORS] +
           [{"seriesName": "Not determined", "color": "gray"}]}))

px.append(query("px-pip-pie", "Public IPs by what they are attached to", RES("type =~ 'microsoft.network/publicipaddresses'") + r"""
| extend attachedTo = tolower(tostring(properties.ipConfiguration.id))
| summarize PublicIPs = count() by AttachedTo = case(attachedTo has '/networkinterfaces/', 'VM / NIC', attachedTo has '/loadbalancers/', 'Load balancer',
    attachedTo has '/applicationgateways/', 'Application gateway', attachedTo has '/azurefirewalls/', 'Azure Firewall',
    attachedTo has '/virtualnetworkgateways/', 'VPN / ExpressRoute gateway', attachedTo has '/bastionhosts/', 'Bastion',
    isnotempty(tostring(properties.natGateway.id)), 'NAT gateway', isempty(attachedTo), 'Unattached', 'Other')""",
    viz="piechart", width=33))

px.append(query("px-paas-type", "Open PaaS by resource type", RES(PAAS_WHERE) + PAAS_EXTEND + r"""
| where Exposure startswith 'Public'
| summarize Open = countif(Exposure == 'Public endpoint - open to all networks'), CheckFirewall = countif(Exposure == 'Public endpoint - check firewall rules'),
            Restricted = countif(Exposure == 'Public endpoint - firewall restricted') by resourceType
| order by Open desc""", width=34,
    grid=grid([bar("Open"), bar("CheckFirewall", "orange"), bar("Restricted", "yellow")],
              L("resourceType", CheckFirewall="Check firewall", Restricted="Firewall restricted"))))

px.append(query("px-paas", "PaaS services with a public endpoint", RES(PAAS_WHERE) + PAAS_EXTEND + r"""
| where Exposure startswith 'Public'
| extend sevOrder = case(Exposure endswith 'open to all networks', 1, Exposure endswith 'check firewall rules', 2, 3)
| project Exposure, id, resourceType, ResourceCategory, PublicNetworkAccess = iff(isempty(pna), '(default)', pna), FirewallDefault = defaultAction,
          PrivateEndpoints = coalesce(privateEndpoints, 0), subscriptionName, resourceGroup, location, sevOrder
| order by sevOrder asc, resourceType asc""",
    grid=grid([colors("Exposure", EXPOSURE_COLORS), res("id"), hidden("sevOrder")],
              L("resourceType", "ResourceCategory", "subscriptionName", "resourceGroup", id="Resource",
                PublicNetworkAccess="Public network access", FirewallDefault="Firewall default action",
                PrivateEndpoints="Private endpoints", location="Location"), row_limit=2000),
    nodata="No PaaS services expose a public endpoint."))

px.append(query("px-storage", "Storage account exposure and hardening", RES("type =~ 'microsoft.storage/storageaccounts'") + r"""
| extend AnonymousBlob = iff(tobool(properties.allowBlobPublicAccess) == true, 'Allowed', 'Blocked'),
         Network = case(tostring(properties.publicNetworkAccess) =~ 'Disabled', 'Private only',
                        tostring(properties.networkAcls.defaultAction) =~ 'Deny', 'Firewall restricted', 'All networks'),
         HttpsOnly = iff(tobool(properties.supportsHttpsTrafficOnly) == false, 'No', 'Yes'),
         MinTls = tostring(properties.minimumTlsVersion),
         SharedKey = iff(tobool(properties.allowSharedKeyAccess) == false, 'Disabled', 'Enabled')
| extend Issues = toint(AnonymousBlob == 'Allowed') + toint(Network == 'All networks') + toint(HttpsOnly == 'No') + toint(MinTls !in ('TLS1_2', 'TLS1_3'))
| where Issues > 0
| project id, AnonymousBlob, Network, HttpsOnly, MinTls, SharedKey, Issues, subscriptionName, resourceGroup
| order by Issues desc""", width=50,
    grid=grid([res("id"), colors("AnonymousBlob", [("Allowed", "redBright")], "green"),
               colors("Network", [("All networks", "redBright"), ("Firewall restricted", "yellow")], "green"),
               colors("HttpsOnly", [("No", "redBright")], "green"), colors("MinTls", [("TLS1_2", "green"), ("TLS1_3", "green")], "redBright"),
               colors("SharedKey", [("Enabled", "yellow")], "green"), bar("Issues")],
              L("subscriptionName", "resourceGroup", id="Storage account", AnonymousBlob="Anonymous blob access",
                HttpsOnly="HTTPS only", MinTls="Min TLS", SharedKey="Shared key access")),
    nodata="All storage accounts block anonymous access, restrict networks, and enforce HTTPS and TLS 1.2."))

px.append(query("px-vm-pip", "Virtual machines with public IPs", RES(
    "type =~ 'microsoft.network/networkinterfaces' and isnotempty(tostring(properties.virtualMachine.id))",
    category_type="'microsoft.compute/virtualmachines'") + r"""
| mv-expand ipc = properties.ipConfigurations
| extend pipId = tolower(tostring(ipc.properties.publicIPAddress.id))
| where isnotempty(pipId)
| project vmId = tostring(properties.virtualMachine.id), nic = id, NicNsg = iff(isempty(tostring(properties.networkSecurityGroup.id)), 'None on NIC', 'Yes'),
          pipId, subscriptionName, resourceGroup
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/publicipaddresses'
    | project pipId = tolower(id), PublicIP = tostring(properties.ipAddress), Sku = tostring(sku.name), Fqdn = tostring(properties.dnsSettings.fqdn)
) on pipId
| project vmId, PublicIP, Fqdn, Sku, NicNsg, nic, subscriptionName, resourceGroup""", width=50,
    grid=grid([res("vmId"), res("nic"), colors("NicNsg", [("None on NIC", "orange")], "green")],
              L("subscriptionName", "resourceGroup", vmId="Virtual machine", PublicIP="Public IP", Fqdn="DNS name",
                NicNsg="NIC NSG", nic="Network interface")),
    nodata="No virtual machines have a public IP."))

px.append(query("px-aks", "AKS API server exposure", RES("type =~ 'microsoft.containerservice/managedclusters'") + r"""
| extend ranges = array_length(properties.apiServerAccessProfile.authorizedIPRanges)
| extend Exposure = case(tobool(properties.apiServerAccessProfile.enablePrivateCluster) == true, 'Private cluster',
                         ranges > 0, 'Public API - IP restricted', 'Public API - open')
| project Exposure, id, AuthorizedRanges = coalesce(ranges, 0), KubernetesVersion = tostring(properties.kubernetesVersion),
          LocalAccounts = iff(tobool(properties.disableLocalAccounts) == true, 'Disabled', 'Enabled'), subscriptionName, resourceGroup
| order by Exposure desc""", width=50,
    grid=grid([colors("Exposure", EXPOSURE_COLORS), res("id"), colors("LocalAccounts", [("Enabled", "orange")], "green")],
              L("subscriptionName", "resourceGroup", id="Cluster", AuthorizedRanges="Authorized IP ranges",
                KubernetesVersion="Version", LocalAccounts="Local accounts")),
    nodata="No AKS clusters in scope."))

px.append(query("px-web", "App Service and Functions exposure", RES("type =~ 'microsoft.web/sites'") + r"""
| extend pna = tostring(properties.publicNetworkAccess)
| extend Exposure = iff(pna =~ 'Disabled', 'Private only', 'Public endpoint - check firewall rules'),
         HttpsOnly = iff(tobool(properties.httpsOnly) == true, 'Yes', 'No'),
         ClientCerts = iff(tobool(properties.clientCertEnabled) == true, 'Required', 'Off')
| project Exposure, id, Kind = kind, HttpsOnly, ClientCerts, DefaultHost = tostring(properties.defaultHostName), subscriptionName, resourceGroup
| order by Exposure asc, HttpsOnly asc""", width=50,
    grid=grid([colors("Exposure", EXPOSURE_COLORS), res("id"), colors("HttpsOnly", [("No", "redBright")], "green")],
              L("subscriptionName", "resourceGroup", id="App", HttpsOnly="HTTPS only", ClientCerts="Client certificates",
                DefaultHost="Default host name")),
    nodata="No App Service or Functions apps in scope."))

px.append(query("px-appgw", "Application gateways", RES("type =~ 'microsoft.network/applicationgateways'") + r"""
| extend WAF = case(isnotempty(tostring(properties.firewallPolicy.id)), 'WAF policy attached',
                    tobool(properties.webApplicationFirewallConfiguration.enabled) == true, strcat('WAF ', tostring(properties.webApplicationFirewallConfiguration.firewallMode)),
                    tostring(properties.sku.tier) has 'WAF', 'WAF SKU - not enabled', 'No WAF'),
         PublicFrontend = iff(tostring(properties.frontendIPConfigurations) contains 'publicIPAddress', 'Yes', 'No')
| project WAF, id, PublicFrontend, Sku = tostring(properties.sku.name), subscriptionName, resourceGroup
| order by WAF desc""", width=50,
    grid=grid([colors("WAF", [("No WAF", "redBright"), ("WAF SKU - not enabled", "redBright"), ("WAF Detection", "orange")], "green"),
               res("id"), colors("PublicFrontend", [("Yes", "orange")], "gray")],
              L("subscriptionName", "resourceGroup", id="Gateway", PublicFrontend="Public frontend")),
    nodata="No application gateways in scope."))

px.append(query("px-pips", "Public IP inventory", RES("type =~ 'microsoft.network/publicipaddresses'") + r"""
| extend attachedTo = tostring(properties.ipConfiguration.id)
| project id, PublicIP = tostring(properties.ipAddress), Fqdn = tostring(properties.dnsSettings.fqdn),
          AttachedTo = iff(isempty(attachedTo), iff(isnotempty(tostring(properties.natGateway.id)), tostring(properties.natGateway.id), ''), extract(@'(?i)^(/subscriptions/[^/]+/resourcegroups/[^/]+/providers/[^/]+/[^/]+/[^/]+)', 1, attachedTo)),
          Status = iff(isempty(attachedTo) and isempty(tostring(properties.natGateway.id)), 'Unattached', 'In use'),
          Sku = tostring(sku.name), Allocation = tostring(properties.publicIPAllocationMethod), DdosProtection = tostring(properties.ddosSettings.protectionMode),
          subscriptionName, resourceGroup, location
| order by Status desc""", width=50,
    grid=grid([res("id"), res("AttachedTo"), colors("Status", [("Unattached", "orange")], "blue")],
              L("subscriptionName", "resourceGroup", id="Public IP", PublicIP="IP address", Fqdn="DNS name",
                AttachedTo="Attached to", DdosProtection="DDoS protection", location="Location"), row_limit=2000)))

px.append(query("px-policies", "Exposure-related policy compliance", STATES + r"""
| where policyName has_any ('public', 'internet', 'private link', 'private endpoint', 'firewall', 'network access', 'anonymous', 'management port', 'just-in-time', 'authorized IP', 'WAF', 'Web Application Firewall')
| summarize Resources = dcount(resourceId), NonCompliant = dcountif(resourceId, complianceState =~ 'NonCompliant'), Effects = make_set(effect) by policyName, policyCategory
| extend Compliance = """ + PCT + r""", Effects = strcat_array(Effects, ', ')
| order by NonCompliant desc""",
    grid=grid([bar_pct("Compliance"), bar("NonCompliant")], L("policyName", "policyCategory", "NonCompliant", "Compliance")),
    nodata="No exposure-related policies are assigned in scope. Consider assigning the built-in 'Microsoft cloud security benchmark' initiative."))

items.append(group("tab-exposure", px, tab="exposure"))

# ================================================================ HYGIENE
hy = []
hy.append(text("hy-intro", "Configuration gaps that weaken your policy controls or leave stale objects behind."))
hy.append(query("hy-dne", "Assignments in DoNotEnforce mode (audit only, Deny/Modify not applied)", ASSIGNMENTS + r"""
| where enforcementMode =~ 'DoNotEnforce'
| project assignmentName, assignmentKind, scopeLevel, assignmentScope, description, assignmentId""", width=50,
    grid=grid([res("assignmentId")], {"assignmentName": "Assignment", "assignmentKind": "Type", "scopeLevel": "Scope level",
                                      "assignmentScope": "Scope", "assignmentId": "Open"}),
    nodata="All assignments are enforced."))
hy.append(query("hy-nomsg", "Assignments with no non-compliance message", ASSIGNMENTS + r"""
| where ncMessages == 0 or isnull(ncMessages)
| project assignmentName, assignmentKind, scopeLevel, assignmentScope, assignmentId""", width=50,
    grid=grid([res("assignmentId")], {"assignmentName": "Assignment", "assignmentKind": "Type", "scopeLevel": "Scope level",
                                      "assignmentScope": "Scope", "assignmentId": "Open"}),
    nodata="Every assignment has a non-compliance message."))
hy.append(query("hy-notscopes", "Assignment exclusions (notScopes)", ASSIGNMENTS + r"""
| where array_length(notScopes) > 0
| mv-expand excluded = notScopes
| project assignmentName, scopeLevel, assignmentScope, ExcludedScope = tostring(excluded), assignmentId""", width=50,
    grid=grid([res("assignmentId")], {"assignmentName": "Assignment", "scopeLevel": "Scope level", "assignmentScope": "Scope",
                                      "ExcludedScope": "Excluded scope", "assignmentId": "Open"}),
    nodata="No assignments have exclusions."))
hy.append(query("hy-deprecated", "Deprecated or preview policies being evaluated", STATES + r"""
| where definitionStatus in ('Deprecated', 'Preview')
| summarize Resources = dcount(resourceId), NonCompliant = dcountif(resourceId, complianceState =~ 'NonCompliant'), Assignments = dcount(assignmentId) by definitionStatus, policyName, policyCategory
| order by definitionStatus asc, Resources desc""", width=50,
    grid=grid([colors("definitionStatus", [("Deprecated", "redBright"), ("Preview", "orange")])],
              L("policyName", "policyCategory", "NonCompliant", definitionStatus="Status")),
    nodata="No deprecated or preview policies are in use."))
hy.append(query("hy-cleanup", "Exemptions to clean up (expired or orphaned)", EXEMPTIONS + r"""
| where expiryStatus == 'Expired' or assignmentStatus != 'OK'
| project exemptionName, expiryStatus, expiresOn, assignmentStatus, scopeLevel, exemptionScope, exemptionId""", width=50,
    grid=grid([colors("expiryStatus", EXPIRY_COLORS), date_only("expiresOn"), colors("assignmentStatus", [("OK", "green")], "redBright"),
               res("exemptionScope"), res("exemptionId")],
              {"exemptionName": "Exemption", "expiryStatus": "Status", "expiresOn": "Expires", "assignmentStatus": "Assignment",
               "scopeLevel": "Scope level", "exemptionScope": "Exempted scope", "exemptionId": "Open"}),
    nodata="No expired or orphaned exemptions."))
hy.append(query("hy-nosubs", "Subscriptions with no policy evaluation results", r"""resourcecontainers
| where type =~ 'microsoft.resources/subscriptions'
| join kind=inner """ + SUBSCOPE + r""" on subscriptionId
| join kind=leftouter (
    policyresources
    | where type =~ 'microsoft.policyinsights/policystates'
    | summarize States = count() by subscriptionId
) on subscriptionId
| where isempty(subscriptionId2)
| project subscriptionName, parentMG, State = tostring(properties.state), subscriptionId""", width=50,
    grid=grid([], {"subscriptionName": "Subscription", "parentMG": "Parent MG", "subscriptionId": "Subscription ID"}),
    nodata="Every subscription in scope has evaluation results."))
hy.append(query("hy-unused", "Custom policy definitions not assigned or used in any initiative", r"""policyresources
| where type =~ 'microsoft.authorization/policydefinitions'
| where properties.policyType =~ 'Custom'
| extend definitionId = tolower(id),
         scopeKey = iff(isnotempty(subscriptionId), tolower(subscriptionId), tolower(extract(@'(?i)managementgroups/([^/]+)', 1, id)))
| join kind=inner """ + SCOPEKEYS + r""" on scopeKey
| join kind=leftouter (
    policyresources
    | where type =~ 'microsoft.authorization/policyassignments'
    | project definitionId = tolower(tostring(properties.policyDefinitionId))
    | union (
        policyresources
        | where type =~ 'microsoft.authorization/policysetdefinitions'
        | where properties.policyType =~ 'Custom'
        | mv-expand d = properties.policyDefinitions
        | project definitionId = tolower(tostring(d.policyDefinitionId))
    )
    | summarize References = count() by definitionId
) on definitionId
| where isempty(definitionId1)
| project Policy = tostring(properties.displayName), Category = tostring(properties.metadata.category), Mode = tostring(properties.mode), DefinedAt = substring(id, 0, indexof(tolower(id), '/providers/microsoft.authorization/policydefinitions/')), id""",
    grid=grid([res("id")], {"DefinedAt": "Defined at", "id": "Open"}),
    nodata="Every custom definition is in use."))
items.append(group("tab-hygiene", hy, tab="hygiene"))

items.append(text("footer", "Data source: Azure Resource Graph (latest policy state for each resource). Resource Graph keeps no history, so for compliance trends export policy states to Log Analytics or Event Grid.", style="info"))

write_workbook(OUT, notebook(items))
