"""Generates the "why was this request refused?" workbook: Azure Policy denials first, then everything else.

Run:  python src/build_policy_denials.py
Out:  workbook/policy-denials.workbook.json

Answers "why was my deployment denied?" From the activity log in Log Analytics: every refused request in the
time range, sorted into policy, permissions, locks, quota and template errors, and for a policy denial the
assignment, the policy and the field values that failed it. From Resource Graph (no workspace needed): the policies
that can deny in the selected subscriptions, and for one assignment its scope, exclusions, enforcement mode, the
effect each policy in it resolves to, its exemptions and the resources it finds non-compliant. Built from the
helpers in build_workbook.py so the workbooks look alike.
"""

import pathlib

from build_workbook import (DAY_MS, WORKSPACE_SET, WORKSPACE_UNSET, arg, big_number_tiles, export_row,
                            free_text_param, gid, la, notebook, params, resource_link, status_fmt, subscription_param,
                            text, time_param, when_set, workspace_param, write_workbook)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "policy-denials.workbook.json"

P = "pol"
HOUR_MS = 3600000

# ---------------------------------------------------------------------------
# Refused requests (activity log)
# ---------------------------------------------------------------------------

# The search box matches a correlation id exactly, or part of the resource id, the caller or the error text.
SEARCH = r"""let Search = trim(@'\s+', @'{Search}');"""
SEARCH_WHERE = "| where isempty(Search) or CorrelationId == Search or _ResourceId contains Search or Caller contains Search or Message contains Search"

# Failed writes, deletes and actions, one row per request (a request logs Started, Accepted and Failed under one
# correlation id). Every error code in the message is collected: a deployment fails with DeploymentFailed or
# InvalidTemplateDeployment and names the real cause in its details. The message is JSON, sometimes with its inner
# quotes escaped, so the codes are read with a pattern that allows for both.
REFUSALS = SEARCH + r"""
let Refusals = AzureActivity
| where TimeGenerated {TimeRange}
| where CategoryValue =~ 'Administrative' and ActivityStatusValue in~ ('Failure', 'Failed')
| extend props = column_ifexists('Properties_d', dynamic(null))
| extend Message = tostring(props.statusMessage), StatusCode = tostring(props.statusCode)
SEARCH_WHERE
| summarize arg_max(TimeGenerated, Message, StatusCode) by CorrelationId, OperationNameValue, _ResourceId, Caller, SubscriptionId
| extend Codes = extract_all(@'code[\\"]*\s*:\s*[\\"]*([A-Za-z]+)', Message)
| extend Code = tostring(set_difference(Codes, dynamic(['DeploymentFailed', 'InvalidTemplateDeployment', 'Forbidden', 'Conflict', 'BadRequest']))[0])
| extend Code = coalesce(Code, tostring(Codes[0]), StatusCode)
| extend Reason = case(
    Message has 'RequestDisallowedByPolicy' or Message has 'disallowed by policy', 'Policy',
    Message has 'RequestDisallowedByAzure', 'Azure restriction (region or service)',
    Message has_any ('AuthorizationFailed', 'LinkedAuthorizationFailed', 'LinkedAccessCheckFailed', 'InvalidAuthenticationToken'), 'Permissions',
    Message has 'ScopeLocked', 'Resource lock',
    Message has_any ('QuotaExceeded', 'ResourceQuotaExceeded', 'SkuNotAvailable', 'ZonalAllocationFailed', 'AllocationFailed',
        'OverconstrainedAllocationRequest', 'MaxStorageAccountsCountPerSubscriptionExceeded') or Message has 'quota', 'Quota or capacity',
    Message has_any ('InvalidTemplate', 'InvalidParameter', 'InvalidRequestContent', 'InvalidResourceReference', 'ResourceNotFound',
        'ParentResourceNotFound', 'NoRegisteredProviderFound', 'MissingSubscriptionRegistration', 'LocationNotAvailableForResourceType'), 'Template or request',
    Message has_any ('AnotherOperationInProgress', 'Conflict', 'ResourceGroupBeingDeleted'), 'Conflict with another operation',
    'Other')
| extend err = parse_json(Message).error
| extend Detail = substring(coalesce(tostring(err.details[0].message), tostring(err.message), tostring(parse_json(Message).message), Message), 0, 500),
    Action = extract(@"perform action '([^']+)'", 1, Message), Scope = extract(@"over scope '([^']+)'", 1, Message);
""".replace("SEARCH_WHERE", SEARCH_WHERE)

