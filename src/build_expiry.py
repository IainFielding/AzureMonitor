"""Generates the expiry and renewals workbook.

Run:  python src/build_expiry.py
Out:  workbook/expiry.workbook.json

Everything with a date on it that the platform team has to act on before it passes: certificates, Key Vault
secrets and keys, storage account keys, AVD registration tokens, policy exemptions, service retirements, planned
maintenance, reservations and savings plans. The Overview counts what falls due inside the chosen window; each tab
lists everything in its area, soonest first. Built from the helpers in build_workbook.py so the workbooks look alike.

A workbook cannot read inside a key vault, so Key Vault objects come from the vault's own near-expiry events (in the
audit log) and from Azure Policy's Key Vault expiry audits, not from the objects themselves. Application
registration secrets live in Microsoft Graph, which a workbook cannot read either.
"""

import pathlib

from build_workbook import (DAY_MS, ONE_TILE, WORKSPACE_UNSET, arg, arm, big_number_tiles, choice_param,
                            gid, group, high_is_good, la, notebook, params, resource_link, status_fmt,
                            subscription_param, text, time_param, workspace_param, write_workbook)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "expiry.workbook.json"

P = "exp"

TABS = [
    ("overview", "Overview"),
    ("certificates", "Certificates & secrets"),
    ("governance", "Exemptions & retirements"),
    ("commitments", "Reservations"),
]

THREE_TILES = 600

# ---------------------------------------------------------------------------
# Dates held on resources in Resource Graph
# ---------------------------------------------------------------------------

# A secret id that ends in a version is pinned to it: the service keeps using that version after the certificate
# is renewed in the vault, so it expires anyway.
PINNED = r"@'(?i)/secrets/[^/]+/[0-9a-f]{32}/?$'"

# Every dated item held on a resource, one row each. Resource Graph allows few unions per query, so the types are
# read in one pass: `items` holds what each resource has several of (API Management host names, the two storage
# keys), and is expanded once. A storage key only has a due date when the account has a key expiration policy and
# still allows shared key access.
RESOURCE_DATES = r"""
resources
| where type in~ ('microsoft.web/certificates', 'microsoft.apimanagement/service', 'microsoft.aad/domainservices',
    'microsoft.cdn/profiles/secrets', 'microsoft.desktopvirtualization/hostpools', 'microsoft.storage/storageaccounts')
| extend items = case(
    type =~ 'microsoft.apimanagement/service', properties.hostnameConfigurations,
    type =~ 'microsoft.storage/storageaccounts',
        iff(isnull(properties.keyPolicy.keyExpirationPeriodInDays) or tostring(properties.allowSharedKeyAccess) =~ 'false',
            dynamic([]), dynamic(['key1', 'key2'])),
    pack_array(properties))
| mv-expand item = items
| extend Kind = case(
        type =~ 'microsoft.web/certificates', 'App Service certificate',
        type =~ 'microsoft.apimanagement/service', 'API Management certificate',
        type =~ 'microsoft.aad/domainservices', 'Secure LDAP certificate',
        type =~ 'microsoft.cdn/profiles/secrets', 'Front Door certificate',
        type =~ 'microsoft.desktopvirtualization/hostpools', 'AVD registration token',
        'Storage account key'),
    Expires = case(
        type =~ 'microsoft.web/certificates', todatetime(properties.expirationDate),
        type =~ 'microsoft.apimanagement/service', todatetime(item.certificate.expiry),
        type =~ 'microsoft.aad/domainservices',
            iff(tostring(properties.ldapsSettings.ldaps) =~ 'Enabled', todatetime(properties.ldapsSettings.certificateNotAfter), datetime(null)),
        type =~ 'microsoft.cdn/profiles/secrets', todatetime(properties.parameters.expirationDate),
        type =~ 'microsoft.desktopvirtualization/hostpools', todatetime(properties.registrationInfo.expirationTime),
        datetime_add('day', toint(properties.keyPolicy.keyExpirationPeriodInDays), todatetime(properties.keyCreationTime[tostring(item)])))
| where isnotnull(Expires)
| extend kvSecret = tostring(item.keyVaultId)
| extend Item = case(
        type =~ 'microsoft.web/certificates', coalesce(tostring(properties.subjectName), name),
        type =~ 'microsoft.apimanagement/service', strcat(tostring(item.hostName), ' (', tostring(item.type), ')'),
        type =~ 'microsoft.cdn/profiles/secrets', coalesce(tostring(properties.parameters.subject), name),
        type =~ 'microsoft.storage/storageaccounts', strcat(name, ' ', tostring(item)),
        name),
    Renewal = case(
        type =~ 'microsoft.cdn/profiles/secrets' and tostring(properties.parameters.type) =~ 'ManagedCertificate', 'Automatic',
        type =~ 'microsoft.cdn/profiles/secrets' and tostring(properties.parameters.useLatestVersion) =~ 'true', 'From Key Vault',
        type =~ 'microsoft.apimanagement/service' and isnotempty(kvSecret),
            iff(kvSecret matches regex """ + PINNED + r""", 'Key Vault, pinned version', 'From Key Vault'),
        type =~ 'microsoft.web/certificates' and isnotempty(tostring(properties.keyVaultId)), 'From Key Vault',
        type =~ 'microsoft.storage/storageaccounts', 'Rotate the key',
        type =~ 'microsoft.desktopvirtualization/hostpools', 'New token when adding hosts',
        'Manual'),
    DaysLeft = datetime_diff('day', Expires, now())
| extend State = case(
        Kind == 'AVD registration token' and Expires < now(), 'No valid token',
        Expires < now(), 'Expired',
        DaysLeft <= {Days}, 'Due',
        'Later')
| project Item, Kind, Expires, DaysLeft, State, Renewal, id, ResourceGroup = resourceGroup
"""

