# Privileged access

*Reference for [privileged-access.workbook.json](../workbook/privileged-access.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

Who holds and uses privileged access, and is it granted properly? PIM activations and the approvals behind them, assignments made outside PIM, risky application permissions, Azure access administrators, and how privileged and break-glass accounts sign in.

It has 26 panels across 5 tabs. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Time range | The period the log and metric panels cover. |
| Log Analytics workspace | The workspace that receives the Entra ID audit and sign-in logs (often the Sentinel workspace) and the activity log. |
| Break-glass accounts | A regular expression matching the emergency access accounts' user principal names, for example ^(bg1/bg2)@contoso\.com$. Any sign-in by them is flagged. |
| Admin account pattern | Optional. A regular expression matching separate admin accounts (for example ^adm-), so they count as privileged even with no role change in the time range. |
| Rushed approval under | An approval decided this soon after the request is flagged as rushed. |

> Select the **Log Analytics workspace** that receives the Entra ID audit and sign-in logs.

## Tab: Overview

#### Tile activations

*Tiles · Log Analytics* · reads `AuditLogs`

#### Tile decisions

*Tiles · Log Analytics* · reads `AuditLogs`, `Event`

#### Tile pending

*Tiles · Log Analytics* · reads `AuditLogs`

#### Tile outside

*Tiles · Log Analytics* · reads `AuditLogs`

#### Tile breakglass

*Tiles · Log Analytics* · reads `SigninLogs`, `AADNonInteractiveUserSignInLogs`

#### Tile mfa

*Tiles · Log Analytics* · reads `AuditLogs`, `SigninLogs`

#### Tile apps

*Tiles · Log Analytics* · reads `AuditLogs`

#### Tile azure

*Tiles · Azure Resource Graph* · reads `authorizationresources`

> *Rushed* approvals were decided within **{FastMinutes} minutes** of the request, too quickly for the approver to
> have checked it. A *self-approved* request was approved by the account that asked for it. *Roles assigned outside
> PIM* are permanent Entra ID role assignments made directly in the directory. *Privileged* accounts are those PIM or
> the directory recorded a role change for in the time range, plus any matching the admin account pattern.

#### Role activations per day by role

*Bar chart · Log Analytics* · reads `AuditLogs`

When there is nothing to show: *No role activations in the time range.*

#### Approval decisions per day

*Bar chart · Log Analytics* · reads `AuditLogs`, `Event`

When there is nothing to show: *No approval decisions in the time range (or no role requires approval).*

## Tab: Activations

#### Activations by role

*Table · Log Analytics* · reads `AuditLogs`

When there is nothing to show: *No role activations.*

#### Activations by person

*Table · Log Analytics* · reads `AuditLogs`

When there is nothing to show: *No role activations.*

#### Every activation

*Table · Log Analytics* · reads `AuditLogs`

Columns: Activated, User, Area, Role, Top tier, Justification, Weak justification, Ticket.

When there is nothing to show: *No role activations in the time range.*

> Covers Entra ID roles, PIM for Groups and Azure resource roles managed in PIM. A *weak justification* is under ten characters. Someone who activates a top-tier role every day may be better served by a narrower role.

## Tab: Approvals

#### Requests awaiting approval (last 24 hours)

*Table · Log Analytics* · reads `AuditLogs`

Columns: Requested, Requester, Role, Area, Top tier, Justification, Ticket.

When there is nothing to show: *No requests are waiting for approval.*

#### Approval decisions

*Table · Log Analytics* · reads `AuditLogs`, `Event`

Columns: Decided, Decision, Approver, Requester, Role, Area, Top tier, Minutes to decide, Rushed, Self-approved, Justification, Ticket, Approver's reason, Requested.

When there is nothing to show: *No approval decisions in the time range (or no role requires approval).*

#### Decisions by approver

*Table · Log Analytics* · reads `AuditLogs`, `Event`

Columns: Decision Time, Decision, Approver, Requester, Role Name, Area, Top-tier decisions, Comment.

When there is nothing to show: *No approval decisions in the time range.*

> Approvals happen only for roles whose PIM settings require them. *Minutes to decide* runs from the latest request for the same person and role before the decision, so it can be wrong when one person makes several requests for one role close together. PIM lets a request expire after 24 hours, so older unanswered requests are not listed as waiting. An approver who approves most requests within a minute or two is unlikely to be checking them.

## Tab: Assignments

### Entra ID roles

#### Role assignments made outside PIM

*Table · Log Analytics* · reads `AuditLogs`

Columns: Assigned, Source, Actor, Assignee, Assignee type, Role, Result.

When there is nothing to show: *No roles were assigned outside PIM in the time range.*

#### Eligible and active assignments made or removed in PIM

*Table · Log Analytics* · reads `AuditLogs`

Columns: Changed, Operation, Actor, Assignee, Role, Area, Top tier, Duration, Result.

When there is nothing to show: *No PIM assignment changes in the time range.*

### Applications

#### Application permissions, credentials and owners

*Table · Log Analytics* · reads `AuditLogs`

Columns: Changed, Kind, Risky, App, Operation, Actor, Result.

When there is nothing to show: *No application permission or credential changes.*

> *Risky* permissions let an application make itself or anyone else an administrator (for example `RoleManagement.ReadWrite.Directory` or `AppRoleAssignment.ReadWrite.All`). A credential added to an application that already holds such a permission is worth checking.

### Azure

#### Owner and access administrator assignments

*Table · Azure Resource Graph* · reads `authorizationresources`

When there is nothing to show: *No Owner or access administrator assignments.*

#### Owner and access administrator assignments made (activity log)

*Table · Log Analytics* · reads `AzureActivity`

Columns: Assigned, Role, Scope, Principal id, Principal type, Caller.

When there is nothing to show: *No Owner or access administrator assignments were made in the time range (or the activity log is not sent to this workspace).*

> Resource Graph shows assignments active now, including those activated through PIM for their duration, and holds principal ids only. Assign these roles to groups managed in PIM rather than to people directly.

## Tab: Sign-ins

> Set **Break-glass accounts** at the top to watch the emergency access accounts. They should never sign in outside a tested emergency.

#### Break-glass account sign-ins

*Table · Log Analytics* · reads `SigninLogs`, `AADNonInteractiveUserSignInLogs`

Columns: Signed in, User, Kind, Result, App, IP address, Country, Conditional Access.

When there is nothing to show: *No sign-ins by the break-glass accounts in the time range.*

#### How privileged accounts sign in

*Table · Log Analytics* · reads `AuditLogs`, `SigninLogs`

Columns: User, Weakest method, Sign-ins, Phishing-resistant, Other MFA, Single factor, Apps, Last sign-in.

When there is nothing to show: *No successful sign-ins by privileged accounts in the time range.*

> *Phishing-resistant* means a FIDO2 key, passkey, Windows Hello for Business or certificate. A sign-in that reuses an earlier MFA from the same session counts as *other MFA*, so an account can show some even when it always uses a passkey. Require an authentication strength in Conditional Access for admin roles to close the gap.

#### Risky sign-ins by privileged accounts

*Table · Log Analytics* · reads `AuditLogs`, `SigninLogs`

Columns: Signed in, User, Risk, Risk state, Result, App, IP address, Country.

When there is nothing to show: *No medium or high risk sign-ins by privileged accounts.*

#### Legacy authentication sign-ins

*Table · Log Analytics* · reads `AuditLogs`, `SigninLogs`

Columns: User, Privileged, Client, Sign Ins, Succeeded, Last seen.

When there is nothing to show: *No legacy authentication sign-ins in the time range.*

#### Changes to Conditional Access, authentication and PIM role settings

*Table · Log Analytics* · reads `AuditLogs`

Columns: Changed, Operation, Actor, Target, Result.

When there is nothing to show: *No policy changes in the time range.*