REASONS = ["Policy", "Azure restriction (region or service)", "Permissions", "Resource lock", "Quota or capacity",
           "Template or request", "Conflict with another operation", "Other"]

REFUSAL_TILES_Q = REFUSALS + """
Refusals
| summarize Requests = count(), Callers = dcount(Caller), Last = max(TimeGenerated) by Reason
| project Reason, Requests, Detail = strcat(Callers, ' callers · last ', format_datetime(Last, 'yyyy-MM-dd HH:mm')),
    State = iff(Reason == 'Policy', 'Unavailable', 'Degraded')
| order by Requests desc
"""

REFUSALS_Q = REFUSALS + """
Refusals
| project Time = TimeGenerated, Reason, Code, Operation = OperationNameValue, Resource = _ResourceId, Caller, Detail,
    Action, Scope, CorrelationId
| order by Time desc
| take 500
"""

# The policy event for each denial (category Policy, operation .../policies/deny/action or denyAction/action) names
# every assignment that denied it. The failed request with the same correlation id carries the evaluation details:
# which fields had which values, against what the policy expects.
DENIALS_Q = SEARCH + r"""
let Why = AzureActivity
| where TimeGenerated {TimeRange}
| where CategoryValue =~ 'Administrative' and ActivityStatusValue in~ ('Failure', 'Failed')
| extend Message = tostring(column_ifexists('Properties_d', dynamic(null)).statusMessage)
| where Message has 'RequestDisallowedByPolicy'
| extend err = parse_json(Message).error
| mv-expand d = iff(array_length(err.details) > 0, err.details, pack_array(err))
| mv-expand ai = d.additionalInfo
| where tostring(ai.type) == 'PolicyViolation'
| mv-expand ex = ai.info.evaluationDetails.evaluatedExpressions
| extend Check = strcat(tostring(ex.path), ' = ', tostring(ex.expressionValue), ' (', tostring(ex.operator), ' ', tostring(ex.targetValue), ')')
| summarize Why = strcat_array(make_set_if(Check, isnotempty(tostring(ex.path)), 10), ' · ')
    by CorrelationId, AssignmentId = tolower(tostring(ai.info.policyAssignmentId)), ReferenceId = tostring(ai.info.policyDefinitionReferenceId);
AzureActivity
| where TimeGenerated {TimeRange}
| where CategoryValue =~ 'Policy' and OperationNameValue contains 'deny'
| extend Message = ''
""" + SEARCH_WHERE + r"""
| extend props = column_ifexists('Properties_d', dynamic(null))
| mv-expand p = parse_json(tostring(props.policies))
| extend AssignmentId = tolower(tostring(p.policyAssignmentId)), ReferenceId = tostring(p.policyDefinitionReferenceId)
| summarize arg_max(TimeGenerated, p, Caller, OperationNameValue) by CorrelationId, _ResourceId, AssignmentId, ReferenceId
| join kind=leftouter Why on CorrelationId, AssignmentId, ReferenceId
| project Time = TimeGenerated, Resource = _ResourceId, Caller,
    Assignment = coalesce(tostring(p.policyAssignmentDisplayName), tostring(p.policyAssignmentName)),
    Policy = coalesce(tostring(p.policyDefinitionDisplayName), tostring(p.policyDefinitionName)),
    Initiative = coalesce(tostring(p.policySetDefinitionDisplayName), tostring(p.policySetDefinitionName)),
    ReferenceId, Effect = tostring(p.policyDefinitionEffect), Why,
    AssignmentScope = tostring(p.policyAssignmentScope), AssignmentId, CorrelationId
| order by Time desc
| take 500
"""

