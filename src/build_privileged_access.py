"""Generates the privileged access workbook.

Run:  python src/build_privileged_access.py
Out:  workbook/privileged-access.workbook.json

Who holds and uses privileged access, and is it being granted properly? Privileged Identity Management activations
and the approvals behind them, assignments made outside PIM, risky application permissions, privileged Azure role
assignments, and how privileged and break-glass accounts sign in. Reads the Entra ID audit and sign-in logs and the
activity log from Log Analytics, and Azure role assignments from Resource Graph. Built from the helpers in
build_workbook.py so the workbooks look alike.

Logs record changes, not standing state: the current members of an Entra ID role are in Microsoft Graph, which a
workbook cannot read, so a role held permanently and never touched in the time range does not appear.
"""

import pathlib

from build_workbook import (DAY_MS, ONE_TILE, WORKSPACE_UNSET, arg, big_number_tiles, choice_param, free_text_param,
                            gid, group, la, notebook, params, status_fmt, subscription_param, text, time_param,
                            when_set, workspace_param, write_workbook)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "privileged-access.workbook.json"

P = "pa"

TABS = [
    ("overview", "Overview"),
    ("activations", "Activations"),
    ("approvals", "Approvals"),
    ("assignments", "Assignments"),
    ("signins", "Sign-ins"),
]

# Roles that can take over the tenant or the Azure estate, flagged wherever a role is listed.
TOP_TIER = ("dynamic(['Global Administrator', 'Privileged Role Administrator', 'Privileged Authentication Administrator', "
            "'Security Administrator', 'Conditional Access Administrator', 'Application Administrator', "
            "'Cloud Application Administrator', 'User Administrator', 'Exchange Administrator', "
            "'SharePoint Administrator', 'Hybrid Identity Administrator', 'Intune Administrator', 'Owner', "
            "'User Access Administrator', 'Role Based Access Control Administrator'])")

# Owner, User Access Administrator and Role Based Access Control Administrator: the Azure roles that can grant access.
AZURE_ROLES = {"8e3af657-a8ff-443c-a75c-2fe8c4bcb635": "Owner",
               "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9": "User Access Administrator",
               "f58310d9-a9f6-439a-9e8d-f62e7b41a168": "RBAC Administrator"}
AZURE_ROLE_IDS = ", ".join(f"'{r}'" for r in AZURE_ROLES)
AZURE_ROLE_CASE = "case(" + ", ".join(f"RoleId == '{r}', '{n}'" for r, n in AZURE_ROLES.items()) + ", '')"

# ---------------------------------------------------------------------------
# Privileged Identity Management events
# ---------------------------------------------------------------------------

# Every PIM audit event, for Entra roles, PIM groups and Azure resources, with the role, the account it is about,
# the justification and ticket, and what kind of event it is. Operation names vary between the three, so the event
# is read from words in the name.
PIM = r"""
let topTier = """ + TOP_TIER + r""";
let pim = AuditLogs
| where TimeGenerated {TimeRange}
| where LoggedByService =~ 'PIM'
| extend Actor = coalesce(tostring(InitiatedBy.user.userPrincipalName), tostring(InitiatedBy.app.displayName))
| mv-apply t = TargetResources on (
    summarize Role = take_anyif(tostring(t.displayName), tostring(t.type) =~ 'Role'),
        Group = take_anyif(tostring(t.displayName), tostring(t.type) =~ 'Group'),
        Target = take_anyif(coalesce(tostring(t.userPrincipalName), tostring(t.displayName)), tostring(t.type) in~ ('User', 'ServicePrincipal'))
  )
| extend details = tostring(AdditionalDetails)
| extend Justification = coalesce(extract(@'"key":"Justification","value":"([^"]*)"', 1, details), ResultReason),
    Ticket = extract(@'"key":"TicketNumber","value":"([^"]*)"', 1, details),
    RoleName = coalesce(Role, Group),
    Area = case(Category =~ 'GroupManagement', 'PIM group', Category =~ 'ResourceManagement', 'Azure resource', 'Entra role'),
    op = tolower(OperationName)
| extend Event = case(
        op has 'approved', 'Approved',
        op has_any ('denied', 'rejected'), 'Denied',
        op has 'approval' and op has 'request', 'Approval requested',
        op has 'activation' and op has 'completed', 'Activated',
        op has 'activation' and op has 'requested', 'Activation requested',
        op has 'deactivat', 'Deactivated',
        op has 'expired', 'Expired',
        op has 'outside of pim', 'Outside PIM',
        op has 'eligible', 'Eligible assignment',
        op has_any ('permanent', 'timebound'), 'Active assignment',
        OperationName),
    TopTier = iff(coalesce(Role, Group) in (topTier), 'Yes', '');
"""

