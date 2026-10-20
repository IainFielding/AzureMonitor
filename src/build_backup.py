"""Generates the backup and recovery workbook: Azure Backup, Site Recovery, SQL and Storage.

Run:  python src/build_backup.py
Out:  workbook/backup-recovery.workbook.json

Is everything that should be backed up or replicated protected, is it working, and could it be restored?
Mostly Azure Resource Graph, so it works without a workspace; job history and Site Recovery RPO trends come
from Log Analytics when a workspace is selected, and the few settings Resource Graph does not index (SQL
long-term retention backups, storage soft delete) come from Azure Resource Manager. Built from the helpers in
build_workbook.py so the workbooks look alike.
"""

import json
import pathlib

from build_workbook import (DAY_MS, ONE_TILE, PROVISIONING, WORKSPACE_SET, WORKSPACE_UNSET, arg, arm,
                            big_number_tiles, gid, group, la, params, resource_link, resource_param, status_fmt, text)

OUT = pathlib.Path(__file__).resolve().parent.parent / "workbook" / "backup-recovery.workbook.json"

TABS = [
    ("overview", "Overview"),
    ("backup", "Azure Backup"),
    ("asr", "Site Recovery"),
    ("sql", "SQL"),
    ("storage", "Storage"),
]

# ---------------------------------------------------------------------------
# Shared Resource Graph fragments
# ---------------------------------------------------------------------------

RSV_ITEM = "microsoft.recoveryservices/vaults/backupfabrics/protectioncontainers/protecteditems"
RSV_JOB = "microsoft.recoveryservices/vaults/backupjobs"
BV_INSTANCE = "microsoft.dataprotection/backupvaults/backupinstances"
BV_JOB = "microsoft.dataprotection/backupvaults/backupjobs"
ASR_ITEM = "microsoft.recoveryservices/vaults/replicationfabrics/replicationprotectioncontainers/replicationprotecteditems"
ASR_JOB = "microsoft.recoveryservices/vaults/replicationjobs"
ASR_PLAN = "microsoft.recoveryservices/vaults/replicationrecoveryplans"

# Backup jobs from both kinds of vault, in one shape.
JOBS = f"""
recoveryservicesresources
| where type in~ ('{RSV_JOB}', '{BV_JOB}')
| extend Started = todatetime(properties.startTime)
| where Started >= todatetime('{{TimeRange:startISO}}')
| extend VaultKind = iff(type =~ '{RSV_JOB}', 'Recovery Services', 'Backup vault'),
    Vault = tostring(split(id, '/')[8]),
    Item = coalesce(tostring(properties.entityFriendlyName), tostring(properties.dataSourceName)),
    Workload = coalesce(tostring(properties.backupManagementType), tostring(properties.dataSourceType)),
    Operation = coalesce(tostring(properties.operation), tostring(properties.operationCategory)),
    Status = tostring(properties.status),
    Duration = todatetime(properties.endTime) - Started,
    Error = coalesce(tostring(properties.extendedInfo.propertyBag['Error Code']), tostring(properties.errorDetails[0].errorCode),
        tostring(properties.extendedInfo.errorDetails[0].errorCode))"""

# Everything protected or replicated, each with the problem it has (empty when healthy). Order matters: the
# first problem found is the one shown.
ATTENTION = f"""
recoveryservicesresources
| where type in~ ('{RSV_ITEM}', '{BV_INSTANCE}', '{ASR_ITEM}')
| extend Vault = tostring(split(id, '/')[8]), Item = tostring(properties.friendlyName),
    LastBackup = todatetime(properties.lastBackupTime), TestFailover = todatetime(properties.lastSuccessfulTestFailoverTime)
// Site Recovery reports "never" as 0001-01-01.
| extend TestFailover = iff(TestFailover < datetime(2000-01-01), datetime(null), TestFailover)
| extend Kind = case(
    type =~ '{ASR_ITEM}', 'Site Recovery',
    type =~ '{BV_INSTANCE}', strcat('Backup vault: ', tostring(split(tostring(properties.dataSourceInfo.datasourceType), '/')[-1])),
    strcat('Backup: ', tostring(properties.workloadType)))
| extend Problem = case(
    type =~ '{ASR_ITEM}' and tostring(properties.replicationHealth) !~ 'Normal',
        strcat('Replication ', tostring(properties.replicationHealth), ': ', tostring(properties.healthErrors[0].errorMessage)),
    type =~ '{ASR_ITEM}' and (isnull(TestFailover) or TestFailover < ago({{TestFailoverDays}}d)),
        iff(isnull(TestFailover), 'Never test failed over', 'No test failover in {{TestFailoverDays}} days'),
    type =~ '{BV_INSTANCE}' and tostring(properties.protectionStatus.status) !~ 'ProtectionConfigured',
        strcat('Protection ', tostring(properties.protectionStatus.status), ' ', tostring(properties.protectionStatus.errorDetails.message)),
    type =~ '{RSV_ITEM}' and tostring(properties.lastBackupStatus) =~ 'Failed', 'Last backup failed',
    type =~ '{RSV_ITEM}' and tostring(properties.healthStatus) =~ 'ActionRequired', 'Action required',
    type =~ '{RSV_ITEM}' and tostring(properties.protectionState) =~ 'Protected' and LastBackup < ago({{StaleHours}}h),
        strcat('No backup for ', datetime_diff('hour', now(), LastBackup), ' hours'),
    type =~ '{RSV_ITEM}' and tostring(properties.protectionState) in~ ('ProtectionStopped', 'ProtectionPaused', 'ProtectionError'),
        strcat('Protection ', tostring(properties.protectionState)),
    '')
| extend Severity = case(Problem has_any ('failed', 'Critical', 'Action required', 'ProtectionError', 'No backup for', 'Never'), 'Critical',
    isnotempty(Problem), 'Warning', '')"""

# Protected items only list what is enrolled, so a machine that was never added to a vault is found by starting
# from the machines instead.
VM_PROTECTION = f"""
resources
| where type =~ 'microsoft.compute/virtualmachines'
| project id = tolower(id),
    OS = tostring(properties.storageProfile.osDisk.osType),
    Power = tostring(properties.extended.instanceView.powerState.displayStatus),
    ResourceGroup = resourceGroup, Location = location
| join kind=leftouter (
    recoveryservicesresources
    | where type =~ '{RSV_ITEM}' and tostring(properties.backupManagementType) =~ 'AzureIaasVM' or type =~ '{ASR_ITEM}'
    | extend isBackup = type =~ '{RSV_ITEM}'
    | project isBackup, vmId = tolower(iff(isBackup,
            coalesce(tostring(properties.sourceResourceId), tostring(properties.virtualMachineId)),
            coalesce(tostring(properties.providerSpecificDetails.fabricObjectId),
                tostring(properties.providerSpecificDetails.protectedManagedDisks[0].sourceManagedDiskId)))),
        vault = iff(isBackup, tostring(split(id, '/')[8]), ''),
        lastBackup = iff(isBackup, todatetime(properties.lastBackupTime), datetime(null))
    | where isBackup and isnotempty(vmId) or vmId has '/virtualmachines/'
    | summarize Vault = max(vault), LastBackup = max(lastBackup), Replicated = countif(not(isBackup)) by id = vmId
  ) on id
| project id, Protection = iff(isempty(Vault), 'Not protected', 'Protected'), Vault, LastBackup,
    Replication = iff(Replicated > 0, 'Replicated', ''), OS, Power, ResourceGroup, Location"""