# An expired registration token is the normal state of a host pool, so it is not something falling due.
RESOURCE_DUE = RESOURCE_DATES + """| where State in ('Due', 'Expired')
"""

RESOURCE_TILES_Q = RESOURCE_DATES + """| extend Group = case(Kind == 'Storage account key', 'Storage account keys',
    Kind == 'AVD registration token', 'AVD registration tokens', 'Certificates on services')
| summarize Due = countif(State == 'Due'), Expired = countif(State == 'Expired'), Total = count() by Group
| join kind=rightouter (
    datatable(Group: string) ['Certificates on services', 'Storage account keys', 'AVD registration tokens']
  ) on Group
| project Signal = Group1, Value = coalesce(Due, 0) + coalesce(Expired, 0),
    Detail = strcat(coalesce(Expired, 0), ' expired · ', coalesce(Total, 0), ' tracked'),
    State = case(Group1 == 'AVD registration tokens', iff(coalesce(Due, 0) > 0, 'Unknown', 'Available'),
        coalesce(Expired, 0) > 0, 'Unavailable', coalesce(Due, 0) > 0, 'Degraded', 'Available')
"""

# ---------------------------------------------------------------------------
# Application Gateway listener certificates
# ---------------------------------------------------------------------------

# Resource Graph holds an uploaded certificate only as encoded data, so its expiry cannot be read; a certificate
# referenced from Key Vault by its latest version is renewed with the vault object.
APPGW_CERTS = r"""
resources
| where type =~ 'microsoft.network/applicationgateways'
| mv-expand cert = properties.sslCertificates
| extend CertId = tolower(tostring(cert.id)), KvSecret = tostring(cert.properties.keyVaultSecretId)
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.network/applicationgateways'
    | mv-expand l = properties.httpListeners
    | extend CertId = tolower(tostring(l.properties.sslCertificate.id))
    | where isnotempty(CertId)
    | summarize Listeners = strcat_array(make_set(tostring(l.name)), ', '),
        HostNames = strcat_array(make_set(coalesce(tostring(l.properties.hostName), tostring(l.properties.hostNames[0]))), ', ')
        by CertId
  ) on CertId
| extend Source = case(isempty(KvSecret), 'Uploaded', KvSecret matches regex """ + PINNED + r""", 'Key Vault, pinned version',
    'Key Vault, latest version')
"""

APPGW_TILE_Q = APPGW_CERTS + """| summarize Total = count(), Manual = countif(Source != 'Key Vault, latest version')
| project Signal = 'App Gateway certificates renewed by hand', Value = Manual,
    Detail = strcat('of ', Total, ' listener certificates'), State = iff(Manual > 0, 'Degraded', 'Available')
"""