ACTIVATIONS = PIM + """pim
| where Event == 'Activated'
| extend User = coalesce(Target, Actor)"""

# Each approval or denial, matched to the latest request for the same account and role before it.
DECISIONS = PIM + """let requests = pim
| where Event in ('Approval requested', 'Activation requested')
| project RequestTime = TimeGenerated, Requester = tolower(Target), RoleName, ReqJustification = Justification, ReqTicket = Ticket;
let decisions = pim
| where Event in ('Approved', 'Denied')
| project DecisionTime = TimeGenerated, Decision = Event, Approver = Actor, Requester = tolower(Target), RoleName, Area,
    TopTier, Comment = ResultReason
| join kind=leftouter requests on Requester, RoleName
| summarize RequestTime = maxif(RequestTime, RequestTime <= DecisionTime),
    Justification = take_anyif(ReqJustification, RequestTime <= DecisionTime), Ticket = take_anyif(ReqTicket, RequestTime <= DecisionTime)
    by DecisionTime, Decision, Approver, Requester, RoleName, Area, TopTier, Comment
| extend MinutesToDecide = round((DecisionTime - RequestTime) / 1m, 1),
    SelfApproved = iff(isnotempty(Requester) and tolower(Approver) == Requester, 'Yes', 'No')
| extend Rushed = iff(Decision == 'Approved' and MinutesToDecide < {FastMinutes}, 'Yes', 'No');
"""

# Approval requests from the last 24 hours (PIM lets a request expire after a day) with no decision or activation
# after them.
PENDING = PIM + """let settled = pim
| where Event in ('Approved', 'Denied', 'Activated')
| project SettledTime = TimeGenerated, Requester = tolower(Target), RoleName;
pim
| where Event == 'Approval requested' and TimeGenerated > ago(24h)
| project RequestTime = TimeGenerated, Requester = tolower(Target), RoleName, Area, TopTier, Justification, Ticket
| join kind=leftouter settled on Requester, RoleName
| summarize Settled = countif(SettledTime >= RequestTime) by RequestTime, Requester, RoleName, Area, TopTier, Justification, Ticket
| where Settled == 0
| extend WaitingHours = round((now() - RequestTime) / 1h, 1)
| project-away Settled"""

# Role assignments made in Entra ID directly rather than through PIM. PIM's own writes are made by the MS-PIM
# application and are left out; PIM also reports assignments it noticed were made outside it.
OUTSIDE_PIM = r"""
union
    (AuditLogs
    | where TimeGenerated {TimeRange}
    | where LoggedByService =~ 'Core Directory' and OperationName in~ ('Add member to role', 'Add scoped member to role')
    | where tostring(InitiatedBy.app.displayName) !~ 'MS-PIM'
    | extend tr = TargetResources[0]
    | mv-apply p = tr.modifiedProperties on (
        summarize Role = take_anyif(trim('"', tostring(p.newValue)), tostring(p.displayName) == 'Role.DisplayName'))
    | extend Assignee = coalesce(tostring(tr.userPrincipalName), tostring(tr.displayName)), AssigneeType = tostring(tr.type),
        Source = 'Entra ID'),
    (AuditLogs
    | where TimeGenerated {TimeRange}
    | where LoggedByService =~ 'PIM' and OperationName has 'outside of PIM'
    | mv-apply t = TargetResources on (
        summarize Role = take_anyif(tostring(t.displayName), tostring(t.type) =~ 'Role'),
            Assignee = take_anyif(coalesce(tostring(t.userPrincipalName), tostring(t.displayName)), tostring(t.type) in~ ('User', 'ServicePrincipal', 'Group')),
            AssigneeType = take_anyif(tostring(t.type), tostring(t.type) in~ ('User', 'ServicePrincipal', 'Group')))
    | extend Source = 'Reported by PIM')
| extend Actor = coalesce(tostring(InitiatedBy.user.userPrincipalName), tostring(InitiatedBy.app.displayName))"""

# Application permissions and credentials: an application granted one of these can make itself, or anyone, an
# administrator.
RISKY_PERMISSIONS = ("'RoleManagement.ReadWrite.Directory', 'AppRoleAssignment.ReadWrite.All', "
                     "'Application.ReadWrite.All', 'Directory.ReadWrite.All', 'PrivilegedAccess.ReadWrite.AzureAD', "
                     "'Policy.ReadWrite.ConditionalAccess', 'UserAuthenticationMethod.ReadWrite.All', "
                     "'Domain.ReadWrite.All', 'full_access_as_app'")