# ---------------------------------------------------------------------------
# Overview tiles
# ---------------------------------------------------------------------------

TILES = [
    ("jobs", JOBS + """
| summarize Failed = countif(Status =~ 'Failed'), Jobs = count()
| project Signal = 'Failed backup jobs', Value = Failed, Detail = strcat('of ', Jobs, ' jobs in the time range'),
    State = case(Jobs == 0, 'Unknown', Failed > 0, 'Unavailable', 'Available')
"""),
    ("attention", ATTENTION + """
| where Kind !~ 'Site Recovery'
| summarize Critical = countif(Severity == 'Critical'), Warning = countif(Severity == 'Warning'), Total = count()
| project Signal = 'Backup items with problems', Value = Critical + Warning,
    Detail = strcat(Critical, ' critical, ', Warning, ' warning, of ', Total),
    State = case(Total == 0, 'Unknown', Critical > 0, 'Unavailable', Warning > 0, 'Degraded', 'Available')
"""),
    ("vms", VM_PROTECTION + """
| summarize Unprotected = countif(Protection == 'Not protected'), Total = count()
| project Signal = 'VMs with no backup', Value = Unprotected, Detail = strcat('of ', Total, ' virtual machines'),
    State = case(Total == 0, 'Unknown', Unprotected > 0, 'Degraded', 'Available')
"""),
    ("asr", ATTENTION + """
| where Kind == 'Site Recovery'
| summarize Unhealthy = countif(Problem startswith 'Replication'), NoTest = countif(Problem has 'test failover' or Problem has 'test failed'),
    Total = count()
| project Signal = 'Replication problems', Value = Unhealthy,
    Detail = strcat(NoTest, ' of ', Total, ' not test failed over in {TestFailoverDays} days'),
    State = case(Total == 0, 'Unknown', Unhealthy > 0, 'Unavailable', NoTest > 0, 'Degraded', 'Available')
"""),
    ("vaults", """
resources
| where type in~ ('microsoft.recoveryservices/vaults', 'microsoft.dataprotection/backupvaults')
| extend SoftDelete = coalesce(tostring(properties.securitySettings.softDeleteSettings.softDeleteState),
        tostring(properties.securitySettings.softDeleteSettings.state)),
    Immutability = tostring(properties.securitySettings.immutabilitySettings.state)
| summarize Weak = countif(SoftDelete !in~ ('AlwaysON', 'Enabled', 'On') or Immutability !in~ ('Locked', 'Unlocked')), Total = count()
| project Signal = 'Vaults without soft delete or immutability', Value = Weak, Detail = strcat('of ', Total, ' vaults'),
    State = case(Total == 0, 'Unknown', Weak > 0, 'Degraded', 'Available')
"""),
    ("sql", """
resources
| where type in~ ('microsoft.sql/servers/databases', 'microsoft.sql/managedinstances')
| where name !~ 'master'
| extend Redundancy = coalesce(tostring(properties.currentBackupStorageRedundancy), tostring(properties.requestedBackupStorageRedundancy))
| summarize Local = countif(Redundancy =~ 'Local'), Total = count()
| project Signal = 'SQL with local-only backups', Value = Local, Detail = strcat('of ', Total, ' databases and managed instances'),
    State = case(Total == 0, 'Unknown', Local > 0, 'Degraded', 'Available')
"""),
]

TILE_NOTE = """\
Thresholds: a backup is *stale* when the last one is older than **{StaleHours} hours**, and a replicated item is
due a test failover after **{TestFailoverDays} days**. Change them at the top. *Local-only* SQL backups (LRS)
cannot be restored if the region is lost."""

# ---------------------------------------------------------------------------
# Azure Backup tab
# ---------------------------------------------------------------------------

RSV_VAULTS_Q = """
resources
| where type =~ 'microsoft.recoveryservices/vaults'
| project id,
    Redundancy = tostring(properties.redundancySettings.standardTierStorageRedundancy),
    CrossRegionRestore = tostring(properties.redundancySettings.crossRegionRestore),
    SoftDelete = tostring(properties.securitySettings.softDeleteSettings.softDeleteState),
    SoftDeleteDays = toint(properties.securitySettings.softDeleteSettings.softDeleteRetentionPeriodInDays),
    Immutability = tostring(properties.securitySettings.immutabilitySettings.state),
    MultiUserAuth = tostring(properties.securitySettings.multiUserAuthorization),
    JobFailureAlerts = tostring(properties.monitoringSettings.azureMonitorAlertSettings.alertsForAllJobFailures),
    PublicNetwork = tostring(properties.publicNetworkAccess),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup, Location = location
"""

BACKUP_VAULTS_Q = """
resources
| where type =~ 'microsoft.dataprotection/backupvaults'
| project id,
    Redundancy = tostring(properties.storageSettings[0].type),
    CrossRegionRestore = tostring(properties.featureSettings.crossRegionRestoreSettings.state),
    SoftDelete = tostring(properties.securitySettings.softDeleteSettings.state),
    SoftDeleteDays = toint(properties.securitySettings.softDeleteSettings.retentionDurationInDays),
    Immutability = tostring(properties.securitySettings.immutabilitySettings.state),
    JobFailureAlerts = tostring(properties.monitoringSettings.azureMonitorAlertSettings.alertsForAllJobFailures),
    Provisioning = tostring(properties.provisioningState),
    ResourceGroup = resourceGroup, Location = location
"""

VAULT_FORMATTERS = [
    resource_link(), PROVISIONING,
    status_fmt("Redundancy", good=["GeoRedundant", "GeoRedundantStorage"], warn=["ZoneRedundant", "ZoneRedundantStorage"],
               bad=["LocallyRedundant", "LocallyRedundantStorage"]),
    status_fmt("CrossRegionRestore", good=["Enabled", "true"], neutral=["Disabled", "false", ""]),
    status_fmt("SoftDelete", good=["AlwaysON", "Enabled", "On"], bad=["Disabled", "Off"]),
    status_fmt("Immutability", good=["Locked", "Unlocked"], warn=["Disabled", ""]),
    status_fmt("MultiUserAuth", good=["Enabled"], neutral=["Disabled", ""]),
    status_fmt("JobFailureAlerts", good=["Enabled"], warn=["Disabled", ""]),
]

VAULT_LABELS = {"id": "Vault", "CrossRegionRestore": "Cross-region restore", "SoftDelete": "Soft delete",
                "SoftDeleteDays": "Soft delete days", "MultiUserAuth": "Multi-user authorisation",
                "JobFailureAlerts": "Job failure alerts", "PublicNetwork": "Public network"}