# ---------------------------------------------------------------------------
# Policies that deny, and one assignment in detail (Resource Graph)
# ---------------------------------------------------------------------------

SEARCH_ARG = r"(isempty(trim(@'\s+', @'{Search}')) or tolower(tostring(properties.resourceId)) contains tolower(trim(@'\s+', @'{Search}')))"

# Compliance results record the effect each policy resolved to, so an effect set by a parameter is already worked
# out. A policy that denies shows here once it has evaluated at least one resource.
DENY_POLICIES_Q = f"""
policyresources
| where type =~ 'microsoft.policyinsights/policystates'
| where tostring(properties.policyDefinitionAction) in~ ('deny', 'denyaction')
| where {SEARCH_ARG}
| summarize NonCompliant = countif(tostring(properties.complianceState) =~ 'NonCompliant'), Resources = dcount(tostring(properties.resourceId)),
    Effect = take_any(tostring(properties.policyDefinitionAction)), Scope = take_any(tostring(properties.policyAssignmentScope))
    by AssignmentId = tolower(tostring(properties.policyAssignmentId)), DefinitionId = tolower(tostring(properties.policyDefinitionId)),
    ReferenceId = tostring(properties.policyDefinitionReferenceId)
| join kind=leftouter (
    policyresources
    | where type =~ 'microsoft.authorization/policyassignments'
    | project AssignmentId = tolower(id), Assignment = coalesce(tostring(properties.displayName), name),
        Enforcement = tostring(properties.enforcementMode)
  ) on AssignmentId
| join kind=leftouter (
    policyresources
    | where type =~ 'microsoft.authorization/policydefinitions'
    | project DefinitionId = tolower(id), Policy = coalesce(tostring(properties.displayName), name)
  ) on DefinitionId
| project Assignment, Policy, Effect, Enforcement, NonCompliant, Resources, Scope, ReferenceId, AssignmentId
| order by NonCompliant desc, Assignment asc
"""

ASSIGNMENT_PICK_Q = """
policyresources
| where type =~ 'microsoft.authorization/policyassignments'
| project value = tolower(id), label = strcat(coalesce(tostring(properties.displayName), name), ' (', tostring(properties.scope), ')')
| order by label asc
"""

ASSIGNMENT = "policyresources\n| where type =~ 'microsoft.authorization/policyassignments' and tolower(id) == '{Assignment}'"

ASSIGNMENT_Q = ASSIGNMENT + """
| extend defId = tolower(tostring(properties.policyDefinitionId))
| join kind=leftouter (
    policyresources
    | where type in~ ('microsoft.authorization/policydefinitions', 'microsoft.authorization/policysetdefinitions')
    | project defId = tolower(id), Definition = coalesce(tostring(properties.displayName), name),
        Kind = iff(type endswith 'setdefinitions', 'Initiative', 'Policy')
  ) on defId
| project Assignment = coalesce(tostring(properties.displayName), name), Kind, Definition,
    Scope = tostring(properties.scope), Excluded = strcat_array(properties.notScopes, ', '),
    Enforcement = tostring(properties.enforcementMode),
    Overrides = iff(array_length(properties.overrides) > 0, tostring(properties.overrides), ''),
    Selectors = iff(array_length(properties.resourceSelectors) > 0, tostring(properties.resourceSelectors), ''),
    Message = tostring(properties.nonComplianceMessages[0].message),
    Identity = tostring(identity.type), CreatedOn = todatetime(properties.metadata.createdOn),
    UpdatedOn = todatetime(properties.metadata.updatedOn)
"""