APPGW_Q = APPGW_CERTS + """| project id, Certificate = tostring(cert.name), Source, Listeners, HostNames, KeyVaultSecret = KvSecret,
    Provisioning = tostring(cert.properties.provisioningState)
| order by case(Source == 'Uploaded', 0, Source == 'Key Vault, pinned version', 1, 2) asc, id asc
"""

# ---------------------------------------------------------------------------
# Key Vault
# ---------------------------------------------------------------------------

# Azure Policy's Key Vault data-plane audits evaluate every certificate, secret and key, so their non-compliant
# results are a list of objects expiring soon (or with no expiry date) across every vault.
KV_POLICY = r"""
policyresources
| where type =~ 'microsoft.policyinsights/policystates'
| where tostring(properties.resourceType) startswith 'Microsoft.KeyVault.Data/'
| where tostring(properties.complianceState) =~ 'NonCompliant'
| extend definitionId = tolower(tostring(properties.policyDefinitionId)), rid = tostring(properties.resourceId)
| join kind=leftouter (
    policyresources
    | where type =~ 'microsoft.authorization/policydefinitions'
    | project definitionId = tolower(id), Policy = tostring(properties.displayName)
  ) on definitionId
| where isempty(Policy) or Policy has_any ('expir', 'validity')
| extend Problem = case(Policy has_any ('not expire within', 'more than the specified number of days'), 'Expires soon',
        Policy has 'expiration date', 'No expiry date', Policy has 'validity', 'Validity too long', 'Non-compliant'),
    Kind = case(rid has '/certificates/', 'Certificate', rid has '/secrets/', 'Secret', rid has '/keys/', 'Key', 'Other'),
    Vault = extract(@'(?i)/vaults/([^/]+)', 1, rid),
    Object = tostring(split(trim_end('/', rid), '/')[-1])
"""

KV_POLICY_TILE_Q = KV_POLICY + """| summarize Soon = dcountif(rid, Problem == 'Expires soon'), NoExpiry = dcountif(rid, Problem == 'No expiry date'),
    Vaults = dcount(Vault)
| project Signal = 'Key Vault objects expiring soon (Policy)', Value = Soon,
    Detail = strcat(NoExpiry, ' with no expiry date · ', Vaults, ' vaults'),
    State = iff(Soon > 0, 'Degraded', 'Available')
"""

KV_POLICY_Q = KV_POLICY + """| summarize Policies = strcat_array(make_set(Policy), '; ') by Vault, Kind, Object, Problem
| order by case(Problem == 'Expires soon', 0, Problem == 'No expiry date', 1, 2) asc, Vault asc, Object asc
"""

# Key Vault writes a near-expiry event about 30 days before an object expires, and an expired event when it does,
# to either the legacy or the resource-specific audit table.
KV_EVENTS = """
union isfuzzy=true
    (AzureDiagnostics | where TimeGenerated {TimeRange} | where ResourceProvider =~ 'MICROSOFT.KEYVAULT'
        | project TimeGenerated, OperationName, Vault = tolower(Resource), Object = column_ifexists('id_s', '')),
    (AZKVAuditLogs | where TimeGenerated {TimeRange}
        | project TimeGenerated, OperationName, Vault = tolower(tostring(split(_ResourceId, '/')[8])), Object = column_ifexists('Id', ''))
| where OperationName contains 'NearExpiry' or OperationName contains 'Expired'
| extend Kind = case(OperationName startswith 'Certificate', 'Certificate', OperationName startswith 'Secret', 'Secret',
        OperationName startswith 'Key', 'Key', 'Other'),
    State = iff(OperationName contains 'NearExpiry', 'Near expiry', 'Expired')
| summarize LastSeen = max(TimeGenerated) by Vault, Kind, Object, State
"""

KV_EVENTS_TILE_Q = KV_EVENTS + """| summarize Near = dcountif(Object, State == 'Near expiry'), Expired = dcountif(Object, State == 'Expired'),
    Vaults = dcount(Vault)
| project Signal = 'Key Vault expiry events (logs)', Value = Near + Expired,
    Detail = strcat(Expired, ' expired · ', Vaults, ' vaults'),
    State = case(Expired > 0, 'Unavailable', Near > 0, 'Degraded', 'Available')
"""

KV_EVENTS_Q = KV_EVENTS + """| order by case(State == 'Expired', 0, 1) asc, LastSeen desc
"""

# ---------------------------------------------------------------------------
# Exemptions, retirements and maintenance
# ---------------------------------------------------------------------------

