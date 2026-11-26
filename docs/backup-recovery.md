# Backup & Recovery

*Reference for [backup-recovery.workbook.json](../workbook/backup-recovery.workbook.json). Generated from the workbook by `src/build_docs.py`: do not edit by hand.*

Is everything that should be backed up or replicated protected, is it working, and could it be restored? Azure Backup (Recovery Services and Backup vaults), Site Recovery, Azure SQL and SQL Server in VMs, and storage accounts.

It has 34 panels across 5 tabs. Each is listed below with what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels need the named tables in the selected workspace; see *Logs to collect* in the [main README](../README.md#logs-to-collect).

## Parameters

| Parameter | What it does |
|---|---|
| Subscriptions | The subscriptions to read. Defaults to all you can see. |
| Time range | Applies to jobs and log panels. Resource Graph keeps recent jobs only; the workspace holds longer history. |
| Log Analytics workspace | Optional. The workspace the vaults' diagnostic settings send to. Enables job history and Site Recovery RPO trends. |
| Backup is stale after | A protected item whose last backup is older than this is flagged. 26 hours allows for a daily backup that runs a little late. |
| Test failover due after | A replicated item or recovery plan with no successful test failover in this long is flagged. |
| Subscription | The subscriptions to read. Defaults to all you can see. |
| Region |  |
| Storage account | Which storage account to include. |

## Tab: Overview

#### Tile jobs

*Tiles · Azure Resource Graph* · reads `recoveryservicesresources`

#### Tile attention

*Tiles · Azure Resource Graph* · reads `recoveryservicesresources`

#### Tile vms

*Tiles · Azure Resource Graph* · reads `recoveryservicesresources`

#### Tile asr

*Tiles · Azure Resource Graph* · reads `recoveryservicesresources`

#### Tile vaults

*Tiles · Azure Resource Graph*

#### Tile sql

*Tiles · Azure Resource Graph*

> Thresholds: a backup is *stale* when the last one is older than **{StaleHours} hours**, and a replicated item is
> due a test failover after **{TestFailoverDays} days**. Change them at the top. *Local-only* SQL backups (LRS)
> cannot be restored if the region is lost.

#### Backup jobs per day by status (time range)

*Bar chart · Azure Resource Graph* · reads `recoveryservicesresources`

When there is nothing to show: *No backup jobs in the time range.*

#### Protected items by workload

*Table · Azure Resource Graph* · reads `recoveryservicesresources`

When there is nothing to show: *Nothing is protected by Azure Backup.*

#### Items needing attention (backup and replication)

*Table · Azure Resource Graph* · reads `recoveryservicesresources`

Columns: Severity, Kind, Vault, Item, Problem, Last backup, Last test failover.

When there is nothing to show: *Every protected and replicated item is healthy.*

## Tab: Azure Backup

### Vaults

#### Recovery Services vaults

*Table · Azure Resource Graph*

Columns: Vault, Redundancy, Cross-region restore, Soft delete, Soft delete days, Immutability, Multi-user authorisation, Job failure alerts, Public network, Provisioning, Resource Group, Location.

When there is nothing to show: *No Recovery Services vaults.*

#### Backup vaults (disks, blobs, AKS, PostgreSQL)

*Table · Azure Resource Graph*

Columns: Vault, Redundancy, Cross-region restore, Soft delete, Soft delete days, Immutability, Job failure alerts, Provisioning, Resource Group, Location.

When there is nothing to show: *No Backup vaults.*

> Soft delete keeps deleted backups recoverable; *AlwaysON* cannot be turned off. Immutability stops recovery points being deleted before they expire; *Locked* cannot be undone. Multi-user authorisation needs a Resource Guard approval for destructive operations. Locally redundant vaults cannot restore if the region is lost.

### Protected items

#### Recovery Services protected items

*Table · Azure Resource Graph* · reads `recoveryservicesresources`

Columns: Vault, Item, Workload, Health, Last backup, Last backup time, Protection, Policy, Archive tier, Source.

When there is nothing to show: *No Recovery Services protected items.*

#### Backup vault instances

*Table · Azure Resource Graph* · reads `recoveryservicesresources`

Columns: Vault, Instance, Datasource, Status, State, Error, Policy, Source.

When there is nothing to show: *No Backup vault instances.*

### Jobs

#### Backup jobs that did not complete (time range)

*Table · Azure Resource Graph* · reads `recoveryservicesresources`

Columns: Started, Vault type, Vault, Item, Workload, Operation, Status, Error, Duration.

When there is nothing to show: *Every backup job in the time range completed.*

> Select a **Log Analytics workspace** at the top for job history, failure codes and job duration (needs the vaults' diagnostic settings in *Resource specific* mode, `AddonAzureBackupJobs`).

#### Backup jobs by status

*Time chart · Log Analytics* · reads `AddonAzureBackupJobs`

#### Backup job duration, p95 (minutes)

*Time chart · Log Analytics* · reads `AddonAzureBackupJobs`

#### Failures by error code

*Table · Log Analytics* · reads `AddonAzureBackupJobs`

When there is nothing to show: *No failed backup jobs (or the vault diagnostic settings are not sending AddonAzureBackupJobs).*

### Coverage

#### Virtual machines by backup protection

*Table · Azure Resource Graph* · reads `recoveryservicesresources`

Columns: Virtual machine, Protection, Vault, Last backup, Replication, OS, Power, Resource Group, Location.

When there is nothing to show: *No virtual machines.*

> Machines rebuilt from an image (pooled AVD hosts, scale set agents) are normally not backed up. *Replication* shows whether Site Recovery also replicates the machine.

## Tab: Site Recovery

#### Replicated items by vault and scenario

*Table · Azure Resource Graph* · reads `recoveryservicesresources`

When there is nothing to show: *No replicated items.*

#### Recovery plans

*Table · Azure Resource Graph* · reads `recoveryservicesresources`

Columns: Vault, Plan, Scenario, Groups, Last test failover, Test, Last planned failover, Last unplanned failover.

When there is nothing to show: *No recovery plans.*

#### Replicated items

*Table · Azure Resource Graph* · reads `recoveryservicesresources`

Columns: Vault, Item, Health, State, Scenario, RPO (minutes), Active location, Primary, Recovery, Last test failover, Test, Failover health, Error, Policy.

When there is nothing to show: *No replicated items.*

> *RPO* is reported for Azure-to-Azure replication. A *Test* of **Never** or **Overdue** means there is no recent proof the machine would come up in the recovery region; a recovery plan test covers every machine in it.

#### Site Recovery jobs that did not succeed (time range)

*Table · Azure Resource Graph* · reads `recoveryservicesresources`

Columns: Started, Vault, Job, Target, State, Scenario, Error.

When there is nothing to show: *Every Site Recovery job in the time range succeeded (or Resource Graph does not hold them).*

> Select a **Log Analytics workspace** at the top for RPO over time (needs the vault's diagnostic settings in *Resource specific* mode, `AzureSiteRecoveryReplicatedItems`).

#### RPO over time, worst 10 items (minutes)

*Time chart · Log Analytics* · reads `AzureSiteRecoveryReplicatedItems`

When there is nothing to show: *No RPO data (or the vault diagnostic settings are not sending AzureSiteRecoveryReplicatedItems).*

#### Failed Site Recovery jobs (workspace)

*Table · Log Analytics* · reads `AzureSiteRecoveryJobs`

When there is nothing to show: *No failed Site Recovery jobs.*

## Tab: SQL

### Azure SQL Database

#### Databases: backup redundancy and point-in-time restore window

*Table · Azure Resource Graph*

Columns: Database, Server, Backup redundancy, Restore window (days), Earliest restore point, Secondary type, Zone redundant, Sku, Status, Resource Group, Location.

When there is nothing to show: *No Azure SQL databases.*

> The restore window is how far back a point-in-time restore can go today. It grows to the configured short-term retention (1 to 35 days) after a database is created. Geo-secondaries and serverless databases that are paused may show no window.

#### Failover groups

*Table · Azure Resource Graph*

Columns: Group, Server, Role, State, Partner, Partner region, Failover policy, Databases, Resource Group.

When there is nothing to show: *No failover groups.*

### Long-term retention backups

> Long-term retention (weekly, monthly, yearly backups kept up to 10 years) is not in Resource Graph, so this reads the latest LTR backup of each database from Azure Resource Manager, for one subscription and region at a time. A database missing from this list has no LTR backup.

#### Latest long-term retention backup per database

*Table · Azure Resource Manager*: `GET {SqlSubscription}/providers/Microsoft.Sql/locations/{SqlRegion}/longTermRetentionBackups`

Columns: Server, Database, Latest LTR backup, Expires, Backup redundancy, Database deleted.

When there is nothing to show: *No long-term retention backups in this subscription and region.*

### SQL Managed Instance

#### Managed instances: backup redundancy and restore window

*Table · Azure Resource Graph*

Columns: Instance, Backup redundancy, Databases, Shortest restore window (days), Zone redundant, State.

When there is nothing to show: *No managed instances.*

### SQL Server in virtual machines

#### SQL Server VMs and Azure Backup

*Table · Azure Resource Graph* · reads `recoveryservicesresources`

Columns: SQL virtual machine, Azure Backup, Databases protected, Failed, Last backup, Image, Edition, License, Resource Group.

When there is nothing to show: *No SQL Server VMs registered with the SQL IaaS extension.*

> *No* means no database on the VM is protected by Azure Backup. That is fine if it uses SQL Server's own backup to URL or another product, which this workbook cannot see.

#### Databases protected by Azure Backup (SQL Server, SAP HANA, SAP ASE)

*Table · Azure Resource Graph* · reads `recoveryservicesresources`

Columns: Vault, Database, Workload, Server, VM, Last backup, Last backup time, Health, Protection, Policy.

When there is nothing to show: *No database workloads protected by Azure Backup.*

## Tab: Storage

#### Storage accounts by backup protection

*Table · Azure Resource Graph* · reads `recoveryservicesresources`

Columns: Storage account, Redundancy, Blob backup, File shares backed up, File share backups failing, Last file share backup, Kind, Data Lake (HNS), Immutable storage, Resource Group, Location.

When there is nothing to show: *No storage accounts.*

> *Blob backup* is Azure Backup for blobs (operational or vaulted) in a Backup vault. *File shares backed up* counts Azure Files shares in a Recovery Services vault. Many accounts hold nothing worth backing up, so an account with neither is not necessarily a problem; geo-redundant storage (GRS, GZRS) protects against losing the region, not against deletion or corruption.

#### Azure Files shares in Recovery Services vaults

*Table · Azure Resource Graph* · reads `recoveryservicesresources`

Columns: Vault, Share, Account, Last backup, Last backup time, Health, Protection, Policy.

When there is nothing to show: *No Azure Files shares are backed up.*

### Data protection settings

> Soft delete, versioning and point-in-time restore are not in Resource Graph, so pick an account to read them from Azure Resource Manager.

#### Blob data protection

*Table · Azure Resource Manager*: `GET {StorageAccount}/blobServices`

Columns: Blob soft delete, Blob soft delete days, Container soft delete, Container soft delete days, Versioning, Change feed, Point-in-time restore, Restore days.

When there is nothing to show: *No blob service settings returned.*

#### File share data protection

*Table · Azure Resource Manager*: `GET {StorageAccount}/fileServices`

Columns: File share soft delete, File share soft delete days.

When there is nothing to show: *No file service settings returned.*