ITEMS_BY_WORKLOAD_Q = f"""
recoveryservicesresources
| where type in~ ('{RSV_ITEM}', '{BV_INSTANCE}')
| extend Workload = iff(type =~ '{RSV_ITEM}', tostring(properties.workloadType),
    tostring(split(tostring(properties.dataSourceInfo.datasourceType), '/')[-1]))
| extend Healthy = iff(type =~ '{RSV_ITEM}',
    tostring(properties.lastBackupStatus) !~ 'Failed' and tostring(properties.healthStatus) !~ 'ActionRequired',
    tostring(properties.protectionStatus.status) =~ 'ProtectionConfigured')
| summarize Items = count(), Problems = countif(not(Healthy)) by Workload
| order by Items desc
"""

ITEMS_Q = f"""
recoveryservicesresources
| where type =~ '{RSV_ITEM}'
| project Vault = tostring(split(id, '/')[8]),
    Item = tostring(properties.friendlyName),
    Workload = tostring(properties.workloadType),
    Health = tostring(properties.healthStatus),
    LastBackup = tostring(properties.lastBackupStatus),
    LastBackupTime = todatetime(properties.lastBackupTime),
    Protection = tostring(properties.protectionState),
    Policy = tostring(properties.policyName),
    Archive = tostring(properties.isArchiveEnabled),
    Source = tostring(properties.sourceResourceId)
| extend AgeHours = datetime_diff('hour', now(), LastBackupTime)
| extend Age = case(Protection !~ 'Protected', '', AgeHours > {{StaleHours}}, 'Stale', 'OK')
| project-reorder Vault, Item, Workload, Health, LastBackup, LastBackupTime, AgeHours, Age
| order by case(LastBackup =~ 'Failed', 0, Health =~ 'ActionRequired', 1, Age == 'Stale', 2, 3) asc, LastBackupTime asc
"""

INSTANCES_Q = f"""
recoveryservicesresources
| where type =~ '{BV_INSTANCE}'
| project Vault = tostring(split(id, '/')[8]),
    Instance = tostring(properties.friendlyName),
    Datasource = tostring(split(tostring(properties.dataSourceInfo.datasourceType), '/')[-1]),
    Status = tostring(properties.protectionStatus.status),
    State = tostring(properties.currentProtectionState),
    Error = tostring(properties.protectionStatus.errorDetails.message),
    Policy = tostring(split(tostring(properties.policyInfo.policyId), '/')[-1]),
    Source = tostring(properties.dataSourceInfo.resourceID)
| order by case(Status =~ 'ProtectionConfigured', 1, 0) asc, Vault asc
"""

JOBS_BY_DAY_Q = JOBS + """
| summarize Jobs = count() by Day = bin(Started, 1d), Status
| order by Day asc
"""

JOBS_FAILED_Q = JOBS + """
| where Status !in~ ('Completed', 'InProgress')
| project Started, VaultKind, Vault, Item, Workload, Operation, Status, Error, Duration
| order by Started desc
| take 500
"""

# Resource-specific Azure Backup tables (diagnostic setting on each vault, "Resource specific" mode).
LA_BACKUP = """
union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (AddonAzureBackupJobs)
| where TimeGenerated {TimeRange}
| extend Operation = tostring(column_ifexists('JobOperation', '')), Status = tostring(column_ifexists('JobStatus', '')),
    FailureCode = tostring(column_ifexists('JobFailureCode', '')), Workload = tostring(column_ifexists('BackupManagementType', '')),
    Item = tostring(column_ifexists('BackupItemUniqueId', '')), DurationMin = todouble(column_ifexists('JobDurationInSecs', 0)) / 60.0
"""

LA_JOBS_TREND_Q = LA_BACKUP + """
| where Operation == 'Backup'
| summarize Jobs = count() by bin(TimeGenerated, {TimeRange:grain}), Status
"""

LA_FAILURE_CODES_Q = LA_BACKUP + """
| where Status == 'Failed'
| summarize Failures = count(), Items = dcount(Item), LastSeen = max(TimeGenerated) by FailureCode, Operation, Workload
| order by Failures desc
"""

LA_DURATION_Q = LA_BACKUP + """
| where Operation == 'Backup' and Status == 'Completed'
| summarize ['p95 minutes'] = percentile(DurationMin, 95) by bin(TimeGenerated, {TimeRange:grain}), Workload
"""

# ---------------------------------------------------------------------------
# Site Recovery tab
# ---------------------------------------------------------------------------

ASR_ITEMS_Q = f"""
recoveryservicesresources
| where type =~ '{ASR_ITEM}'
| extend TestFailover = todatetime(properties.lastSuccessfulTestFailoverTime)
| extend TestFailover = iff(TestFailover < datetime(2000-01-01), datetime(null), TestFailover)
| project Vault = tostring(split(id, '/')[8]),
    Item = tostring(properties.friendlyName),
    Health = tostring(properties.replicationHealth),
    State = tostring(properties.protectionStateDescription),
    Scenario = tostring(properties.providerSpecificDetails.instanceType),
    RpoMinutes = round(todouble(properties.providerSpecificDetails.rpoInSeconds) / 60.0, 1),
    ActiveLocation = tostring(properties.activeLocation),
    Primary = tostring(properties.primaryFabricFriendlyName),
    Recovery = tostring(properties.recoveryFabricFriendlyName),
    TestFailover,
    TestDue = case(isnull(TestFailover), 'Never', TestFailover < ago({{TestFailoverDays}}d), 'Overdue', 'OK'),
    FailoverHealth = tostring(properties.failoverHealth),
    Error = tostring(properties.healthErrors[0].errorMessage),
    Policy = tostring(properties.policyFriendlyName)
| order by case(Health =~ 'Critical', 0, Health =~ 'Warning', 1, TestDue != 'OK', 2, 3) asc, Vault asc
"""

ASR_SUMMARY_Q = f"""
recoveryservicesresources
| where type =~ '{ASR_ITEM}'
| summarize Items = count(), Critical = countif(tostring(properties.replicationHealth) =~ 'Critical'),
    Warning = countif(tostring(properties.replicationHealth) =~ 'Warning')
    by Vault = tostring(split(id, '/')[8]), Scenario = tostring(properties.providerSpecificDetails.instanceType)
| order by Critical desc, Warning desc
"""

ASR_PLANS_Q = f"""
recoveryservicesresources
| where type =~ '{ASR_PLAN}'
| extend LastTest = todatetime(properties.lastTestFailoverTime)
| project Vault = tostring(split(id, '/')[8]),
    Plan = tostring(properties.friendlyName),
    Scenario = tostring(properties.currentScenario.scenarioName),
    Groups = array_length(properties.groups),
    LastTest,
    TestDue = case(isnull(LastTest) or LastTest < datetime(2000-01-01), 'Never', LastTest < ago({{TestFailoverDays}}d), 'Overdue', 'OK'),
    LastPlannedFailover = todatetime(properties.lastPlannedFailoverTime),
    LastUnplannedFailover = todatetime(properties.lastUnplannedFailoverTime)
| order by case(TestDue == 'OK', 1, 0) asc, Vault asc
"""