EXEMPTIONS = """
policyresources
| where type =~ 'microsoft.authorization/policyexemptions'
| extend Expires = todatetime(properties.expiresOn),
    Scope = tostring(split(tolower(id), '/providers/microsoft.authorization/policyexemptions/')[0])
| extend DaysLeft = datetime_diff('day', Expires, now())
| extend Status = case(isnull(Expires), 'No expiry', Expires < now(), 'Expired', DaysLeft <= {Days}, 'Due', 'Later')
"""

EXEMPTIONS_TILE_Q = EXEMPTIONS + """| summarize Due = countif(Status == 'Due'), Expired = countif(Status == 'Expired'), Never = countif(Status == 'No expiry')
| project Signal = 'Policy exemptions expiring', Value = Due,
    Detail = strcat(Expired, ' already expired · ', Never, ' never expire'),
    State = case(Expired > 0 or Due > 0, 'Degraded', 'Available')
"""

EXEMPTIONS_Q = EXEMPTIONS + """| project Exemption = coalesce(tostring(properties.displayName), name), Status, Expires, DaysLeft,
    Category = tostring(properties.exemptionCategory),
    Assignment = tostring(split(tostring(properties.policyAssignmentId), '/')[-1]),
    Description = tostring(properties.description), Scope
| order by case(Status == 'Expired', 0, Status == 'Due', 1, Status == 'No expiry', 3, 2) asc, Expires asc
"""

RETIREMENTS = """
advisorresources
| where type =~ 'microsoft.advisor/recommendations'
| where tostring(properties.extendedProperties.recommendationSubCategory) =~ 'ServiceUpgradeAndRetirement'
| extend RetirementDate = todatetime(properties.extendedProperties.retirementDate),
    Retiring = coalesce(tostring(properties.extendedProperties.retirementFeatureName), tostring(properties.shortDescription.problem)),
    rid = tolower(tostring(properties.resourceMetadata.resourceId))
| extend DaysLeft = datetime_diff('day', RetirementDate, now())
"""

RETIREMENTS_TILE_Q = RETIREMENTS + """| summarize Features = dcountif(Retiring, DaysLeft <= {Days}), Resources = dcountif(rid, DaysLeft <= {Days})
| project Signal = 'Service retirements', Value = Features, Detail = strcat(Resources, ' resources affected'),
    State = iff(Features > 0, 'Degraded', 'Available')
"""

RETIREMENTS_Q = RETIREMENTS + """| summarize Resources = dcount(rid), Examples = strcat_array(make_set(tostring(split(rid, '/')[-1]), 5), ', ')
    by Retiring, RetirementDate, DaysLeft, Impact = tostring(properties.impact), Action = tostring(properties.shortDescription.solution)
| extend Due = iff(DaysLeft <= {Days}, 'Yes', '')
| project Retiring, RetirementDate, DaysLeft, Due, Resources, Examples, Impact, Action
| order by RetirementDate asc
"""

MAINTENANCE = """
servicehealthresources
| where type =~ 'microsoft.resourcehealth/events'
| where tostring(properties.Status) =~ 'Active'
| extend EventType = tostring(properties.EventType), Title = tostring(properties.Title)
| where EventType =~ 'PlannedMaintenance' or tostring(properties.EventSubType) =~ 'Retirement' or Title contains 'retir'
| extend Kind = iff(EventType =~ 'PlannedMaintenance', 'Planned maintenance', 'Retirement'),
    Starts = todatetime(tolong(properties.ImpactStartTime)), Ends = todatetime(tolong(properties.ImpactMitigationTime))
"""

MAINTENANCE_TILE_Q = MAINTENANCE + """| summarize Maintenance = dcountif(tostring(properties.TrackingId), Kind == 'Planned maintenance'),
    Notices = dcountif(tostring(properties.TrackingId), Kind == 'Retirement')
| project Signal = 'Planned maintenance notices', Value = Maintenance, Detail = strcat(Notices, ' retirement notices'),
    State = iff(Maintenance + Notices > 0, 'Degraded', 'Available')
"""

MAINTENANCE_Q = MAINTENANCE + """| summarize Subscriptions = dcount(subscriptionId) by Kind, Title, TrackingId = tostring(properties.TrackingId), Starts, Ends
| order by Starts asc
"""