APP_CHANGES = f"""
AuditLogs
| where TimeGenerated {{TimeRange}}
| where OperationName has_any ('app role assignment to service principal', 'delegated permission grant', 'Consent to application',
    'service principal credentials', 'Certificates and secrets management', 'owner to application', 'owner to service principal')
| extend Actor = coalesce(tostring(InitiatedBy.user.userPrincipalName), tostring(InitiatedBy.app.displayName)),
    App = tostring(TargetResources[0].displayName),
    Kind = case(OperationName has_any ('app role assignment', 'permission grant', 'Consent'), 'Permission granted',
        OperationName has_any ('credentials', 'Certificates and secrets'), 'Credential added or changed', 'Owner added'),
    targets = tostring(TargetResources)
| extend Risky = iff(targets has_any ({RISKY_PERMISSIONS}), 'Yes', '')"""

# Accounts treated as privileged in the sign-in panels: anyone PIM or the directory recorded a role change for in
# the time range, plus accounts matching the admin naming pattern.
PRIVILEGED_USERS = """
let adminPattern = @'{AdminPattern}';
let privileged = AuditLogs
| where TimeGenerated {TimeRange}
| where LoggedByService =~ 'PIM' or (LoggedByService =~ 'Core Directory' and OperationName has 'member to role')
| mv-apply t = TargetResources on (where tostring(t.type) =~ 'User' | project u = tolower(tostring(t.userPrincipalName)))
| where isnotempty(u)
| distinct u;
"""

PRIVILEGED_SIGNINS = PRIVILEGED_USERS + """SigninLogs
| where TimeGenerated {TimeRange}
| where tolower(UserPrincipalName) in (privileged) or (isnotempty(adminPattern) and UserPrincipalName matches regex adminPattern)"""

AUTH_STRENGTH = PRIVILEGED_SIGNINS + """
| where ResultType == '0'
| extend methods = tostring(AuthenticationDetails)
| extend Strength = case(methods has_any ('FIDO2', 'Windows Hello', 'Passkey', 'X.509', 'Certificate-based'), 'Phishing-resistant',
    AuthenticationRequirement =~ 'multiFactorAuthentication', 'MFA', 'Single factor')
| summarize SignIns = count(), PhishingResistant = countif(Strength == 'Phishing-resistant'), Mfa = countif(Strength == 'MFA'),
    SingleFactor = countif(Strength == 'Single factor'), Apps = dcount(AppDisplayName), LastSignIn = max(TimeGenerated)
    by User = UserPrincipalName
| extend Weakest = case(SingleFactor > 0, 'Single factor', Mfa > 0, 'MFA, not phishing-resistant', 'Phishing-resistant')"""

# Interactive and non-interactive sign-ins by the break-glass accounts. The two tables store location differently,
# so each is shaped before the union.
BREAK_GLASS = """
let pattern = @'{BreakGlass}';
union isfuzzy=true
    (SigninLogs
    | where TimeGenerated {TimeRange}
    | where isnotempty(pattern) and UserPrincipalName matches regex pattern
    | project TimeGenerated, UserPrincipalName, ResultType, AppDisplayName, IPAddress,
        Country = tostring(LocationDetails.countryOrRegion), ConditionalAccessStatus, Kind = 'Interactive'),
    (AADNonInteractiveUserSignInLogs
    | where TimeGenerated {TimeRange}
    | where isnotempty(pattern) and UserPrincipalName matches regex pattern
    | project TimeGenerated, UserPrincipalName, ResultType, AppDisplayName, IPAddress,
        Country = tostring(parse_json(tostring(LocationDetails)).countryOrRegion), ConditionalAccessStatus, Kind = 'Non-interactive')"""

# ---------------------------------------------------------------------------
# Overview tiles
# ---------------------------------------------------------------------------