ASR_JOBS_Q = f"""
recoveryservicesresources
| where type =~ '{ASR_JOB}'
| extend Started = todatetime(properties.startTime)
| where Started >= todatetime('{{TimeRange:startISO}}')
| where tostring(properties.state) !in~ ('Succeeded', 'InProgress')
| project Started, Vault = tostring(split(id, '/')[8]),
    Job = tostring(properties.friendlyName), Target = tostring(properties.targetObjectName),
    State = tostring(properties.state), Scenario = tostring(properties.scenarioName),
    Error = tostring(properties.errors[0].providerErrorDetails.errorMessage)
| order by Started desc
| take 500
"""

# Resource-specific Site Recovery tables. Column names have changed between versions, so read them loosely.
LA_ASR_RPO_Q = """
union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (AzureSiteRecoveryReplicatedItems)
| where TimeGenerated {TimeRange}
| extend Item = coalesce(tostring(column_ifexists('ReplicatedItemFriendlyName', '')), tostring(column_ifexists('ReplicatedItemName', '')),
        tostring(column_ifexists('ReplicationProtectedItemName', '')), tostring(column_ifexists('ReplicatedItemId', ''))),
    RpoMinutes = todouble(column_ifexists('RpoInSeconds', real(null))) / 60.0
| where isnotnull(RpoMinutes)
| summarize RpoMinutes = max(RpoMinutes) by bin(TimeGenerated, {TimeRange:grain}), Item
| join kind=inner (
    union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (AzureSiteRecoveryReplicatedItems)
    | where TimeGenerated {TimeRange}
    | extend Item = coalesce(tostring(column_ifexists('ReplicatedItemFriendlyName', '')), tostring(column_ifexists('ReplicatedItemName', '')),
            tostring(column_ifexists('ReplicationProtectedItemName', '')), tostring(column_ifexists('ReplicatedItemId', ''))),
        RpoMinutes = todouble(column_ifexists('RpoInSeconds', real(null))) / 60.0
    | summarize Worst = max(RpoMinutes) by Item
    | top 10 by Worst desc
  ) on Item
| project TimeGenerated, Item, RpoMinutes
"""

LA_ASR_JOBS_Q = """
union isfuzzy=true (datatable(TimeGenerated: datetime)[]), (AzureSiteRecoveryJobs)
| where TimeGenerated {TimeRange}
| extend Status = tostring(column_ifexists('Status', '')), Operation = tostring(column_ifexists('OperationName', '')),
    Item = tostring(column_ifexists('AffectedResourceName', ''))
| where Status !in~ ('Succeeded', 'InProgress', '')
| summarize Jobs = count(), LastSeen = max(TimeGenerated) by Operation, Status, Item
| order by LastSeen desc
"""

# ---------------------------------------------------------------------------
# SQL tab
# ---------------------------------------------------------------------------

SQL_DBS_Q = """
resources
| where type =~ 'microsoft.sql/servers/databases'
| where name !~ 'master'
| extend Earliest = todatetime(properties.earliestRestoreDate)
| project id, Server = tostring(split(id, '/')[8]),
    Redundancy = coalesce(tostring(properties.currentBackupStorageRedundancy), tostring(properties.requestedBackupStorageRedundancy)),
    RestoreWindowDays = round(todouble(datetime_diff('minute', now(), Earliest)) / 1440.0, 1),
    EarliestRestore = Earliest,
    Secondary = tostring(properties.secondaryType),
    ZoneRedundant = tostring(properties.zoneRedundant),
    Sku = tostring(sku.name), Status = tostring(properties.status),
    ResourceGroup = resourceGroup, Location = location
| order by case(Redundancy =~ 'Local', 0, 1) asc, RestoreWindowDays asc
"""

SQL_MI_Q = """
resources
| where type =~ 'microsoft.sql/managedinstances'
| project mi = tolower(id), Instance = name,
    Redundancy = coalesce(tostring(properties.currentBackupStorageRedundancy), tostring(properties.requestedBackupStorageRedundancy)),
    ZoneRedundant = tostring(properties.zoneRedundant), State = tostring(properties.state)
| join kind=leftouter (
    resources
    | where type =~ 'microsoft.sql/managedinstances/databases'
    | extend Earliest = todatetime(properties.earliestRestorePoint)
    | summarize Databases = count(), ShortestWindowDays = round(min(todouble(datetime_diff('minute', now(), Earliest))) / 1440.0, 1)
        by mi = tolower(tostring(split(id, '/databases/')[0]))
  ) on mi
| project id = mi, Redundancy, Databases = coalesce(Databases, 0), ShortestWindowDays, ZoneRedundant, State
| order by case(Redundancy =~ 'Local', 0, 1) asc
"""

SQL_FAILOVER_Q = """
resources
| where type =~ 'microsoft.sql/servers/failovergroups'
| project Group = name, Server = tostring(split(id, '/')[8]),
    Role = tostring(properties.replicationRole), State = tostring(properties.replicationState),
    Partner = tostring(split(tostring(properties.partnerServers[0].id), '/')[8]),
    PartnerLocation = tostring(properties.partnerServers[0].location),
    FailoverPolicy = tostring(properties.readWriteEndpoint.failoverPolicy),
    Databases = array_length(properties.databases), ResourceGroup = resourceGroup
| order by Group asc
"""

WORKLOAD_DBS_Q = f"""
recoveryservicesresources
| where type =~ '{RSV_ITEM}'
| where tostring(properties.backupManagementType) =~ 'AzureWorkload'
| extend Container = tostring(split(id, '/')[12])
| project Vault = tostring(split(id, '/')[8]),
    Database = tostring(properties.friendlyName),
    Workload = tostring(properties.workloadType),
    Server = coalesce(tostring(properties.serverName), tostring(properties.parentName)),
    Vm = tostring(split(Container, ';')[-1]),
    LastBackup = tostring(properties.lastBackupStatus),
    LastBackupTime = todatetime(properties.lastBackupTime),
    Health = tostring(properties.healthStatus),
    Protection = tostring(properties.protectionState),
    Policy = tostring(properties.policyName)
| order by case(LastBackup =~ 'Failed', 0, Health =~ 'ActionRequired', 1, 2) asc, LastBackupTime asc
"""