# Each policy in the assignment and the effect it resolves to. An initiative passes each policy its effect as a
# value or as "[parameters('name')]", and that parameter is set on the assignment or falls back to the initiative's
# default. A policy given no effect uses its own default, or the literal in its rule. A single policy assignment is
# handled as an initiative of one. Overrides on the assignment can change the effect again (see the row above).
EFFECTS_Q = ASSIGNMENT + r"""
| project aParams = properties.parameters, defId = tolower(tostring(properties.policyDefinitionId))
| join kind=inner (
    policyresources
    | where type in~ ('microsoft.authorization/policydefinitions', 'microsoft.authorization/policysetdefinitions')
    | project defId = tolower(id), def = properties, isSet = type endswith 'setdefinitions'
  ) on defId
| extend members = iff(isSet, def.policyDefinitions,
    pack_array(pack('policyDefinitionId', defId, 'policyDefinitionReferenceId', '', 'parameters',
        pack('effect', pack('value', "[parameters('effect')]")))))
| mv-expand m = members limit 2000
| extend passed = tostring(m.parameters.effect.value)
| extend pname = extract(@"^\[parameters\('([^']+)'\)\]$", 1, passed)
| extend fromParent = iff(isempty(pname), passed, coalesce(tostring(aParams[pname].value), tostring(def.parameters[pname].defaultValue)))
| extend memberId = tolower(tostring(m.policyDefinitionId)), ReferenceId = tostring(m.policyDefinitionReferenceId)
| join kind=leftouter (
    policyresources
    | where type =~ 'microsoft.authorization/policydefinitions'
    | project memberId = tolower(id), Policy = coalesce(tostring(properties.displayName), name),
        Category = tostring(properties.metadata.category), ownDefault = tostring(properties.parameters.effect.defaultValue),
        ruleEffect = tostring(properties.policyRule.then.effect)
  ) on memberId
| extend Effect = case(isnotempty(fromParent), fromParent, ruleEffect startswith '[', ownDefault, ruleEffect)
| project Policy, Effect, Category, ReferenceId, memberId
| order by case(Effect =~ 'Deny', 0, Effect =~ 'DenyAction', 1, Effect =~ 'Modify', 2, Effect =~ 'DeployIfNotExists', 3, 4) asc, Policy asc
"""

EXEMPTIONS_Q = """
policyresources
| where type =~ 'microsoft.authorization/policyexemptions'
| where tolower(tostring(properties.policyAssignmentId)) == '{Assignment}'
| extend Expires = todatetime(properties.expiresOn)
| project Exemption = coalesce(tostring(properties.displayName), name), Scope = tostring(split(tolower(id), '/providers/microsoft.authorization/policyexemptions/')[0]),
    Category = tostring(properties.exemptionCategory),
    Policies = iff(array_length(properties.policyDefinitionReferenceIds) > 0, strcat_array(properties.policyDefinitionReferenceIds, ', '), '(all)'),
    Expires, Status = case(isnull(Expires), 'No expiry', Expires < now(), 'Expired', Expires < now() + 14d, 'Expires within 14 days', 'Active'),
    Description = tostring(properties.description)
| order by Scope asc
"""

NONCOMPLIANT_Q = f"""
policyresources
| where type =~ 'microsoft.policyinsights/policystates'
| where tolower(tostring(properties.policyAssignmentId)) == '{{Assignment}}'
| where tostring(properties.complianceState) =~ 'NonCompliant'
| where {SEARCH_ARG}
| project Resource = tostring(properties.resourceId), ReferenceId = tostring(properties.policyDefinitionReferenceId),
    Effect = tostring(properties.policyDefinitionAction), Evaluated = todatetime(properties.timestamp)
| order by Effect asc, Resource asc
| take 500
"""

# Locks on a resource, its resource group or its subscription refuse deletes (CanNotDelete) or every change
# (ReadOnly).
LOCKS_Q = r"""
resources
| where type =~ 'microsoft.authorization/locks'
| extend Scope = tostring(split(tolower(id), '/providers/microsoft.authorization/locks/')[0])
| where isempty(trim(@'\s+', @'{Search}')) or tolower(trim(@'\s+', @'{Search}')) contains Scope or Scope contains tolower(trim(@'\s+', @'{Search}'))
| project Lock = name, Level = tostring(properties.level), Scope, Notes = tostring(properties.notes)
| order by Scope asc
"""