LA_TILES = [
    ("activations", ACTIVATIONS + """
| summarize Activations = count(), Users = dcount(User), TopTier = countif(TopTier == 'Yes')
| project Signal = 'Role activations', Value = Activations,
    Detail = strcat(Users, ' people · ', TopTier, ' of top-tier roles'), State = 'Available'
"""),
    ("decisions", DECISIONS + """decisions
| summarize Total = count(), Denied = countif(Decision == 'Denied'), Rushed = countif(Rushed == 'Yes'),
    Self = countif(SelfApproved == 'Yes')
| project Signal = 'Approval decisions', Value = Total,
    Detail = strcat(Denied, ' denied · ', Rushed, ' under {FastMinutes} min · ', Self, ' self-approved'),
    State = case(Self > 0, 'Unavailable', Rushed > 0, 'Degraded', 'Available')
"""),
    ("pending", PENDING + """
| summarize Pending = count(), TopTier = countif(TopTier == 'Yes'), Oldest = max(WaitingHours)
| project Signal = 'Requests awaiting approval', Value = Pending,
    Detail = iff(Pending == 0, 'none in the last 24 hours', strcat(TopTier, ' top-tier · oldest ', Oldest, ' h')),
    State = iff(Pending > 0, 'Degraded', 'Available')
"""),
    ("outside", OUTSIDE_PIM + """
| where Source == 'Entra ID'
| summarize Assignments = count(), ToApps = countif(AssigneeType =~ 'ServicePrincipal')
| project Signal = 'Roles assigned outside PIM', Value = Assignments, Detail = strcat(ToApps, ' to service principals'),
    State = iff(Assignments > 0, 'Degraded', 'Available')
"""),
    ("breakglass", BREAK_GLASS + """
| summarize SignIns = count(), Accounts = dcount(UserPrincipalName)
| project Signal = 'Break-glass sign-ins', Value = SignIns,
    Detail = iff(isempty(@'{BreakGlass}'), 'set the break-glass accounts at the top', strcat(Accounts, ' accounts')),
    State = case(isempty(@'{BreakGlass}'), 'Unknown', SignIns > 0, 'Unavailable', 'Available')
"""),
    ("mfa", AUTH_STRENGTH + """
| summarize Users = count(), Weak = countif(Weakest != 'Phishing-resistant'), Single = countif(Weakest == 'Single factor')
| project Signal = 'Privileged without phishing-resistant MFA', Value = Weak,
    Detail = strcat(Single, ' single factor · of ', Users, ' privileged accounts'),
    State = case(Single > 0, 'Unavailable', Weak > 0, 'Degraded', 'Available')
"""),
    ("apps", APP_CHANGES + """
| summarize Risky = countif(Risky == 'Yes'), Total = count()
| project Signal = 'Risky app permissions granted', Value = Risky, Detail = strcat('of ', Total, ' app permission and credential changes'),
    State = iff(Risky > 0, 'Degraded', 'Available')
"""),
]

AZURE_PRIVILEGED = f"""
authorizationresources
| where type =~ 'microsoft.authorization/roleassignments'
| extend RoleId = tolower(tostring(split(tostring(properties.roleDefinitionId), '/')[-1]))
| where RoleId in ({AZURE_ROLE_IDS})
| extend Role = {AZURE_ROLE_CASE}, scope = tolower(tostring(properties.scope))
| extend parts = split(scope, '/')
| extend ScopeLevel = case(scope == '/', 'Tenant root',
    scope startswith '/providers/microsoft.management/managementgroups/', 'Management group',
    array_length(parts) == 3, 'Subscription', array_length(parts) == 5, 'Resource group', 'Resource')
| summarize Created = min(todatetime(properties.createdOn)), CreatedBy = take_any(tostring(properties.createdBy))
    by Scope = scope, ScopeLevel, Role, PrincipalType = tostring(properties.principalType),
    PrincipalId = tostring(properties.principalId)"""

AZURE_TILE = AZURE_PRIVILEGED + """
| where ScopeLevel in ('Tenant root', 'Management group', 'Subscription')
| summarize Users = countif(PrincipalType =~ 'User'), Total = count()
| project Signal = 'Azure access admins assigned to users', Value = Users,
    Detail = strcat('of ', Total, ' Owner / access admin assignments at subscription or above'),
    State = iff(Users > 0, 'Degraded', 'Available')
"""

TILE_NOTE = """\
*Rushed* approvals were decided within **{FastMinutes} minutes** of the request, too quickly for the approver to
have checked it. A *self-approved* request was approved by the account that asked for it. *Roles assigned outside
PIM* are permanent Entra ID role assignments made directly in the directory. *Privileged* accounts are those PIM or
the directory recorded a role change for in the time range, plus any matching the admin account pattern."""

# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------

ACTIVATIONS_BY_DAY_Q = ACTIVATIONS + """
| summarize Activations = count() by Day = bin(TimeGenerated, 1d), RoleName
"""

DECISIONS_BY_DAY_Q = DECISIONS + """decisions
| summarize Decisions = count() by Day = bin(DecisionTime, 1d), Decision
"""

ACTIVATION_LIST_Q = ACTIVATIONS + """
| extend WeakJustification = iff(strlen(trim(@'\\s+', Justification)) < 10, 'Yes', '')
| project TimeGenerated, User, Area, Role = RoleName, TopTier, Justification, WeakJustification, Ticket
| order by TimeGenerated desc
| take 1000
"""

ACTIVATIONS_BY_ROLE_Q = ACTIVATIONS + """
| summarize Activations = count(), People = dcount(User), LastActivation = max(TimeGenerated) by Area, Role = RoleName, TopTier
| order by TopTier desc, Activations desc
"""