TILE_NOTE = """\
Each tile counts what falls due in the next **{Days} days** (change the window at the top), plus anything already
expired. *Certificates on services* are those held on App Service, API Management, Front Door and Entra Domain
Services (secure LDAP). *Storage account keys* only have a due date when the account has a key expiration policy.
An expired AVD registration token is normal, so only tokens about to lapse are counted. Reservations and savings
plans are on their own tab."""

# ---------------------------------------------------------------------------
# Parameters and tabs
# ---------------------------------------------------------------------------


def global_params():
    return params(f"{P}-params", [
        subscription_param(P),
        choice_param(P, "Days", "Due within",
                     [("30", "30 days"), ("60", "60 days"), ("90", "90 days"), ("180", "180 days"), ("365", "1 year")],
                     "90", "How far ahead to count something as due."),
        workspace_param(P, "Optional. The workspace that receives the Key Vault audit logs, for Key Vault's own "
                           "near-expiry and expired events."),
        time_param(P, 30 * DAY_MS, [d * DAY_MS for d in (7, 14, 30, 60, 90)],
                   "How far back to look for Key Vault expiry events. Key Vault reports near expiry once, about "
                   "30 days ahead, so keep this at 30 days or more."),
        {"id": gid(f"{P}-param-selectedTab"), "version": "KqlParameterItem/1.0", "name": "selectedTab", "type": 1,
         "value": "overview", "isHiddenWhenLocked": True},
    ])


def tabs():
    return {"type": 11, "content": {"version": "LinkItem/1.0", "style": "tabs", "links": [
        {"id": gid(f"{P}-tab-" + key), "cellValue": "selectedTab", "linkTarget": "parameter",
         "linkLabel": label, "subTarget": key, "style": "link"} for key, label in TABS
    ]}, "name": f"{P}-tabs"}


TILES = big_number_tiles("Signal", "State", "Value", "Detail")
STATE = status_fmt("State", good=["Later"], warn=["Due"], bad=["Expired"], neutral=["No valid token"])
RENEWAL = status_fmt("Renewal", good=["Automatic", "From Key Vault"], warn=["Key Vault, pinned version", "Manual"])
DAYS_LEFT = high_is_good("DaysLeft", 60, 30)
DATED_LABELS = {"id": "Resource", "DaysLeft": "Days left", "ResourceGroup": "Resource group"}


def overview_tab():
    return group(f"{P}-tab-overview", [
        arg(f"{P}-tile-resources", "", RESOURCE_TILES_Q, vis="tiles", tiles=TILES, fixed_px=THREE_TILES),
        arg(f"{P}-tile-appgw", "", APPGW_TILE_Q, vis="tiles", tiles=TILES, fixed_px=ONE_TILE),
        arg(f"{P}-tile-kv-policy", "", KV_POLICY_TILE_Q, vis="tiles", tiles=TILES, fixed_px=ONE_TILE),
        la(f"{P}-tile-kv-events", "", KV_EVENTS_TILE_Q, vis="tiles", tiles=TILES, fixed_px=ONE_TILE),
        arg(f"{P}-tile-exemptions", "", EXEMPTIONS_TILE_Q, vis="tiles", tiles=TILES, fixed_px=ONE_TILE),
        arg(f"{P}-tile-retirements", "", RETIREMENTS_TILE_Q, vis="tiles", tiles=TILES, fixed_px=ONE_TILE),
        arg(f"{P}-tile-maintenance", "", MAINTENANCE_TILE_Q, vis="tiles", tiles=TILES, fixed_px=ONE_TILE),
        text(f"{P}-tile-note", TILE_NOTE, "info"),
        arg(f"{P}-due", "Certificates, keys and tokens due in the next {Days} days", RESOURCE_DUE + "| order by Expires asc",
            formatters=[resource_link(), STATE, RENEWAL, DAYS_LEFT], labels=DATED_LABELS,
            no_data="Nothing held on a resource falls due in the window."),
        arg(f"{P}-due-exemptions", "Policy exemptions expiring in the next {Days} days",
            EXEMPTIONS_Q.replace("| order by", "| where Status in ('Due', 'Expired')\n| order by"),
            formatters=[status_fmt("Status", warn=["Due"], bad=["Expired"]), DAYS_LEFT],
            labels={"DaysLeft": "Days left"}, width=50, no_data="No policy exemptions expire in the window."),
        arg(f"{P}-due-retirements", "Service retirements in the next {Days} days",
            RETIREMENTS_Q.replace("| order by", "| where Due == 'Yes'\n| order by"),
            formatters=[DAYS_LEFT, status_fmt("Impact", warn=["Medium"], bad=["High"])],
            labels={"RetirementDate": "Retirement date", "DaysLeft": "Days left"}, width=50,
            no_data="Advisor reports no retirements in the window."),
    ], tab="overview")