# SQL Server VMs, and whether Azure Backup protects any database on them. A VM that backs up with SQL Server's
# own backup to URL, or another product, shows as none here.
SQL_VMS_Q = f"""
resources
| where type =~ 'microsoft.sqlvirtualmachine/sqlvirtualmachines'
| extend vmId = tolower(tostring(properties.virtualMachineResourceId))
| project id, vmKey = strcat(tostring(split(vmId, '/')[4]), ';', tostring(split(vmId, '/')[8])),
    Image = tostring(properties.sqlImageOffer), Edition = tostring(properties.sqlImageSku),
    License = tostring(properties.sqlServerLicenseType), ResourceGroup = resourceGroup
| join kind=leftouter (
    recoveryservicesresources
    | where type =~ '{RSV_ITEM}'
    | where tostring(properties.workloadType) =~ 'SQLDataBase'
    | extend parts = split(tolower(tostring(split(id, '/')[12])), ';')
    | summarize Protected = count(), LastBackup = max(todatetime(properties.lastBackupTime)),
        Failed = countif(tostring(properties.lastBackupStatus) =~ 'Failed')
        by vmKey = strcat(tostring(parts[-2]), ';', tostring(parts[-1]))
  ) on vmKey
| project id, AzureBackup = iff(Protected > 0, 'Yes', 'No'), Databases = coalesce(Protected, 0), Failed = coalesce(Failed, 0),
    LastBackup, Image, Edition, License, ResourceGroup
| order by AzureBackup asc, Failed desc
"""

# ---------------------------------------------------------------------------
# Storage tab
# ---------------------------------------------------------------------------

STORAGE_Q = f"""
resources
| where type =~ 'microsoft.storage/storageaccounts'
| project id = tolower(id), Redundancy = tostring(sku.name), Kind = kind,
    Hns = tostring(properties.isHnsEnabled), Immutable = tostring(properties.immutableStorageWithVersioning.enabled),
    ResourceGroup = resourceGroup, Location = location
| join kind=leftouter (
    recoveryservicesresources
    | where type =~ '{RSV_ITEM}' and tostring(properties.workloadType) =~ 'AzureFileShare'
        or type =~ '{BV_INSTANCE}' and tostring(properties.dataSourceInfo.datasourceType) has 'blobServices'
    | extend isShare = type =~ '{RSV_ITEM}'
    | summarize Shares = countif(isShare),
        SharesFailed = countif(isShare and tostring(properties.lastBackupStatus) =~ 'Failed'),
        SharesLastBackup = max(iff(isShare, todatetime(properties.lastBackupTime), datetime(null))),
        BlobStatus = max(iff(isShare, '', tostring(properties.protectionStatus.status)))
        by id = tolower(iff(isShare, tostring(properties.sourceResourceId), tostring(properties.dataSourceInfo.resourceID)))
  ) on id
| project id, Redundancy, BlobBackup = iff(isempty(BlobStatus), 'None', BlobStatus), FileShareBackups = coalesce(Shares, 0),
    FileSharesFailed = coalesce(SharesFailed, 0), SharesLastBackup, Kind, Hns, Immutable, ResourceGroup, Location
| order by FileSharesFailed desc, case(BlobBackup == 'None' and FileShareBackups == 0, 1, 0) asc, Redundancy asc
"""

FILE_SHARES_Q = f"""
recoveryservicesresources
| where type =~ '{RSV_ITEM}'
| where tostring(properties.workloadType) =~ 'AzureFileShare'
| project Vault = tostring(split(id, '/')[8]),
    Share = tostring(properties.friendlyName),
    Account = tostring(split(tostring(properties.sourceResourceId), '/')[8]),
    LastBackup = tostring(properties.lastBackupStatus),
    LastBackupTime = todatetime(properties.lastBackupTime),
    Health = tostring(properties.healthStatus),
    Protection = tostring(properties.protectionState),
    Policy = tostring(properties.policyName)
| order by case(LastBackup =~ 'Failed', 0, 1) asc, LastBackupTime asc
"""

STORAGE_REDUNDANCY = status_fmt("Redundancy", good=["Standard_GRS", "Standard_RAGRS", "Standard_GZRS", "Standard_RAGZRS"],
                                warn=["Standard_ZRS", "Premium_ZRS"], neutral=["Standard_LRS", "Premium_LRS"])

# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------


def dropdown(name, label, values, default, description):
    return {"id": gid("bk-param-" + name), "version": "KqlParameterItem/1.0", "name": name, "label": label, "type": 2,
            "isRequired": True, "jsonData": json.dumps([{"value": v, "label": l} for v, l in values]),
            "value": default, "typeSettings": {"showDefault": False}, "description": description}


def global_params():
    return params("bk-params", [
        {
            "id": gid("bk-param-Subscription"),
            "version": "KqlParameterItem/1.0",
            "name": "Subscription",
            "label": "Subscriptions",
            "type": 6,
            "isRequired": True,
            "multiSelect": True,
            "quote": "'",
            "delimiter": ",",
            "query": "summarize by subscriptionId\n| project value = strcat('/subscriptions/', subscriptionId), label = subscriptionId",
            "crossComponentResources": ["value::all"],
            "typeSettings": {"additionalResourceOptions": ["value::all"], "showDefault": False},
            "defaultValue": "value::all",
            "value": ["value::all"],
            "queryType": 1,
            "resourceType": "microsoft.resourcegraph/resources",
        },
        {
            "id": gid("bk-param-TimeRange"),
            "version": "KqlParameterItem/1.0",
            "name": "TimeRange",
            "label": "Time range",
            "type": 4,
            "isRequired": True,
            "value": {"durationMs": 7 * DAY_MS},
            "typeSettings": {
                "selectableValues": [{"durationMs": d * DAY_MS} for d in (1, 3, 7, 14, 30)],
                "allowCustom": True,
            },
            "description": "Applies to jobs and log panels. Resource Graph keeps recent jobs only; the workspace "
                           "holds longer history.",
        },
        {
            "id": gid("bk-param-Workspace"),
            "version": "KqlParameterItem/1.0",
            "name": "Workspace",
            "label": "Log Analytics workspace",
            "type": 5,
            "isRequired": False,
            "multiSelect": True,
            "quote": "'",
            "delimiter": ",",
            "query": "resources\n| where type =~ 'microsoft.operationalinsights/workspaces'\n| project id",
            "crossComponentResources": ["{Subscription}"],
            "typeSettings": {"resourceTypeFilter": {"microsoft.operationalinsights/workspaces": True},
                             "additionalResourceOptions": [], "showDefault": False},
            "queryType": 1,
            "resourceType": "microsoft.resourcegraph/resources",
            "description": "Optional. The workspace the vaults' diagnostic settings send to. Enables job history "
                           "and Site Recovery RPO trends.",
        },
        dropdown("StaleHours", "Backup is stale after",
                 [("24", "24 hours"), ("26", "26 hours"), ("36", "36 hours"), ("48", "48 hours"), ("72", "72 hours"),
                  ("168", "7 days")], "26",
                 "A protected item whose last backup is older than this is flagged. 26 hours allows for a daily "
                 "backup that runs a little late."),
        dropdown("TestFailoverDays", "Test failover due after",
                 [("90", "90 days"), ("180", "180 days"), ("365", "365 days")], "180",
                 "A replicated item or recovery plan with no successful test failover in this long is flagged."),
        {"id": gid("bk-param-selectedTab"), "version": "KqlParameterItem/1.0", "name": "selectedTab", "type": 1,
         "value": "overview", "isHiddenWhenLocked": True},
    ])