ACTIVATIONS_BY_USER_Q = ACTIVATIONS + """
| summarize Activations = count(), Roles = dcount(RoleName), TopTier = countif(TopTier == 'Yes'),
    RoleList = strcat_array(make_set(RoleName, 10), ', '), LastActivation = max(TimeGenerated)
    by User
| order by TopTier desc, Activations desc
"""

DECISIONS_Q = DECISIONS + """decisions
| project DecisionTime, Decision, Approver, Requester, Role = RoleName, Area, TopTier, MinutesToDecide, Rushed, SelfApproved,
    Justification, Ticket, Comment, RequestTime
| order by DecisionTime desc
"""

APPROVERS_Q = DECISIONS + """decisions
| summarize Approved = countif(Decision == 'Approved'), Denied = countif(Decision == 'Denied'),
    Requesters = dcount(Requester), MedianMinutes = round(percentile(MinutesToDecide, 50), 1),
    Rushed = countif(Rushed == 'Yes'), SelfApproved = countif(SelfApproved == 'Yes'), TopTier = countif(TopTier == 'Yes')
    by Approver
| order by SelfApproved desc, Rushed desc, Approved desc
"""

PENDING_Q = PENDING + """
| order by TopTier desc, RequestTime asc
"""

ASSIGNMENT_CHANGES_Q = PIM + """pim
| where Event in ('Eligible assignment', 'Active assignment') or OperationName has 'Remove'
| where Event !in ('Activated', 'Activation requested', 'Approval requested', 'Approved', 'Denied', 'Deactivated', 'Expired')
| where tolower(OperationName) !has 'requested'
| extend Duration = case(tolower(OperationName) has 'permanent', 'Permanent', tolower(OperationName) has 'timebound', 'Time-bound', '')
| project TimeGenerated, Operation = OperationName, Actor, Assignee = Target, Role = RoleName, Area, TopTier, Duration, Result
| order by TimeGenerated desc
| take 1000
"""

OUTSIDE_PIM_Q = OUTSIDE_PIM + """
| project TimeGenerated, Source, Actor, Assignee, AssigneeType, Role, Result
| order by TimeGenerated desc
"""

APP_CHANGES_Q = APP_CHANGES + """
| project TimeGenerated, Kind, Risky, App, Operation = OperationName, Actor, Result
| order by Risky desc, TimeGenerated desc
| take 500
"""

AZURE_PRIVILEGED_Q = AZURE_PRIVILEGED + """
| order by case(ScopeLevel == 'Tenant root', 0, ScopeLevel == 'Management group', 1, ScopeLevel == 'Subscription', 2, 3) asc,
    case(PrincipalType =~ 'User', 0, 1) asc, Scope asc
"""

AZURE_GRANTS_Q = f"""
AzureActivity
| where TimeGenerated {{TimeRange}}
| where OperationNameValue =~ 'MICROSOFT.AUTHORIZATION/ROLEASSIGNMENTS/WRITE' and ActivityStatusValue in~ ('Success', 'Succeeded')
| extend props = column_ifexists('Properties_d', dynamic(null))
| extend body = todynamic(tostring(props.requestbody))
| extend RoleId = tolower(tostring(split(tostring(body.Properties.RoleDefinitionId), '/')[-1]))
| where RoleId in ({AZURE_ROLE_IDS})
| project TimeGenerated, Role = {AZURE_ROLE_CASE}, Scope = tostring(split(tolower(_ResourceId), '/providers/microsoft.authorization/roleassignments/')[0]),
    PrincipalId = tostring(body.Properties.PrincipalId), PrincipalType = tostring(body.Properties.PrincipalType), Caller
| order by TimeGenerated desc
"""

BREAK_GLASS_Q = BREAK_GLASS + """
| project TimeGenerated, User = UserPrincipalName, Kind, Result = iff(ResultType == '0', 'Success', strcat('Failed (', ResultType, ')')),
    App = AppDisplayName, IPAddress, Country, ConditionalAccess = ConditionalAccessStatus
| order by TimeGenerated desc
"""

AUTH_STRENGTH_Q = AUTH_STRENGTH + """
| project User, Weakest, SignIns, PhishingResistant, Mfa, SingleFactor, Apps, LastSignIn
| order by case(Weakest == 'Single factor', 0, Weakest startswith 'MFA', 1, 2) asc, SignIns desc
"""

