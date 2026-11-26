# Expiry and renewals

*Reference for [expiry.workbook.json](../workbook/expiry.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

Everything with a date the platform team has to act on before it passes: certificates, Key Vault objects, storage keys, AVD registration tokens, policy exemptions, service retirements, planned maintenance, reservations and savings plans.

It has 19 panels across 4 tabs. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Due within | How far ahead to count something as due. |
| Log Analytics workspace | Optional. The workspace that receives the Key Vault audit logs, for Key Vault's own near-expiry and expired events. |
| Time range | How far back to look for Key Vault expiry events. Key Vault reports near expiry once, about 30 days ahead, so keep this at 30 days or more. |

## Tab: Overview

#### Tile resources

*Tiles · Azure Resource Graph*

#### Tile appgw

*Tiles · Azure Resource Graph*

#### Tile kv policy

*Tiles · Azure Resource Graph* · reads `policyresources`

#### Tile kv events

*Tiles · Log Analytics* · reads `AzureDiagnostics`, `AZKVAuditLogs`

#### Tile exemptions

*Tiles · Azure Resource Graph* · reads `policyresources`

#### Tile retirements

*Tiles · Azure Resource Graph* · reads `advisorresources`

#### Tile maintenance

*Tiles · Azure Resource Graph* · reads `servicehealthresources`

> Each tile counts what falls due in the next **{Days} days** (change the window at the top), plus anything already
> expired. *Certificates on services* are those held on App Service, API Management, Front Door and Entra Domain
> Services (secure LDAP). *Storage account keys* only have a due date when the account has a key expiration policy.
> An expired AVD registration token is normal, so only tokens about to lapse are counted. Reservations and savings
> plans are on their own tab.

#### Certificates, keys and tokens due in the next {Days} days

*Table · Azure Resource Graph*

Columns: Item, Kind, Expires, Days left, State, Renewal, Resource, Resource group.

When there is nothing to show: *Nothing held on a resource falls due in the window.*

#### Policy exemptions expiring in the next {Days} days

*Table · Azure Resource Graph* · reads `policyresources`

Columns: Exemption, Status, Expires, Days left, Category, Assignment, Description, Scope.

When there is nothing to show: *No policy exemptions expire in the window.*

#### Service retirements in the next {Days} days

*Table · Azure Resource Graph* · reads `advisorresources`

Columns: Retiring, Retirement date, Days left, Due, Resources, Examples, Impact, Action.

When there is nothing to show: *Advisor reports no retirements in the window.*

## Tab: Certificates & secrets

### Certificates, keys and tokens held on services

#### Everything with an expiry date

*Table · Azure Resource Graph*

Columns: Item, Kind, Expires, Days left, State, Renewal, Resource, Resource group.

When there is nothing to show: *No App Service, API Management, Front Door or secure LDAP certificates, storage key policies or AVD registration tokens found.*

> *From Key Vault* means the service reads the certificate from a vault and picks up a renewed version by itself, so the date to watch is the vault object's. A *pinned version* is read from Key Vault but by a fixed version, so it still expires: point it at the versionless secret id. Front Door managed certificates renew automatically.

### Application Gateway listener certificates

#### Listener certificates and where they come from

*Table · Azure Resource Graph*

Columns: Application gateway, Certificate, Source, Listeners, Host names, Key Vault secret, Provisioning.

When there is nothing to show: *No Application Gateway has TLS certificates.*

> Resource Graph holds an uploaded certificate only as encoded data, so its expiry date cannot be shown here; open the gateway's *Listeners* blade, or better, move the certificate to Key Vault and reference the versionless secret id so renewals reach the gateway without a change.

### Key Vault certificates, secrets and keys

#### Objects flagged by Azure Policy's Key Vault expiry audits

*Table · Azure Resource Graph* · reads `policyresources`

When there is nothing to show: *No Key Vault object is non-compliant with an expiry policy, or no such policy is assigned (see below).*

> A workbook cannot read inside a vault. Assign the built-in policies *Certificates should not expire within the specified number of days*, *Secrets should have more than the specified number of days before expiration* and *Keys should have more than the specified number of days before expiration* (Audit, with the number of days set to match the window above) at the landing zone root, and every object that is due appears here. Policy evaluates vault contents about once a day.

> Select a **Log Analytics workspace** at the top to add Key Vault's own near-expiry and expired events.

#### Near-expiry and expired events (Key Vault audit log)

*Table · Log Analytics* · reads `AzureDiagnostics`, `AZKVAuditLogs`

When there is nothing to show: *No expiry events in the time range. Key Vault reports near expiry once, about 30 days ahead, so use a time range of 30 days or more; vaults must send audit logs to this workspace.*

> **Not covered:** client secrets and certificates on Entra ID app registrations and service principals are held in Microsoft Graph, which a workbook cannot query. Use Entra ID's *App registrations* blade or a scheduled Graph report for those.

## Tab: Exemptions & retirements

#### Policy exemptions

*Table · Azure Resource Graph* · reads `policyresources`

Columns: Exemption, Status, Expires, Days left, Category, Assignment, Description, Scope.

When there is nothing to show: *No policy exemptions in the selected subscriptions.*

> When an exemption expires, the resources it covered count as non-compliant again, and a *Deny* policy starts refusing changes to them. Renew it, or fix the resource, before the date.

#### Service retirements affecting your resources (Azure Advisor)

*Table · Azure Resource Graph* · reads `advisorresources`

Columns: Retiring, Retirement date, Days left, Due, Resources, Examples, Impact, Action.

When there is nothing to show: *Advisor reports no service retirements for the selected subscriptions.*

#### Planned maintenance and retirement notices (Azure Service Health)

*Table · Azure Resource Graph* · reads `servicehealthresources`

When there is nothing to show: *No active planned maintenance or retirement notices.*

## Tab: Reservations

#### Reservations

*Table · Azure Resource Manager*: `GET /providers/Microsoft.Capacity/reservations`

Columns: Reservation, Expires, Renew, State, Type, Sku, Quantity, Term, Scope.

When there is nothing to show: *No reservations visible. Reading them needs the Reservations Reader role (at the tenant) or a role on each reservation.*

#### Savings plans

*Table · Azure Resource Manager*: `GET /providers/Microsoft.BillingBenefits/savingsPlans`

Columns: Savings plan, Expires, Renew, State, Commitment, Currency, Per, Term, Scope.

When there is nothing to show: *No savings plans visible. Reading them needs the Savings plan Reader role or a role on each plan.*

> Sorted by expiry, soonest first. A reservation with **Renew** off simply stops at its expiry date and the resources it covered go back to pay-as-you-go prices, which shows up as a jump in cost the next day. Turn automatic renewal on, or plan an exchange, before the date. Expired and cancelled reservations stay in the list.
