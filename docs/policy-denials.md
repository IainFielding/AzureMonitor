# Why was this request refused?

*Reference for [policy-denials.workbook.json](../workbook/policy-denials.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

Azure Policy denials and the other reasons Resource Manager refuses a request (permissions, locks, quota, template errors), and for a policy: which assignment, which policy, the values that failed it, and how to exempt or exclude.

It has 9 panels. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Search | Optional. A correlation id, or part of a resource name or id, deployment name or caller. |
| Log Analytics workspace | The workspace the subscriptions' activity log is sent to. Needed for the refused requests. |
| Time range | Applies to the activity log panels. |
| Policy assignment | Pick one, or select a row in a table above. |

## Panels

> Paste anything you have into **Search**: the correlation id from the error, the resource or deployment name, or
> the caller. Leave it empty to see every refused request in the time range.
>
> **Fixing a policy denial.** In order of preference:
> 1. **Change the request** to meet the policy (*Why it was denied* shows the field, its value and what the policy
>    expects: an allowed location, a SKU, a tag, private access only).
> 2. **Exempt** the resource or resource group from that assignment, as *Waiver* or *Mitigated*, ideally with an
>    expiry date. An exemption can name single policies of an initiative.
> 3. **Exclude** the scope from the assignment (*notScopes*), or set the policy's effect parameter to *Audit*.
>
> Setting the assignment's enforcement mode to *DoNotEnforce* stops every policy in it denying anywhere it applies:
> use it to unblock a change in an emergency, then put it back. Policy changes and new exemptions can take a few
> minutes to apply.

> Select the **Log Analytics workspace** your subscriptions send their activity log to (`AzureActivity`) to see refused requests. The policy panels further down work without one.

#### Tiles

*Tiles · Log Analytics* · reads `AzureActivity`

When there is nothing to show: *No refused requests in the time range.*

#### Refused requests (latest 500)

*Table · Log Analytics* · reads `AzureActivity`

Columns: Time, Reason, Code, Operation, Resource, Caller, Error, Action needed, At scope, Correlation id.

When there is nothing to show: *No refused requests. Widen the time range or clear Search.*

> *Permissions* means the caller lacks the role for that action at that scope (see *Action* and *Scope*); a
> *LinkedAuthorizationFailed* means it also needs rights on a resource it references, such as the subnet or key
> vault. *Resource lock* means a CanNotDelete or ReadOnly lock on the resource, its resource group or subscription.
> *Azure restriction* is a region or service the subscription is not allowed to use, which policy does not control:
> raise a support request.

#### Policy denials: which assignment, which policy, and why

*Table · Log Analytics* · reads `AzureActivity`

Columns: Time, Resource, Caller, Assignment, Policy, Initiative, Policy reference id, Effect, Why it was denied, Assigned at, Assignment id, Correlation id.

When there is nothing to show: *No policy denials in the time range. Check *Refused requests* above for other reasons.*

### Policy assignments

#### Policies that deny, and the existing resources they find non-compliant

*Table · Azure Resource Graph* · reads `policyresources`

Columns: Assignment, Policy, Effect, Enforcement, Non-compliant, Resources evaluated, Scope, Policy reference id, Assignment id.

When there is nothing to show: *No policy with a deny effect has evaluated a resource in the selected subscriptions.*

#### The assignment

*Table · Azure Resource Graph* · reads `policyresources`

Columns: Assignment, Kind, Definition, Scope, Excluded scopes (notScopes), Enforcement, Effect overrides, Resource selectors, Non-compliance message, Identity, Created, Updated.

When there is nothing to show: *Assignment not found in the selected subscriptions.*

#### Policies in the assignment and the effect each resolves to

*Table · Azure Resource Graph* · reads `policyresources`

Columns: Policy, Effect, Category, Policy reference id, Definition.

When there is nothing to show: *Could not read the assignment's definition.*

#### Exemptions from the assignment

*Table · Azure Resource Graph* · reads `policyresources`

Columns: Exemption, Scope, Category, Policies, Expires, Status, Description.

When there is nothing to show: *No exemptions from this assignment.*

#### Resources the assignment finds non-compliant (latest 500)

*Table · Azure Resource Graph* · reads `policyresources`

Columns: Resource, Policy reference id, Effect, Evaluated.

When there is nothing to show: *No non-compliant resources (or none match Search).*

### Locks

#### Locks (matching Search, if given)

*Table · Azure Resource Graph*

Columns: Lock, Level, Scope, Notes.

When there is nothing to show: *No locks in the selected subscriptions (or none on the resource in Search).*