RISKY_SIGNINS_Q = PRIVILEGED_SIGNINS + """
| where RiskLevelDuringSignIn in~ ('medium', 'high') or RiskState =~ 'atRisk'
| project TimeGenerated, User = UserPrincipalName, Risk = RiskLevelDuringSignIn, RiskState,
    Result = iff(ResultType == '0', 'Success', strcat('Failed (', ResultType, ')')), App = AppDisplayName, IPAddress,
    Country = tostring(LocationDetails.countryOrRegion)
| order by TimeGenerated desc
"""

LEGACY_AUTH_Q = PRIVILEGED_USERS + """SigninLogs
| where TimeGenerated {TimeRange}
| where ClientAppUsed !in~ ('Browser', 'Mobile Apps and Desktop clients', '')
| summarize SignIns = count(), Succeeded = countif(ResultType == '0'), LastSeen = max(TimeGenerated)
    by User = UserPrincipalName, ClientApp = ClientAppUsed
| extend u = tolower(User)
| join kind=leftouter (privileged | extend Privileged = 'Yes') on u
| extend Privileged = iff(Privileged == 'Yes' or (isnotempty(adminPattern) and User matches regex adminPattern), 'Yes', 'No')
| project User, Privileged, ClientApp, SignIns, Succeeded, LastSeen
| order by Privileged desc, Succeeded desc
| take 200
"""

POLICY_CHANGES_Q = """
AuditLogs
| where TimeGenerated {TimeRange}
| where OperationName has_any ('conditional access policy', 'named location', 'authentication strength', 'authentication method',
    'authorization policy', 'cross-tenant access', 'role setting', 'role management policy')
| project TimeGenerated, Operation = OperationName,
    Actor = coalesce(tostring(InitiatedBy.user.userPrincipalName), tostring(InitiatedBy.app.displayName)),
    Target = tostring(TargetResources[0].displayName), Result
| order by TimeGenerated desc
| take 500
"""

# ---------------------------------------------------------------------------
# Parameters and tabs
# ---------------------------------------------------------------------------


def global_params():
    return params(f"{P}-params", [
        subscription_param(P),
        time_param(P, 7 * DAY_MS, [d * DAY_MS for d in (1, 7, 14, 30, 90)]),
        workspace_param(P, "The workspace that receives the Entra ID audit and sign-in logs (often the Sentinel "
                           "workspace) and the activity log.", required=True),
        free_text_param(P, "BreakGlass", "Break-glass accounts",
                        "A regular expression matching the emergency access accounts' user principal names, for "
                        "example ^(bg1|bg2)@contoso\\.com$. Any sign-in by them is flagged."),
        free_text_param(P, "AdminPattern", "Admin account pattern",
                        "Optional. A regular expression matching separate admin accounts (for example ^adm-), so they "
                        "count as privileged even with no role change in the time range."),
        choice_param(P, "FastMinutes", "Rushed approval under",
                     [("1", "1 minute"), ("2", "2 minutes"), ("5", "5 minutes"), ("10", "10 minutes")], "2",
                     "An approval decided this soon after the request is flagged as rushed."),
        {"id": gid(f"{P}-param-selectedTab"), "version": "KqlParameterItem/1.0", "name": "selectedTab", "type": 1,
         "value": "overview", "isHiddenWhenLocked": True},
    ])


def tabs():
    return {"type": 11, "content": {"version": "LinkItem/1.0", "style": "tabs", "links": [
        {"id": gid(f"{P}-tab-" + key), "cellValue": "selectedTab", "linkTarget": "parameter",
         "linkLabel": label, "subTarget": key, "style": "link"} for key, label in TABS
    ]}, "name": f"{P}-tabs"}


TOP_TIER_FMT = status_fmt("TopTier", bad=["Yes"])
YES_BAD = dict(bad=["Yes"], good=["No"])
DECISION = status_fmt("Decision", good=["Approved"], warn=["Denied"])


def overview_tab():
    return group(f"{P}-tab-overview", [
        *[la(f"{P}-tile-{key}", "", q, vis="tiles", tiles=big_number_tiles("Signal", "State", "Value", "Detail"),
             fixed_px=ONE_TILE) for key, q in LA_TILES],
        arg(f"{P}-tile-azure", "", AZURE_TILE, vis="tiles", tiles=big_number_tiles("Signal", "State", "Value", "Detail"),
            fixed_px=ONE_TILE),
        text(f"{P}-tile-note", TILE_NOTE, "info"),
        la(f"{P}-activations-day", "Role activations per day by role", ACTIVATIONS_BY_DAY_Q, vis="barchart", width=50,
           no_data="No role activations in the time range."),
        la(f"{P}-decisions-day", "Approval decisions per day", DECISIONS_BY_DAY_Q, vis="barchart", width=50,
           no_data="No approval decisions in the time range (or no role requires approval)."),
    ], tab="overview")


