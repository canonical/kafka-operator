# Configuration backup and restore

Charmed Apache Kafka's configuration is distributed using [Charmed Apache ZooKeeper](https://charmhub.io/zookeeper?channel=3/stable).
A Charmed Apache ZooKeeper backup can be stored on any S3-compatible storage.
S3 access and configurations are managed with the [`s3-integrator` charm](https://charmhub.io/s3-integrator).

This guide contains step-by-step instructions on how to deploy and configure the `s3-integrator` charm for [AWS S3](https://aws.amazon.com/s3/), send the configurations to the Charmed Apache ZooKeeper application, and finally manage your Charmed Apache ZooKeeper backups.

## Configure `s3-integrator`

First, deploy the `s3-integrator` charm:

```shell
juju deploy s3-integrator
juju run s3-integrator/leader sync-s3-credentials access-key=<aws-access-key-id> secret-key=<aws-secret-key>
```

Then, use `juju config` to add your configuration parameters. For example:

```shell
juju config s3-integrator \
    endpoint="https://s3.us-west-2.amazonaws.com" \
    bucket="zk-backups-bucket-1" \
    path="/zk-backups" \
    region="us-west-2"
```

[note]
The only mandatory configuration parameter in the command above is the `bucket`.
[/note]

### Integrate with Charmed Apache ZooKeeper

To pass these configurations to Charmed Apache ZooKeeper, integrate the two applications:

```shell
juju integrate s3-integrator zookeeper
```

You can create, list, and restore backups now:

```shell
juju run zookeeper/leader create-backup
juju run zookeeper/leader list-backups
juju run zookeeper/leader restore backup-id=<backup-id-here>
```

## Create a backup

Check that Charmed Apache ZooKeeper deployment with configurations set for S3 storage is `active` and `idle` with the `juju status` command. Once it's active, create a backup with the `create-backup` command:

```shell
juju run zookeeper/leader create-backup
```

Charmed Apache ZooKeeper backups created with the command above will always be **full** backups: a copy of *all* the Charmed Apache Kafka configuration will be stored in S3.

The command will output the ID of the newly created backup:

```
                                     Backup created
┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Id                   ┃ Log-sequence-number ┃ Path                           ┃
┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 2024-09-12T14:32:46Z │          8589934621 │ zookeeper_backups/2024-09-12T1 │
│                      │                     │ 4:32:46Z/snapshot              │
└──────────────────────┴─────────────────────┴────────────────────────────────┘
```

## List backups

To list available backups, run the `list-backups` command:

```shell
juju run zookeeper/leader list-backups
```

This command shows available backups, for example:

```
                                     Backups
┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Id                   ┃ Log-sequence-number ┃ Path                           ┃
┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 2024-09-12T14:32:46Z │          8589934621 │ zookeeper_backups/2024-09-12T1 │
│                      │                     │ 4:32:46Z/snapshot              │
│ 2024-09-12T14:32:00Z │          8589934621 │ zookeeper_backups/2024-09-12T1 │
│                      │                     │ 4:32:00Z/snapshot              │
│ 2024-09-12T14:26:12Z │          8589934621 │ zookeeper_backups/2024-09-12T1 │
│                      │                     │ 4:26:12Z/snapshot              │
└──────────────────────┴─────────────────────┴────────────────────────────────┘
```

Below is a list of parameters shown for each backup:

- `Id`: identifier of the backup.
- `Log-Sequence-number`: a database-specific number to identify its state. Learn more about the Zxid on [Apache ZooKeeper documentation](https://zookeeper.apache.org/doc/r3.9.2/zookeeperProgrammers.html#sc_timeInZk).
- `Path`: path of the snapshot file in the S3 repository.

## Restore a backup

[note]
This operation puts you at risk of losing unsaved configuration data.
We recommend creating a backup first.
[/note]

To restore from backup, run the `restore` command and pass the `backup-id` (in the `YYYY-MM-DDTHH:MM:SSZ` format) that is listed in the `list-backups` action output:

```shell
juju run zookeeper/leader restore backup-id=<backup-id-here>
```

The restore will then proceed. Follow its progress using `juju status`.