def tabs():
    return {"type": 11, "content": {"version": "LinkItem/1.0", "style": "tabs", "links": [
        {"id": gid("bk-tab-" + key), "cellValue": "selectedTab", "linkTarget": "parameter",
         "linkLabel": label, "subTarget": key, "style": "link"} for key, label in TABS
    ]}, "name": "bk-tabs"}


def arm_query(name, title, path, api_version, columns, extra_params=(), **kw):
    """arm() with extra URL parameters beyond api-version."""
    item = arm(name, title, path, api_version, columns, **kw)
    request = json.loads(item["content"]["query"])
    request["urlParams"] += [{"key": k, "value": v} for k, v in extra_params]
    item["content"]["query"] = json.dumps(request)
    return item


def when_set(*names):
    """Visible only once every named parameter has a value."""
    conds = [{"parameterName": n, "comparison": "isNotEqualTo", "value": ""} for n in names]
    return conds[0] if len(conds) == 1 else conds


def _visible(item, *names):
    cond = when_set(*names)
    item["conditionalVisibility" if isinstance(cond, dict) else "conditionalVisibilities"] = cond
    return item


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

LAST_BACKUP = status_fmt("LastBackup", good=["Healthy", "Completed"], bad=["Failed", "IRPending"])
HEALTH = status_fmt("Health", good=["Passed", "Normal"], warn=["ActionSuggested", "Warning"], bad=["ActionRequired", "Critical"])
PROTECTION = status_fmt("Protection", good=["Protected"], warn=["ProtectionStopped", "ProtectionPaused", "IRPending"],
                        bad=["ProtectionError"])
JOB_STATUS = status_fmt("Status", good=["Completed"], warn=["CompletedWithWarnings", "Cancelled", "InProgress"], bad=["Failed"])
TEST_DUE = status_fmt("TestDue", good=["OK"], warn=["Overdue"], bad=["Never"])
REDUNDANCY = status_fmt("Redundancy", good=["Geo", "GeoZone"], warn=["Zone"], bad=["Local"])


def overview_tab():
    attention_q = ATTENTION + """
| where isnotempty(Problem)
| project Severity, Kind, Vault, Item, Problem, LastBackup, TestFailover
| order by case(Severity == 'Critical', 0, 1) asc, Kind asc
| take 500
"""
    return group("bk-tab-overview", [
        *[arg(f"bk-tile-{key}", "", q, vis="tiles", tiles=big_number_tiles("Signal", "State", "Value", "Detail"),
              fixed_px=ONE_TILE) for key, q in TILES],
        text("bk-tile-note", TILE_NOTE, "info"),
        arg("bk-jobs-day", "Backup jobs per day by status (time range)", JOBS_BY_DAY_Q, vis="barchart", width=50,
            no_data="No backup jobs in the time range."),
        arg("bk-workloads", "Protected items by workload", ITEMS_BY_WORKLOAD_Q, width=50,
            formatters=[{"columnMatch": "Problems", "formatter": 18, "formatOptions": {
                "thresholdsOptions": "icons", "thresholdsGrid": [
                    {"operator": ">", "thresholdValue": "0", "representation": "4", "text": "{0}{1}"},
                    {"operator": "Default", "thresholdValue": None, "representation": "success", "text": "{0}{1}"}]}}],
            no_data="Nothing is protected by Azure Backup."),
        arg("bk-attention", "Items needing attention (backup and replication)", attention_q,
            formatters=[status_fmt("Severity", warn=["Warning"], bad=["Critical"])],
            labels={"LastBackup": "Last backup", "TestFailover": "Last test failover"},
            no_data="Every protected and replicated item is healthy."),
    ], tab="overview")


def backup_tab():
    vm_q = VM_PROTECTION + "\n| order by case(Protection == 'Not protected', 0, 1) asc, ResourceGroup asc\n"
    return group("bk-tab-backup", [
        text("bk-vaults-h", "### Vaults"),
        arg("bk-rsv", "Recovery Services vaults", RSV_VAULTS_Q, formatters=VAULT_FORMATTERS, labels=VAULT_LABELS,
            no_data="No Recovery Services vaults."),
        arg("bk-bv", "Backup vaults (disks, blobs, AKS, PostgreSQL)", BACKUP_VAULTS_Q, formatters=VAULT_FORMATTERS,
            labels=VAULT_LABELS, no_data="No Backup vaults."),
        text("bk-vaults-note", "Soft delete keeps deleted backups recoverable; *AlwaysON* cannot be turned off. "
             "Immutability stops recovery points being deleted before they expire; *Locked* cannot be undone. "
             "Multi-user authorisation needs a Resource Guard approval for destructive operations. Locally "
             "redundant vaults cannot restore if the region is lost.", "info"),
        text("bk-items-h", "### Protected items"),
        arg("bk-items", "Recovery Services protected items", ITEMS_Q,
            formatters=[LAST_BACKUP, HEALTH, PROTECTION,
                        status_fmt("Age", good=["OK"], bad=["Stale"]),
                        resource_link("Source")],
            labels={"LastBackup": "Last backup", "LastBackupTime": "Last backup time", "AgeHours": "Hours since backup",
                    "Age": "Within {StaleHours} h", "Archive": "Archive tier"},
            no_data="No Recovery Services protected items."),
        arg("bk-instances", "Backup vault instances", INSTANCES_Q,
            formatters=[status_fmt("Status", good=["ProtectionConfigured"], warn=["ProtectionStopped"],
                                   bad=["ProtectionError", "ConfiguringProtectionFailed"]), resource_link("Source")],
            no_data="No Backup vault instances."),
        text("bk-jobs-h", "### Jobs"),
        arg("bk-jobs-failed", "Backup jobs that did not complete (time range)", JOBS_FAILED_Q, formatters=[JOB_STATUS],
            labels={"VaultKind": "Vault type"}, no_data="Every backup job in the time range completed."),
        text("bk-la-hint", "Select a **Log Analytics workspace** at the top for job history, failure codes and job "
             "duration (needs the vaults' diagnostic settings in *Resource specific* mode, `AddonAzureBackupJobs`).",
             "info", visible_when=WORKSPACE_UNSET),
        la("bk-la-trend", "Backup jobs by status", LA_JOBS_TREND_Q, vis="timechart", width=50),
        la("bk-la-duration", "Backup job duration, p95 (minutes)", LA_DURATION_Q, vis="timechart", width=50),
        la("bk-la-codes", "Failures by error code", LA_FAILURE_CODES_Q,
           labels={"FailureCode": "Error code", "LastSeen": "Last seen"},
           no_data="No failed backup jobs (or the vault diagnostic settings are not sending AddonAzureBackupJobs)."),
        text("bk-coverage-h", "### Coverage"),
        arg("bk-vm-protection", "Virtual machines by backup protection", vm_q, formatters=[
            resource_link(), status_fmt("Protection", good=["Protected"], bad=["Not protected"]),
        ], labels={"id": "Virtual machine", "LastBackup": "Last backup"}, no_data="No virtual machines."),
        text("bk-vm-note", "Machines rebuilt from an image (pooled AVD hosts, scale set agents) are normally not "
             "backed up. *Replication* shows whether Site Recovery also replicates the machine.", "info"),
    ], tab="backup")