def activations_tab():
    return group(f"{P}-tab-activations", [
        la(f"{P}-by-role", "Activations by role", ACTIVATIONS_BY_ROLE_Q, width=50, formatters=[TOP_TIER_FMT],
           labels={"TopTier": "Top tier", "LastActivation": "Last activation"}, no_data="No role activations."),
        la(f"{P}-by-user", "Activations by person", ACTIVATIONS_BY_USER_Q, width=50,
           labels={"TopTier": "Top-tier activations", "RoleList": "Roles", "LastActivation": "Last activation"},
           no_data="No role activations."),
        la(f"{P}-activations", "Every activation", ACTIVATION_LIST_Q,
           formatters=[TOP_TIER_FMT, status_fmt("WeakJustification", warn=["Yes"])],
           labels={"TimeGenerated": "Activated", "TopTier": "Top tier", "WeakJustification": "Weak justification"},
           no_data="No role activations in the time range."),
        text(f"{P}-activations-note", "Covers Entra ID roles, PIM for Groups and Azure resource roles managed in PIM. "
             "A *weak justification* is under ten characters. Someone who activates a top-tier role every day may be "
             "better served by a narrower role.", "info"),
    ], tab="activations")


def approvals_tab():
    return group(f"{P}-tab-approvals", [
        la(f"{P}-pending", "Requests awaiting approval (last 24 hours)", PENDING_Q, formatters=[TOP_TIER_FMT],
           labels={"RequestTime": "Requested", "RoleName": "Role", "TopTier": "Top tier", "WaitingHours": "Waiting (hours)"},
           no_data="No requests are waiting for approval."),
        la(f"{P}-decisions", "Approval decisions", DECISIONS_Q,
           formatters=[DECISION, TOP_TIER_FMT, status_fmt("Rushed", **YES_BAD), status_fmt("SelfApproved", **YES_BAD)],
           labels={"DecisionTime": "Decided", "TopTier": "Top tier", "MinutesToDecide": "Minutes to decide",
                   "SelfApproved": "Self-approved", "Comment": "Approver's reason", "RequestTime": "Requested"},
           no_data="No approval decisions in the time range (or no role requires approval)."),
        la(f"{P}-approvers", "Decisions by approver", APPROVERS_Q,
           formatters=[{"columnMatch": c, "formatter": 18, "formatOptions": {
               "thresholdsOptions": "icons", "thresholdsGrid": [
                   {"operator": ">", "thresholdValue": "0", "representation": "4", "text": "{0}{1}"},
                   {"operator": "Default", "thresholdValue": None, "representation": "success", "text": "{0}{1}"}]}}
               for c in ("Rushed", "SelfApproved")],
           labels={"MedianMinutes": "Median minutes to decide", "SelfApproved": "Self-approved",
                   "TopTier": "Top-tier decisions"},
           no_data="No approval decisions in the time range."),
        text(f"{P}-approvals-note", "Approvals happen only for roles whose PIM settings require them. *Minutes to "
             "decide* runs from the latest request for the same person and role before the decision, so it can be "
             "wrong when one person makes several requests for one role close together. PIM lets a request expire "
             "after 24 hours, so older unanswered requests are not listed as waiting. An approver who approves most "
             "requests within a minute or two is unlikely to be checking them.", "info"),
    ], tab="approvals")


def assignments_tab():
    return group(f"{P}-tab-assignments", [
        text(f"{P}-entra-h", "### Entra ID roles"),
        la(f"{P}-outside", "Role assignments made outside PIM", OUTSIDE_PIM_Q,
           formatters=[status_fmt("AssigneeType", warn=["ServicePrincipal"])],
           labels={"TimeGenerated": "Assigned", "AssigneeType": "Assignee type"},
           no_data="No roles were assigned outside PIM in the time range."),
        la(f"{P}-pim-changes", "Eligible and active assignments made or removed in PIM", ASSIGNMENT_CHANGES_Q,
           formatters=[TOP_TIER_FMT, status_fmt("Duration", warn=["Permanent"], good=["Time-bound"])],
           labels={"TimeGenerated": "Changed", "TopTier": "Top tier"},
           no_data="No PIM assignment changes in the time range."),
        text(f"{P}-apps-h", "### Applications"),
        la(f"{P}-apps", "Application permissions, credentials and owners", APP_CHANGES_Q,
           formatters=[status_fmt("Risky", bad=["Yes"]),
                       status_fmt("Kind", warn=["Permission granted", "Credential added or changed"], neutral=["Owner added"])],
           labels={"TimeGenerated": "Changed"}, no_data="No application permission or credential changes."),
        text(f"{P}-apps-note", "*Risky* permissions let an application make itself or anyone else an administrator "
             "(for example `RoleManagement.ReadWrite.Directory` or `AppRoleAssignment.ReadWrite.All`). A credential "
             "added to an application that already holds such a permission is worth checking.", "info"),
        text(f"{P}-azure-h", "### Azure"),
        arg(f"{P}-azure", "Owner and access administrator assignments", AZURE_PRIVILEGED_Q,
            formatters=[status_fmt("PrincipalType", warn=["User"])],
            labels={"ScopeLevel": "Scope level", "PrincipalType": "Principal type", "PrincipalId": "Principal id",
                    "CreatedBy": "Created by (id)"},
            no_data="No Owner or access administrator assignments."),
        la(f"{P}-azure-grants", "Owner and access administrator assignments made (activity log)", AZURE_GRANTS_Q,
           labels={"TimeGenerated": "Assigned", "PrincipalId": "Principal id", "PrincipalType": "Principal type"},
           no_data="No Owner or access administrator assignments were made in the time range (or the activity log "
                   "is not sent to this workspace)."),
        text(f"{P}-azure-note", "Resource Graph shows assignments active now, including those activated through PIM "
             "for their duration, and holds principal ids only. Assign these roles to groups managed in PIM rather "
             "than to people directly.", "info"),
    ], tab="assignments")