def certificates_tab():
    return group(f"{P}-tab-certificates", [
        text(f"{P}-services-h", "### Certificates, keys and tokens held on services"),
        arg(f"{P}-dated", "Everything with an expiry date", RESOURCE_DATES + "| order by Expires asc",
            formatters=[resource_link(), STATE, RENEWAL, DAYS_LEFT], labels=DATED_LABELS, group_by="Kind",
            no_data="No App Service, API Management, Front Door or secure LDAP certificates, storage key policies or "
                    "AVD registration tokens found."),
        text(f"{P}-dated-note", "*From Key Vault* means the service reads the certificate from a vault and picks up "
             "a renewed version by itself, so the date to watch is the vault object's. A *pinned version* is read "
             "from Key Vault but by a fixed version, so it still expires: point it at the versionless secret id. "
             "Front Door managed certificates renew automatically.", "info"),
        text(f"{P}-appgw-h", "### Application Gateway listener certificates"),
        arg(f"{P}-appgw", "Listener certificates and where they come from", APPGW_Q,
            formatters=[resource_link(), status_fmt("Source", good=["Key Vault, latest version"],
                                                     warn=["Key Vault, pinned version", "Uploaded"])],
            labels={"id": "Application gateway", "HostNames": "Host names", "KeyVaultSecret": "Key Vault secret"},
            no_data="No Application Gateway has TLS certificates."),
        text(f"{P}-appgw-note", "Resource Graph holds an uploaded certificate only as encoded data, so its expiry "
             "date cannot be shown here; open the gateway's *Listeners* blade, or better, move the certificate to "
             "Key Vault and reference the versionless secret id so renewals reach the gateway without a change.",
             "info"),
        text(f"{P}-kv-h", "### Key Vault certificates, secrets and keys"),
        arg(f"{P}-kv-policy", "Objects flagged by Azure Policy's Key Vault expiry audits", KV_POLICY_Q,
            formatters=[status_fmt("Problem", warn=["Expires soon", "Validity too long"], neutral=["No expiry date"])],
            no_data="No Key Vault object is non-compliant with an expiry policy, or no such policy is assigned (see "
                    "below)."),
        text(f"{P}-kv-policy-note", "A workbook cannot read inside a vault. Assign the built-in policies "
             "*Certificates should not expire within the specified number of days*, *Secrets should have more than "
             "the specified number of days before expiration* and *Keys should have more than the specified number "
             "of days before expiration* (Audit, with the number of days set to match the window above) at the "
             "landing zone root, and every object that is due appears here. Policy evaluates vault contents about "
             "once a day.", "info"),
        text(f"{P}-kv-hint", "Select a **Log Analytics workspace** at the top to add Key Vault's own near-expiry and "
             "expired events.", "info", visible_when=WORKSPACE_UNSET),
        la(f"{P}-kv-events", "Near-expiry and expired events (Key Vault audit log)", KV_EVENTS_Q,
           formatters=[status_fmt("State", warn=["Near expiry"], bad=["Expired"])], labels={"LastSeen": "Reported"},
           no_data="No expiry events in the time range. Key Vault reports near expiry once, about 30 days ahead, so "
                   "use a time range of 30 days or more; vaults must send audit logs to this workspace."),
        text(f"{P}-graph-note", "**Not covered:** client secrets and certificates on Entra ID app registrations and "
             "service principals are held in Microsoft Graph, which a workbook cannot query. Use Entra ID's *App "
             "registrations* blade or a scheduled Graph report for those.", "warning"),
    ], tab="certificates")