def asr_tab():
    return group("bk-tab-asr", [
        arg("bk-asr-summary", "Replicated items by vault and scenario", ASR_SUMMARY_Q, width=40,
            formatters=[{"columnMatch": "Critical", "formatter": 18, "formatOptions": {
                "thresholdsOptions": "icons", "thresholdsGrid": [
                    {"operator": ">", "thresholdValue": "0", "representation": "4", "text": "{0}{1}"},
                    {"operator": "Default", "thresholdValue": None, "representation": "success", "text": "{0}{1}"}]}}],
            no_data="No replicated items."),
        arg("bk-asr-plans", "Recovery plans", ASR_PLANS_Q, width=60, formatters=[TEST_DUE],
            labels={"LastTest": "Last test failover", "TestDue": "Test", "LastPlannedFailover": "Last planned failover",
                    "LastUnplannedFailover": "Last unplanned failover"},
            no_data="No recovery plans."),
        arg("bk-asr-items", "Replicated items", ASR_ITEMS_Q,
            formatters=[HEALTH, TEST_DUE, status_fmt("FailoverHealth", good=["Normal"], warn=["Warning"], bad=["Critical"])],
            labels={"RpoMinutes": "RPO (minutes)", "ActiveLocation": "Active location", "TestFailover": "Last test failover",
                    "TestDue": "Test", "FailoverHealth": "Failover health"},
            no_data="No replicated items."),
        text("bk-asr-note", "*RPO* is reported for Azure-to-Azure replication. A *Test* of **Never** or **Overdue** "
             "means there is no recent proof the machine would come up in the recovery region; a recovery plan "
             "test covers every machine in it.", "info"),
        arg("bk-asr-jobs", "Site Recovery jobs that did not succeed (time range)", ASR_JOBS_Q,
            formatters=[status_fmt("State", warn=["Cancelled", "Suspended"], bad=["Failed"])],
            no_data="Every Site Recovery job in the time range succeeded (or Resource Graph does not hold them)."),
        text("bk-asr-la-hint", "Select a **Log Analytics workspace** at the top for RPO over time (needs the vault's "
             "diagnostic settings in *Resource specific* mode, `AzureSiteRecoveryReplicatedItems`).", "info",
             visible_when=WORKSPACE_UNSET),
        la("bk-asr-rpo", "RPO over time, worst 10 items (minutes)", LA_ASR_RPO_Q, vis="timechart",
           no_data="No RPO data (or the vault diagnostic settings are not sending AzureSiteRecoveryReplicatedItems)."),
        la("bk-asr-la-jobs", "Failed Site Recovery jobs (workspace)", LA_ASR_JOBS_Q,
           labels={"LastSeen": "Last seen"}, no_data="No failed Site Recovery jobs."),
    ], tab="asr")


def sql_tab():
    sql_sub = {
        "id": gid("bk-param-SqlSubscription"), "version": "KqlParameterItem/1.0", "name": "SqlSubscription",
        "label": "Subscription", "type": 6, "isRequired": False, "multiSelect": False,
        "query": "resources\n| where type =~ 'microsoft.sql/servers'\n| summarize by subscriptionId\n"
                 "| project value = strcat('/subscriptions/', subscriptionId), label = subscriptionId",
        "crossComponentResources": ["{Subscription}"], "typeSettings": {"showDefault": False},
        "queryType": 1, "resourceType": "microsoft.resourcegraph/resources",
    }
    sql_region = {
        "id": gid("bk-param-SqlRegion"), "version": "KqlParameterItem/1.0", "name": "SqlRegion",
        "label": "Region", "type": 2, "isRequired": False,
        "query": "resources\n| where type =~ 'microsoft.sql/servers'\n| summarize by location\n"
                 "| project value = location, label = location",
        "crossComponentResources": ["{SqlSubscription}"], "typeSettings": {"showDefault": False},
        "queryType": 1, "resourceType": "microsoft.resourcegraph/resources",
    }
    ltr_cols = [("Server", "$.properties.serverName", None), ("Database", "$.properties.databaseName", None),
                ("Latest LTR backup", "$.properties.backupTime", "datetime"),
                ("Expires", "$.properties.backupExpirationTime", "datetime"),
                ("Backup redundancy", "$.properties.backupStorageRedundancy", None),
                ("Database deleted", "$.properties.databaseDeletionTime", "datetime")]
    return group("bk-tab-sql", [
        text("bk-sql-h", "### Azure SQL Database"),
        arg("bk-sql-dbs", "Databases: backup redundancy and point-in-time restore window", SQL_DBS_Q,
            formatters=[resource_link(), REDUNDANCY,
                        {"columnMatch": "RestoreWindowDays", "formatter": 18, "formatOptions": {
                            "thresholdsOptions": "icons", "thresholdsGrid": [
                                {"operator": "<", "thresholdValue": "1", "representation": "2", "text": "{0}{1}"},
                                {"operator": "Default", "thresholdValue": None, "representation": "success", "text": "{0}{1}"}]}}],
            labels={"id": "Database", "Redundancy": "Backup redundancy", "RestoreWindowDays": "Restore window (days)",
                    "EarliestRestore": "Earliest restore point", "Secondary": "Secondary type", "ZoneRedundant": "Zone redundant"},
            no_data="No Azure SQL databases."),
        text("bk-sql-note", "The restore window is how far back a point-in-time restore can go today. It grows to "
             "the configured short-term retention (1 to 35 days) after a database is created. Geo-secondaries and "
             "serverless databases that are paused may show no window.", "info"),
        arg("bk-sql-fog", "Failover groups", SQL_FAILOVER_Q,
            formatters=[status_fmt("State", good=["CATCH_UP"], warn=["PENDING", "SEEDING"], bad=["SUSPENDED"]),
                        status_fmt("FailoverPolicy", good=["Automatic"], neutral=["Manual"])],
            labels={"PartnerLocation": "Partner region", "FailoverPolicy": "Failover policy"},
            no_data="No failover groups."),
        text("bk-sql-ltr-h", "### Long-term retention backups"),
        text("bk-sql-ltr-note", "Long-term retention (weekly, monthly, yearly backups kept up to 10 years) is not in "
             "Resource Graph, so this reads the latest LTR backup of each database from Azure Resource Manager, for "
             "one subscription and region at a time. A database missing from this list has no LTR backup.", "info"),
        params("bk-sql-ltr-params", [sql_sub, sql_region]),
        _visible(arm_query("bk-sql-ltr", "Latest long-term retention backup per database",
                           "{SqlSubscription}/providers/Microsoft.Sql/locations/{SqlRegion}/longTermRetentionBackups",
                           "2021-11-01", ltr_cols, extra_params=[("onlyLatestPerDatabase", "true")],
                           no_data="No long-term retention backups in this subscription and region."),
                 "SqlSubscription", "SqlRegion"),
        text("bk-mi-h", "### SQL Managed Instance"),
        arg("bk-sql-mi", "Managed instances: backup redundancy and restore window", SQL_MI_Q,
            formatters=[resource_link(), REDUNDANCY,
                        status_fmt("State", good=["Ready"], warn=["Updating", "Creating"], bad=["Failed"])],
            labels={"id": "Instance", "Redundancy": "Backup redundancy",
                    "ShortestWindowDays": "Shortest restore window (days)", "ZoneRedundant": "Zone redundant"},
            no_data="No managed instances."),
        text("bk-vm-h", "### SQL Server in virtual machines"),
        arg("bk-sql-vms", "SQL Server VMs and Azure Backup", SQL_VMS_Q,
            formatters=[resource_link(), status_fmt("AzureBackup", good=["Yes"], warn=["No"]),
                        {"columnMatch": "Failed", "formatter": 18, "formatOptions": {
                            "thresholdsOptions": "icons", "thresholdsGrid": [
                                {"operator": ">", "thresholdValue": "0", "representation": "4", "text": "{0}{1}"},
                                {"operator": "Default", "thresholdValue": None, "representation": "success", "text": "{0}{1}"}]}}],
            labels={"id": "SQL virtual machine", "AzureBackup": "Azure Backup", "Databases": "Databases protected",
                    "LastBackup": "Last backup"},
            no_data="No SQL Server VMs registered with the SQL IaaS extension."),
        text("bk-sql-vms-note", "*No* means no database on the VM is protected by Azure Backup. That is fine if it "
             "uses SQL Server's own backup to URL or another product, which this workbook cannot see.", "info"),
        arg("bk-workload-dbs", "Databases protected by Azure Backup (SQL Server, SAP HANA, SAP ASE)", WORKLOAD_DBS_Q,
            formatters=[LAST_BACKUP, HEALTH, PROTECTION],
            labels={"Vm": "VM", "LastBackup": "Last backup", "LastBackupTime": "Last backup time"},
            no_data="No database workloads protected by Azure Backup."),
    ], tab="sql")