EFFECT = status_fmt("Effect", good=["Audit", "audit", "AuditIfNotExists", "auditifnotexists"],
                    warn=["Modify", "modify", "DeployIfNotExists", "deployifnotexists", "Append", "append"],
                    bad=["Deny", "deny", "DenyAction", "denyaction"], neutral=["Disabled", "disabled", "Manual", "manual"])

HOW_TO = """\
Paste anything you have into **Search**: the correlation id from the error, the resource or deployment name, or
the caller. Leave it empty to see every refused request in the time range.

**Fixing a policy denial.** In order of preference:
1. **Change the request** to meet the policy (*Why it was denied* shows the field, its value and what the policy
   expects: an allowed location, a SKU, a tag, private access only).
2. **Exempt** the resource or resource group from that assignment, as *Waiver* or *Mitigated*, ideally with an
   expiry date. An exemption can name single policies of an initiative.
3. **Exclude** the scope from the assignment (*notScopes*), or set the policy's effect parameter to *Audit*.

Setting the assignment's enforcement mode to *DoNotEnforce* stops every policy in it denying anywhere it applies:
use it to unblock a change in an emergency, then put it back. Policy changes and new exemptions can take a few
minutes to apply."""

REFUSALS_NOTE = """\
*Permissions* means the caller lacks the role for that action at that scope (see *Action* and *Scope*); a
*LinkedAuthorizationFailed* means it also needs rights on a resource it references, such as the subnet or key
vault. *Resource lock* means a CanNotDelete or ReadOnly lock on the resource, its resource group or subscription.
*Azure restriction* is a region or service the subscription is not allowed to use, which policy does not control:
raise a support request."""


def parameters():
    return params(f"{P}-params", [
        subscription_param(P),
        free_text_param(P, "Search", "Search",
                        "Optional. A correlation id, or part of a resource name or id, deployment name or caller."),
        workspace_param(P, "The workspace the subscriptions' activity log is sent to. Needed for the refused requests."),
        time_param(P, DAY_MS, (HOUR_MS, 4 * HOUR_MS, 12 * HOUR_MS, DAY_MS, 3 * DAY_MS, 7 * DAY_MS, 14 * DAY_MS, 30 * DAY_MS),
                   "Applies to the activity log panels."),
    ])


def assignment_param():
    return params(f"{P}-assignment-params", [{
        "id": gid(f"{P}-param-Assignment"), "version": "KqlParameterItem/1.0", "name": "Assignment",
        "label": "Policy assignment", "type": 2, "isRequired": False, "multiSelect": False,
        "query": ASSIGNMENT_PICK_Q.strip(), "crossComponentResources": ["{Subscription}"],
        "typeSettings": {"showDefault": False}, "queryType": 1, "resourceType": "microsoft.resourcegraph/resources",
        "description": "Pick one, or select a row in a table above.",
    }])