def signins_tab():
    return group(f"{P}-tab-signins", [
        text(f"{P}-bg-hint", "Set **Break-glass accounts** at the top to watch the emergency access accounts. They "
             "should never sign in outside a tested emergency.", "info",
             visible_when={"parameterName": "BreakGlass", "comparison": "isEqualTo", "value": ""}),
        when_set(la(f"{P}-break-glass", "Break-glass account sign-ins", BREAK_GLASS_Q,
                    formatters=[status_fmt("Result", good=["Success"])],
                    labels={"TimeGenerated": "Signed in", "IPAddress": "IP address", "ConditionalAccess": "Conditional Access"},
                    no_data="No sign-ins by the break-glass accounts in the time range."), "BreakGlass"),
        la(f"{P}-auth-strength", "How privileged accounts sign in", AUTH_STRENGTH_Q,
           formatters=[status_fmt("Weakest", good=["Phishing-resistant"], warn=["MFA, not phishing-resistant"],
                                  bad=["Single factor"])],
           labels={"Weakest": "Weakest method", "SignIns": "Sign-ins", "PhishingResistant": "Phishing-resistant",
                   "Mfa": "Other MFA", "SingleFactor": "Single factor", "LastSignIn": "Last sign-in"},
           no_data="No successful sign-ins by privileged accounts in the time range."),
        text(f"{P}-auth-note", "*Phishing-resistant* means a FIDO2 key, passkey, Windows Hello for Business or "
             "certificate. A sign-in that reuses an earlier MFA from the same session counts as *other MFA*, so an "
             "account can show some even when it always uses a passkey. Require an authentication strength in "
             "Conditional Access for admin roles to close the gap.", "info"),
        la(f"{P}-risky", "Risky sign-ins by privileged accounts", RISKY_SIGNINS_Q,
           formatters=[status_fmt("Risk", warn=["medium"], bad=["high"]), status_fmt("Result", good=["Success"])],
           labels={"TimeGenerated": "Signed in", "RiskState": "Risk state", "IPAddress": "IP address"},
           no_data="No medium or high risk sign-ins by privileged accounts."),
        la(f"{P}-legacy", "Legacy authentication sign-ins", LEGACY_AUTH_Q,
           formatters=[status_fmt("Privileged", bad=["Yes"], neutral=["No"])],
           labels={"ClientApp": "Client", "LastSeen": "Last seen"},
           no_data="No legacy authentication sign-ins in the time range."),
        la(f"{P}-policy-changes", "Changes to Conditional Access, authentication and PIM role settings", POLICY_CHANGES_Q,
           labels={"TimeGenerated": "Changed"}, no_data="No policy changes in the time range."),
    ], tab="signins")


def workbook():
    return notebook([
        text(f"{P}-header", "# Privileged access\n"
             "Who holds and uses privileged access, and is it granted properly? PIM activations and the approvals "
             "behind them, assignments made outside PIM, risky application permissions, Azure access "
             "administrators, and how privileged and break-glass accounts sign in."),
        global_params(),
        text(f"{P}-la-hint", "Select the **Log Analytics workspace** that receives the Entra ID audit and sign-in "
             "logs.", "warning", visible_when=WORKSPACE_UNSET),
        tabs(),
        overview_tab(),
        activations_tab(),
        approvals_tab(),
        assignments_tab(),
        signins_tab(),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