def storage_tab():
    account = {
        "id": gid("bk-param-StorageAccount"), "version": "KqlParameterItem/1.0", "name": "StorageAccount",
        "label": "Storage account", "type": 5, "isRequired": False, "multiSelect": False,
        "query": "resources\n| where type =~ 'microsoft.storage/storageaccounts'\n| project id",
        "crossComponentResources": ["{Subscription}"], "typeSettings": {"showDefault": False},
        "queryType": 1, "resourceType": "microsoft.resourcegraph/resources",
    }
    blob_cols = [("Blob soft delete", "$.properties.deleteRetentionPolicy.enabled", None),
                 ("Blob soft delete days", "$.properties.deleteRetentionPolicy.days", None),
                 ("Container soft delete", "$.properties.containerDeleteRetentionPolicy.enabled", None),
                 ("Container soft delete days", "$.properties.containerDeleteRetentionPolicy.days", None),
                 ("Versioning", "$.properties.isVersioningEnabled", None),
                 ("Change feed", "$.properties.changeFeed.enabled", None),
                 ("Point-in-time restore", "$.properties.restorePolicy.enabled", None),
                 ("Restore days", "$.properties.restorePolicy.days", None)]
    file_cols = [("File share soft delete", "$.properties.shareDeleteRetentionPolicy.enabled", None),
                 ("File share soft delete days", "$.properties.shareDeleteRetentionPolicy.days", None)]
    return group("bk-tab-storage", [
        arg("bk-storage", "Storage accounts by backup protection", STORAGE_Q,
            formatters=[resource_link(), STORAGE_REDUNDANCY,
                        status_fmt("BlobBackup", good=["ProtectionConfigured"], neutral=["None"],
                                   bad=["ProtectionError", "ConfiguringProtectionFailed"]),
                        {"columnMatch": "FileSharesFailed", "formatter": 18, "formatOptions": {
                            "thresholdsOptions": "icons", "thresholdsGrid": [
                                {"operator": ">", "thresholdValue": "0", "representation": "4", "text": "{0}{1}"},
                                {"operator": "Default", "thresholdValue": None, "representation": "success", "text": "{0}{1}"}]}}],
            labels={"id": "Storage account", "BlobBackup": "Blob backup", "FileShareBackups": "File shares backed up",
                    "FileSharesFailed": "File share backups failing", "SharesLastBackup": "Last file share backup",
                    "Hns": "Data Lake (HNS)", "Immutable": "Immutable storage"},
            no_data="No storage accounts."),
        text("bk-storage-note", "*Blob backup* is Azure Backup for blobs (operational or vaulted) in a Backup vault. "
             "*File shares backed up* counts Azure Files shares in a Recovery Services vault. Many accounts hold "
             "nothing worth backing up, so an account with neither is not necessarily a problem; geo-redundant "
             "storage (GRS, GZRS) protects against losing the region, not against deletion or corruption.", "info"),
        arg("bk-file-shares", "Azure Files shares in Recovery Services vaults", FILE_SHARES_Q,
            formatters=[LAST_BACKUP, HEALTH, PROTECTION],
            labels={"LastBackup": "Last backup", "LastBackupTime": "Last backup time"},
            no_data="No Azure Files shares are backed up."),
        text("bk-softdelete-h", "### Data protection settings"),
        text("bk-softdelete-note", "Soft delete, versioning and point-in-time restore are not in Resource Graph, so "
             "pick an account to read them from Azure Resource Manager.", "info"),
        params("bk-storage-params", [account]),
        _visible(arm("bk-blob-settings", "Blob data protection", "{StorageAccount}/blobServices", "2023-01-01",
                     blob_cols, width=60, no_data="No blob service settings returned."), "StorageAccount"),
        _visible(arm("bk-file-settings", "File share data protection", "{StorageAccount}/fileServices", "2023-01-01",
                     file_cols, width=40, no_data="No file service settings returned."), "StorageAccount"),
    ], tab="storage")


def workbook():
    return {
        "version": "Notebook/1.0",
        "items": [
            text("bk-header", "# Backup & Recovery\n"
                 "Is everything that should be backed up or replicated protected, is it working, and could it be "
                 "restored? Azure Backup (Recovery Services and Backup vaults), Site Recovery, Azure SQL and SQL "
                 "Server in VMs, and storage accounts."),
            global_params(),
            tabs(),
            overview_tab(),
            backup_tab(),
            asr_tab(),
            sql_tab(),
            storage_tab(),
        ],
        "fallbackResourceIds": ["Azure Monitor"],
        "$schema": "https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json",
    }


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" keeps the output byte-identical on Windows and Linux; CI regenerates it and compares.
    OUT.write_text(json.dumps(workbook(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