def workbook():
    denials = la(f"{P}-denials", "Policy denials: which assignment, which policy, and why", DENIALS_Q,
                 formatters=[EFFECT, resource_link("Resource")],
                 labels={"ReferenceId": "Policy reference id", "Why": "Why it was denied",
                         "AssignmentScope": "Assigned at", "AssignmentId": "Assignment id", "CorrelationId": "Correlation id"},
                 no_data="No policy denials in the time range. Check *Refused requests* above for other reasons.")
    deny_policies = arg(f"{P}-deny-policies", "Policies that deny, and the existing resources they find non-compliant",
                        DENY_POLICIES_Q,
                        formatters=[EFFECT, status_fmt("Enforcement", bad=["Default"], neutral=["DoNotEnforce"]),
                                    {"columnMatch": "NonCompliant", "formatter": 18, "formatOptions": {
                                        "thresholdsOptions": "icons", "thresholdsGrid": [
                                            {"operator": ">", "thresholdValue": "0", "representation": "2", "text": "{0}{1}"},
                                            {"operator": "Default", "thresholdValue": None, "representation": "success", "text": "{0}{1}"}]}}],
                        labels={"NonCompliant": "Non-compliant", "Resources": "Resources evaluated",
                                "ReferenceId": "Policy reference id", "AssignmentId": "Assignment id"},
                        no_data="No policy with a deny effect has evaluated a resource in the selected subscriptions.")
    return notebook([
        text(f"{P}-header", "# Why was this request refused?\n"
             "Azure Policy denials and the other reasons Resource Manager refuses a request (permissions, locks, quota, "
             "template errors), and for a policy: which assignment, which policy, the values that failed it, and how "
             "to exempt or exclude."),
        parameters(),
        text(f"{P}-howto", HOW_TO, "info"),
        text(f"{P}-ws-hint", "Select the **Log Analytics workspace** your subscriptions send their activity log to "
             "(`AzureActivity`) to see refused requests. The policy panels further down work without one.", "info",
             visible_when=WORKSPACE_UNSET),
        la(f"{P}-tiles", "", REFUSAL_TILES_Q, vis="tiles", tiles=big_number_tiles("Reason", "State", "Requests", "Detail"),
           no_data="No refused requests in the time range."),
        la(f"{P}-refusals", "Refused requests (latest 500)", REFUSALS_Q,
           formatters=[status_fmt("Reason", bad=["Policy"], warn=REASONS[1:]), resource_link("Resource")],
           labels={"Operation": "Operation", "Detail": "Error", "Action": "Action needed", "Scope": "At scope",
                   "CorrelationId": "Correlation id"},
           no_data="No refused requests. Widen the time range or clear Search."),
        text(f"{P}-refusals-note", REFUSALS_NOTE, "info", visible_when=WORKSPACE_SET),
        export_row(denials, "AssignmentId", "Assignment"),
        text(f"{P}-policy-h", "### Policy assignments"),
        export_row(deny_policies, "AssignmentId", "Assignment"),
        assignment_param(),
        when_set(arg(f"{P}-assignment", "The assignment", ASSIGNMENT_Q,
                     formatters=[status_fmt("Enforcement", good=["Default"], warn=["DoNotEnforce"])],
                     labels={"Excluded": "Excluded scopes (notScopes)", "Overrides": "Effect overrides",
                             "Selectors": "Resource selectors", "Message": "Non-compliance message",
                             "CreatedOn": "Created", "UpdatedOn": "Updated"},
                     no_data="Assignment not found in the selected subscriptions."), "Assignment"),
        when_set(arg(f"{P}-effects", "Policies in the assignment and the effect each resolves to", EFFECTS_Q, width=60,
                     formatters=[EFFECT, resource_link("memberId")],
                     labels={"ReferenceId": "Policy reference id", "memberId": "Definition"},
                     no_data="Could not read the assignment's definition."), "Assignment"),
        when_set(arg(f"{P}-exemptions", "Exemptions from the assignment", EXEMPTIONS_Q, width=40,
                     formatters=[status_fmt("Status", good=["Active"], warn=["Expires within 14 days", "No expiry"],
                                            bad=["Expired"]), resource_link("Scope")],
                     no_data="No exemptions from this assignment."), "Assignment"),
        when_set(arg(f"{P}-noncompliant", "Resources the assignment finds non-compliant (latest 500)", NONCOMPLIANT_Q,
                     formatters=[EFFECT, resource_link("Resource")], labels={"ReferenceId": "Policy reference id"},
                     no_data="No non-compliant resources (or none match Search)."), "Assignment"),
        text(f"{P}-locks-h", "### Locks"),
        arg(f"{P}-locks", "Locks (matching Search, if given)", LOCKS_Q,
            formatters=[status_fmt("Level", warn=["CanNotDelete"], bad=["ReadOnly"]), resource_link("Scope")],
            no_data="No locks in the selected subscriptions (or none on the resource in Search)."),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
