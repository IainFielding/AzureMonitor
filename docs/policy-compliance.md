# Azure Policy Compliance

*Reference for [policy-compliance.workbook.json](../workbook/policy-compliance.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

Compliance, exemptions, regulatory frameworks, remediation and governance hygiene across the tenant, using **Azure Resource Graph**. Data is the latest evaluation result for each resource (Azure Policy re-evaluates about every 24 hours, and after a resource changes).

**Compliance %** is the share of evaluated resources with no non-compliant policy states. Exempt and unknown count as compliant, as in the Azure portal. You need **Reader** on the tenant root management group to see everything.

It has 55 panels across 8 tabs. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Management group | Includes everything under the selected management groups, plus policies inherited from above them. |
| Subscription | Lists only subscriptions under the selected management groups. |
| Resource category | Groups resource types by service area, based on the resource provider. |
| Policy category | Policy definition metadata category (e.g. Storage, Security Center). |
| Effect |  |
| Initiative | Limits results to policies assigned through the selected initiatives. 'Standalone policies' covers policies assigned on their own. |
| Compliance state | Filters individual policy evaluation results (one per resource and policy). Choosing Non-compliant shows only failing results. |
| Expiry status |  |
| Exemption category |  |
| Initiative (control view) |  |

## Tab: Overview

#### Tiles resources

*Tiles · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

#### Tiles policies

*Tiles · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

#### Tiles exemptions

*Tiles · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

#### Resources by compliance state

*Pie chart · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

#### Resources by category

*Bar chart · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

#### Non-compliant resources by effect

*Pie chart · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

#### Compliance by management group (includes child groups)

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: Management group, Subscriptions, Resources, Non-compliant, Compliance %.

#### Compliance by subscription

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: Subscription, Parent MG, Resources, Non-compliant, Compliance %, Last evaluated.

#### Top 15 non-compliant policies

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: subscription Id, compliance State, resource Id, resource Type, resource Group, resource Location, assignment Id, assignment Name, definition Id, definition Ref Id, set Definition Id, effect, group Names, evaluated On.

#### Top 15 resource groups by non-compliant resources

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: subscription Id, compliance State, resource Id, resource Type, Resource group, resource Location, assignment Id, assignment Name, definition Id, definition Ref Id, set Definition Id, effect, group Names, evaluated On.

## Tab: Policies & assignments

> Click a policy to list its non-compliant resources. The assignments table covers assignments at, above or below the selected scope.

#### Policy compliance (click a row for details)

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: Policy, Policy category, Type, Status, Effects, Assignments, Resources, Non-compliant, Exempt, Compliance %.

#### Non-compliant resources for the selected policy

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: Resource, Resource type, Category, Subscription, Resource group, Effect, Assignment, Evaluated.

#### Non-compliant resources by policy category

*Bar chart · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

#### Assignments by scope level and type

*Pie chart · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

#### Policy assignments

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: Assignment, Type, Scope level, Scope, Enforcement, Identity, Exclusions, Non-compliance message, Resources, Non-compliant, Compliance %, Open.

## Tab: Resources

#### Compliance by resource type

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: subscription Id, compliance State, resource Id, Resource type, resource Group, resource Location, assignment Id, assignment Name, definition Id, definition Ref Id, set Definition Id, effect, group Names, evaluated On.

#### Non-compliant resources by region

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: subscription Id, compliance State, resource Id, resource Type, resource Group, Location, assignment Id, assignment Name, definition Id, definition Ref Id, set Definition Id, effect, group Names, evaluated On.

#### Resources (click a row to see every policy that applies to it)

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: Status, Resource, Resource type, Category, Subscription, Resource group, Location, Failing policies, Failing policies (first 5), Last evaluated.

#### Policy states for the selected resource

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: State, Policy, Policy category, Effect, Assignment, Reference ID, Evaluated.

## Tab: Exemptions

#### Tiles

*Tiles · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

#### Exemptions by expiry status

*Pie chart · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

#### Exemption expiries over the next 12 months

*Bar chart · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

When there is nothing to show: *No exemptions expire in the next 12 months.*

#### Exemptions by scope and subscription

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

#### Expiring within 30 days

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: Exemption, Days left, Expires, Category, Scope level, Exempted scope, Assignment, Subscription, Open.

When there is nothing to show: *Nothing expires in the next 30 days.*

#### Exemption register

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: Exemption, Status, Days left, Expires, Category, Scope level, Exempted scope, Resource category, Assignment, Assignment status, Covers, Subscription, Justification, Metadata, Open.

#### Exempt resources by assignment (from evaluation results)

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: subscription Id, compliance State, resource Id, resource Type, resource Group, resource Location, Assignment, assignment Name, definition Id, definition Ref Id, set Definition Id, effect, group Names, evaluated On.

## Tab: Regulatory frameworks

> Shows initiatives (policy sets) assigned in scope. Pick an initiative to see compliance for each control or group. Built-in regulatory initiatives such as CIS Azure Foundations, NIST SP 800-53 Rev. 5, ISO 27001 and Microsoft Cloud Security Benchmark map their policies to controls. Click a control to list its failing resources.

#### Compliance by assigned initiative

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: Initiative, Type, Resources, Non-compliant, Compliance %.

#### Control tiles

*Tiles · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

#### Failing controls by domain

*Bar chart · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

#### Controls (click a row for failing resources)

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: Status, Control, Domain, Resources, Non-compliant, Compliance %.

#### Failing resources for the selected control

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: Resource, Resource type, Subscription, Resource group, Policy, Effect, Evaluated.

## Tab: Remediation

> Policies with **DeployIfNotExists** or **Modify** effects can fix non-compliant resources by running a remediation task. Assignments with no managed identity cannot remediate. Create tasks in [Policy > Remediation](https://portal.azure.com/#view/Microsoft_Azure_Policy/PolicyMenuBlade/~/Remediation). The other non-compliant resources need manual fixes or an exemption.

#### Tiles

*Tiles · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

#### Remediation backlog by assignment and policy

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: Assignment, Policy, Effect, Non-compliant resources, Subscriptions, Managed identity, Enforcement, Reference ID (for remediation task), Open.

When there is nothing to show: *No remediable non-compliance in the current filter.*

#### Top manual fixes (Audit / AuditIfNotExists / Deny)

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: subscription Id, compliance State, resource Id, resource Type, resource Group, resource Location, assignment Id, assignment Name, definition Id, definition Ref Id, set Definition Id, Effect, group Names, evaluated On.

## Tab: Public exposure

> Resources reachable from the internet, read from the live resource configuration (not from policy results). The **Management group**, **Subscription** and **Resource category** filters apply here. The policy filters (category, effect, initiative, state) apply only to the policy table at the bottom of this tab.

#### Tiles

*Tiles · Azure Resource Graph* · reads `resourcecontainers`

#### Nsg tiles

*Tiles · Azure Resource Graph* · reads `resourcecontainers`

#### NSG inbound rules open to the internet

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Severity, NSG, Rule, Priority, Source, Ports, Sensitive ports, Attached, Subscription, Resource group, Open.

When there is nothing to show: *No NSG rules allow inbound traffic from the internet.*

#### PaaS network exposure

*Pie chart · Azure Resource Graph* · reads `resourcecontainers`

#### Public IPs by what they are attached to

*Pie chart · Azure Resource Graph* · reads `resourcecontainers`

#### Open PaaS by resource type

*Table · Azure Resource Graph* · reads `resourcecontainers`

#### PaaS services with a public endpoint

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Exposure, Resource, Resource type, Category, Public network access, Firewall default action, Private endpoints, Subscription, Resource group, Location.

When there is nothing to show: *No PaaS services expose a public endpoint.*

#### Storage account exposure and hardening

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Storage account, Anonymous blob access, Network, HTTPS only, Min TLS, Shared key access, Issues, Subscription, Resource group.

When there is nothing to show: *All storage accounts block anonymous access, restrict networks, and enforce HTTPS and TLS 1.2.*

#### Virtual machines with public IPs

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Virtual machine, Public IP, DNS name, Sku, NIC NSG, Network interface, Subscription, Resource group.

When there is nothing to show: *No virtual machines have a public IP.*

#### AKS API server exposure

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Exposure, Cluster, Authorized IP ranges, Version, Local accounts, Subscription, Resource group.

When there is nothing to show: *No AKS clusters in scope.*

#### App Service and Functions exposure

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Exposure, App, Kind, HTTPS only, Client certificates, Default host name, Subscription, Resource group.

When there is nothing to show: *No App Service or Functions apps in scope.*

#### Application gateways

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: WAF, Gateway, Public frontend, Sku, Subscription, Resource group.

When there is nothing to show: *No application gateways in scope.*

#### Public IP inventory

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Public IP, IP address, DNS name, Attached to, Status, Sku, Allocation, DDoS protection, Subscription, Resource group, Location.

#### Exposure-related policy compliance

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: subscription Id, compliance State, resource Id, resource Type, resource Group, resource Location, assignment Id, assignment Name, definition Id, definition Ref Id, set Definition Id, effect, group Names, evaluated On.

When there is nothing to show: *No exposure-related policies are assigned in scope. Consider assigning the built-in 'Microsoft cloud security benchmark' initiative.*

## Tab: Governance hygiene

> Configuration gaps that weaken your policy controls or leave stale objects behind.

#### Assignments in DoNotEnforce mode (audit only, Deny/Modify not applied)

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: Assignment, Type, Scope level, Scope, description, Open.

When there is nothing to show: *All assignments are enforced.*

#### Assignments with no non-compliance message

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: Assignment, Type, Scope level, Scope, Open.

When there is nothing to show: *Every assignment has a non-compliance message.*

#### Assignment exclusions (notScopes)

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: Assignment, Scope level, Scope, Excluded scope, Open.

When there is nothing to show: *No assignments have exclusions.*

#### Deprecated or preview policies being evaluated

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: subscription Id, compliance State, resource Id, resource Type, resource Group, resource Location, assignment Id, assignment Name, definition Id, definition Ref Id, set Definition Id, effect, group Names, evaluated On.

When there is nothing to show: *No deprecated or preview policies are in use.*

#### Exemptions to clean up (expired or orphaned)

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: Exemption, Status, Expires, Assignment, Scope level, Exempted scope, Open.

When there is nothing to show: *No expired or orphaned exemptions.*

#### Subscriptions with no policy evaluation results

*Table · Azure Resource Graph* · reads `resourcecontainers`, `policyresources`

Columns: Subscription, Parent MG, State, Subscription ID.

When there is nothing to show: *Every subscription in scope has evaluation results.*

#### Custom policy definitions not assigned or used in any initiative

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: Policy, Category, Mode, Defined at, Open.

When there is nothing to show: *Every custom definition is in use.*

> Data source: Azure Resource Graph (latest policy state for each resource). Resource Graph keeps no history, so for compliance trends export policy states to Log Analytics or Event Grid.
