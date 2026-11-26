# Cloud Center of Excellence

*Reference for [cloud-center-of-excellence.workbook.json](../workbook/cloud-center-of-excellence.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

One scorecard for the team that sets cloud standards: governance and tagging, landing zone placement, security posture and privileged access, savings and idle resources, monitoring, patching and retirements, by subscription. Read from Azure Resource Graph: no workspace needed. You need **Reader** across the subscriptions (at the tenant root management group to see everything).

It has 45 panels across 6 tabs. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Required tags | Comma-separated tag names every resource should carry, as your tagging policy sets out. Compared without case. |
| Owner tag | The tag on a subscription that names its owner, shown beside each subscription. |
| Approved regions | Optional. Comma-separated Azure region names (for example uksouth,ukwest). Resources elsewhere are counted on the Scorecard and listed on Governance & tagging. |

## Tab: Scorecard

### Govern

#### Tile policy

*Tiles · Azure Resource Graph* · reads `policyresources`

#### Tile tags

*Tiles · Azure Resource Graph*

#### Tile placement

*Tiles · Azure Resource Graph* · reads `resourcecontainers`

#### Tile regions

*Tiles · Azure Resource Graph*

### Secure

#### Tile defender

*Tiles · Azure Resource Graph* · reads `securityresources`

#### Tile owners

*Tiles · Azure Resource Graph* · reads `authorizationresources`

### Manage cost

#### Tile savings

*Tiles · Azure Resource Graph* · reads `advisorresources`

#### Tile waste

*Tiles · Azure Resource Graph*

### Operate

#### Tile advisor

*Tiles · Azure Resource Graph* · reads `advisorresources`

#### Tile agents

*Tiles · Azure Resource Graph*

#### Tile retirements

*Tiles · Azure Resource Graph* · reads `advisorresources`

> **How to read this.** Each tile is one measure the CCoE owns; a green tick means nothing needs action, amber means
> some subscriptions are behind. *Policy compliance* is the share of evaluated resources with no failing policy (as in
> the Azure portal). *Tag coverage* counts resources that carry every tag in **Required tags**, ignoring the
> platform's own types that nobody tags (extensions, Network Watcher). *Privileged roles* are Owner, User Access
> Administrator and RBAC Administrator assigned to a user rather than a group. *Idle resources* are unattached disks,
> unused public IPs, stopped but billed VMs, empty App Service plans, unused load balancers and NAT gateways, and old
> snapshots. *Advisor savings* is Azure Advisor's own estimate, a year. Advisor high-impact issues and the Defender for
> Cloud secure score are the same figures as on the Platform health overview.

#### Scorecard by subscription

*Table · Azure Resource Graph* · reads `resourcecontainers`, `policyresources`, `securityresources`

Columns: Subscription, Parent management group, Placement, Owner, Resources, Tag coverage %, Policy compliance %, Secure score %.

When there is nothing to show: *No subscriptions selected.*

## Tab: Landing zones

> Where subscriptions sit in the management group hierarchy, and how the estate is growing. In an Azure landing zone every subscription belongs under a landing zone, platform, sandbox or decommissioned management group; one *directly under the tenant root* gets none of the policies or access set on those groups.

#### Subscriptions by parent management group

*Bar chart · Azure Resource Graph* · reads `resourcecontainers`

#### Subscriptions by offer

*Pie chart · Azure Resource Graph* · reads `resourcecontainers`

#### Subscriptions

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Subscription, State, Placement, Parent management group, Owner, Offer, Resources, Resource groups, Regions.

When there is nothing to show: *No subscriptions selected.*

#### Resources created and deleted per day (last 14 days)

*Bar chart · Azure Resource Graph* · reads `resourcechanges`

When there is nothing to show: *No resources created or deleted in the last 14 days.*

#### Most common resource types

*Table · Azure Resource Graph*

#### Resources by region

*Pie chart · Azure Resource Graph*

> Resource Graph keeps 14 days of change history, so growth is shown for that window only. For a resource-by-resource view of the changes, use the **What changed?** workbook.

## Tab: Governance & tagging

> Policy compliance and tagging by subscription. For the detail behind a low score (which policies fail, exemptions, regulatory initiatives) open the **Azure Policy compliance** workbook.

#### Azure Policy compliance by subscription

*Table · Azure Resource Graph* · reads `policyresources`, `resourcecontainers`

Columns: Subscription, Parent management group, Owner, Evaluated, Non-compliant resources, Failing policies, Compliance %.

When there is nothing to show: *No policy evaluation results in the selected subscriptions.*

### Tagging
Measured against **Required tags** at the top. Tags inherited from a resource group by policy (*Inherit a tag from the resource group*) are written to the resource and count; tags only on the resource group do not.

#### Coverage by tag

*Table · Azure Resource Graph*

Columns: Tag, Coverage %, Tagged, Resources without it.

When there is nothing to show: *Set Required tags at the top.*

#### Coverage by subscription

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Subscription, Coverage %, Missing a tag, Resources.

When there is nothing to show: *Set Required tags at the top.*

#### Subscriptions missing required tags

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Subscription, Missing.

When there is nothing to show: *Every subscription carries every required tag.*

#### Resource groups missing required tags

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Resource group, Missing, Subscription.

When there is nothing to show: *Every resource group carries every required tag.*

#### Resources missing required tags

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Resource, Type, Missing, Resource group, Subscription.

When there is nothing to show: *Every resource carries every required tag.*

### Regions

#### Resources outside the approved regions

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Region, Subscription, Resources.

When there is nothing to show: *Every resource is in an approved region (or is global).*

## Tab: Cost

> Savings the CCoE can chase, by subscription. Resource Graph holds no spend: for actual and forecast cost use Cost Management, or the **FinOps hubs** data, which this workbook does not read.

#### Cost tiles

*Tiles · Azure Resource Graph* · reads `advisorresources`

#### Advisor savings by subscription (a year)

*Table · Azure Resource Graph* · reads `advisorresources`, `resourcecontainers`

Columns: Subscription, Savings, Currency, Recommendations.

When there is nothing to show: *Advisor has no cost recommendations for the selected subscriptions.*

#### Advisor cost recommendations

*Table · Azure Resource Graph* · reads `advisorresources`

Columns: Recommendation, Savings, Currency, Resources, Subscriptions, Impact, Action.

When there is nothing to show: *Advisor has no cost recommendations for the selected subscriptions.*

### Idle resources

#### Idle resources by subscription

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Subscription, Idle, Kinds.

When there is nothing to show: *No idle resources found.*

#### Licences paid in the VM price (Azure Hybrid Benefit not used)

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Subscription, Gap, Machines.

When there is nothing to show: *Every Windows and SQL Server VM uses Azure Hybrid Benefit.*

#### Idle resources

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Resource, Kind, Detail, What to do, Resource group, Subscription.

When there is nothing to show: *No idle resources found.*

> Azure Hybrid Benefit only applies where you hold Windows Server or SQL Server licences with Software Assurance (or subscriptions); check with whoever manages licensing before switching it on. Windows client VMs (Azure Virtual Desktop) need the licence type *Windows_Client*.

## Tab: Security & identity

> Security posture and privileged access by subscription. The **Platform health** Security tab has the alerts and recommendations behind these figures; the **Privileged access** workbook has activations, approvals and sign-ins.

#### Defender for Cloud secure score

*Table · Azure Resource Graph* · reads `securityresources`, `resourcecontainers`

Columns: Subscription, Score %, Points, Out of.

When there is nothing to show: *No secure score: Defender for Cloud is not reporting for the selected subscriptions.*

#### Defender for Cloud plans

*Table · Azure Resource Graph* · reads `securityresources`, `resourcecontainers`

Columns: Subscription, Plans on %, On, Off, Plans off.

When there is nothing to show: *No Defender for Cloud plans found.*

#### High-severity recommendations by subscription

*Table · Azure Resource Graph* · reads `securityresources`, `resourcecontainers`

Columns: Subscription, Recommendations, Resources.

When there is nothing to show: *No unhealthy high-severity recommendations.*

#### Roles that can grant access, by scope

*Table · Azure Resource Graph* · reads `authorizationresources`

#### Assigned to users directly, at subscription scope or above

*Table · Azure Resource Graph* · reads `authorizationresources`, `resourcecontainers`

Columns: Scope level, Scope, Role, User object ID.

When there is nothing to show: *Every privileged role at subscription scope or above is assigned to a group or identity.*

#### Custom roles with wildcard actions

*Table · Azure Resource Graph* · reads `authorizationresources`

Columns: Role, Wildcard, Actions, Assignable scopes.

When there is nothing to show: *No custom roles use wildcard actions.*

> Resource Graph has object IDs, not names: look a user up in Entra ID, or use the **Privileged access** workbook, which reads names from the sign-in logs. Assigning roles to groups (made eligible through PIM) keeps access reviewable.

## Tab: Operations

> How well the estate is run, by subscription: monitoring, patching, Advisor's high-impact issues, changes made by hand, and what Azure is retiring. The **Platform health** Monitoring and Governance tabs list the machines behind these figures.

#### Monitoring agent on machines

*Pie chart · Azure Resource Graph*

When there is nothing to show: *No VMs or Arc servers in the selected subscriptions.*

#### Azure Monitor Agent coverage by subscription

*Table · Azure Resource Graph* · reads `resourcecontainers`

Columns: Subscription, Coverage %, Machines, Legacy agent only, No agent.

When there is nothing to show: *No VMs or Arc servers in the selected subscriptions.*

#### Patching by subscription (Azure Update Manager)

*Table · Azure Resource Graph* · reads `patchassessmentresources`, `resourcecontainers`

Columns: Subscription, Machines, Up to date %, Critical or security due, Not assessed in 7 days, Reboot pending.

When there is nothing to show: *No VMs or Arc servers in the selected subscriptions.*

#### Advisor high-impact recommendations by subscription

*Table · Azure Resource Graph* · reads `advisorresources`, `resourcecontainers`

Columns: Subscription, Total, Reliability, Security, Cost, Operations, Performance.

When there is nothing to show: *Advisor has no high-impact recommendations.*

#### Changes by tool (last 14 days)

*Pie chart · Azure Resource Graph* · reads `resourcechanges`

When there is nothing to show: *No changes recorded in the last 14 days.*

#### Changes made in the Azure portal, by subscription (last 14 days)

*Table · Azure Resource Graph* · reads `resourcechanges`, `resourcecontainers`

Columns: Subscription, Made in the portal %, Portal changes, Changes.

When there is nothing to show: *No changes recorded in the last 14 days.*

#### Azure retirements within 180 days (Azure Advisor)

*Table · Azure Resource Graph* · reads `advisorresources`

Columns: Retiring, Retirement date, Days left, Resources, Subscriptions, Action.

When there is nothing to show: *Advisor reports no retirements in the next 180 days.*

#### Resources currently unavailable or degraded (Resource Health)

*Table · Azure Resource Graph* · reads `healthresources`, `resourcecontainers`

Columns: Resource, State, Reason, Since, Summary, Subscription.

When there is nothing to show: *Resource Health reports nothing unavailable or degraded.*

> A high share of changes made in the portal means changes are bypassing the pipelines (infrastructure as code) the platform relies on. Some portal changes are expected: incident fixes and sandbox subscriptions.