def governance_tab():
    return group(f"{P}-tab-governance", [
        arg(f"{P}-exemptions", "Policy exemptions", EXEMPTIONS_Q,
            formatters=[status_fmt("Status", good=["Later"], warn=["Due", "No expiry"], bad=["Expired"]), DAYS_LEFT],
            labels={"DaysLeft": "Days left"}, no_data="No policy exemptions in the selected subscriptions."),
        text(f"{P}-exemptions-note", "When an exemption expires, the resources it covered count as non-compliant "
             "again, and a *Deny* policy starts refusing changes to them. Renew it, or fix the resource, before the "
             "date.", "info"),
        arg(f"{P}-retirements", "Service retirements affecting your resources (Azure Advisor)", RETIREMENTS_Q,
            formatters=[DAYS_LEFT, status_fmt("Due", warn=["Yes"]), status_fmt("Impact", warn=["Medium"], bad=["High"])],
            labels={"RetirementDate": "Retirement date", "DaysLeft": "Days left"},
            no_data="Advisor reports no service retirements for the selected subscriptions."),
        arg(f"{P}-maintenance", "Planned maintenance and retirement notices (Azure Service Health)", MAINTENANCE_Q,
            formatters=[status_fmt("Kind", warn=["Planned maintenance", "Retirement"])],
            labels={"TrackingId": "Tracking ID"}, no_data="No active planned maintenance or retirement notices."),
    ], tab="governance")


RESERVATION_STATE = status_fmt("State", good=["Succeeded"], warn=["Expiring", "PendingRenewal"],
                               bad=["Expired"], neutral=["Cancelled", "Split", "Merged"])


def _ascending(item, column):
    item["content"]["gridSettings"]["sortBy"] = [{"itemKey": column, "sortOrder": 1}]
    return item


def commitments_tab():
    return group(f"{P}-tab-commitments", [
        _ascending(arm(f"{P}-reservations", "Reservations", "/providers/Microsoft.Capacity/reservations", "2022-11-01", [
            ("Reservation", "$.properties.displayName", None),
            ("Expires", "$.properties.expiryDateTime", "datetime"),
            ("Renew", "$.properties.renew", None),
            ("State", "$.properties.displayProvisioningState", None),
            ("Type", "$.properties.reservedResourceType", None),
            ("Sku", "$.sku.name", None),
            ("Quantity", "$.properties.quantity", None),
            ("Term", "$.properties.term", None),
            ("Scope", "$.properties.userFriendlyAppliedScopeType", None),
        ], no_data="No reservations visible. Reading them needs the Reservations Reader role (at the tenant) or a "
                   "role on each reservation.",
            formatters=[RESERVATION_STATE, status_fmt("Renew", good=["true"], warn=["false"])]), "Expires"),
        _ascending(arm(f"{P}-savings-plans", "Savings plans", "/providers/Microsoft.BillingBenefits/savingsPlans",
                       "2022-11-01", [
            ("SavingsPlan", "$.properties.displayName", None),
            ("Expires", "$.properties.expiryDateTime", "datetime"),
            ("Renew", "$.properties.renew", None),
            ("State", "$.properties.displayProvisioningState", None),
            ("Commitment", "$.properties.commitment.amount", None),
            ("Currency", "$.properties.commitment.currencyCode", None),
            ("Per", "$.properties.commitment.grain", None),
            ("Term", "$.properties.term", None),
            ("Scope", "$.properties.appliedScopeType", None),
        ], no_data="No savings plans visible. Reading them needs the Savings plan Reader role or a role on each plan.",
            formatters=[RESERVATION_STATE, status_fmt("Renew", good=["true"], warn=["false"])],
            labels={"SavingsPlan": "Savings plan"}), "Expires"),
        text(f"{P}-commitments-note", "Sorted by expiry, soonest first. A reservation with **Renew** off simply stops "
             "at its expiry date and the resources it covered go back to pay-as-you-go prices, which shows up as a "
             "jump in cost the next day. Turn automatic renewal on, or plan an exchange, before the date. Expired "
             "and cancelled reservations stay in the list.", "info"),
    ], tab="commitments")


def workbook():
    return notebook([
        text(f"{P}-header", "# Expiry and renewals\n"
             "Everything with a date the platform team has to act on before it passes: certificates, Key Vault "
             "objects, storage keys, AVD registration tokens, policy exemptions, service retirements, planned "
             "maintenance, reservations and savings plans."),
        global_params(),
        tabs(),
        overview_tab(),
        certificates_tab(),
        governance_tab(),
        commitments_tab(),
    ])


def main():
    write_workbook(OUT, workbook())


if __name__ == "__main__":
    main()
