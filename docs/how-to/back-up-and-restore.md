(how-to-back-up-and-restore)=
# Backup and restore

Apache Kafka configuration is distributed using Apache ZooKeeper.
An Apache ZooKeeper backup can be stored on any S3-compatible storage.
S3 access and configurations are managed with the [`s3-integrator` charm](https://charmhub.io/s3-integrator), that can be integrated with Charmed Apache ZooKeeper.

This guide will teach you how to deploy and configure the `s3-integrator` charm for [AWS S3](https://aws.amazon.com/s3/), send the configurations to Charmed Apache ZooKeeper K8s, and finally manage your Apache ZooKeeper backups.

## Configure `s3-integrator`

First, deploy and run the charm:

```shell
juju deploy s3-integrator
juju run s3-integrator/leader sync-s3-credentials access-key=<access-key-here> secret-key=<secret-key-here>
```

Then, use `juju config` to add your configuration parameters. For example:

```shell
juju config s3-integrator \
    endpoint="https://s3.us-west-2.amazonaws.com" \
    bucket="zk-backups-bucket-1" \
    path="/zk-backups" \
    region="us-west-2"
```

```{note}
The only mandatory configuration parameter in the command above is the `bucket`.
```

### Integrate with Charmed Apache ZooKeeper K8s

To pass these configurations to Charmed Apache ZooKeeper K8s, integrate the two applications:

```shell
juju integrate s3-integrator zookeeper-k8s
```

You can create, list, and restore backups now:

```shell
juju run zookeeper-k8s/leader list-backups
juju run zookeeper-k8s/leader create-backup
juju run zookeeper-k8s/leader list-backups
juju run zookeeper-k8s/leader restore backup-id=<backup-id-here>
```

## Create a backup

Once you have a Charmed Apache ZooKeeper K8s deployment with configurations set for S3 storage, check that it is `active` and `idle` with `juju status`.\
Once Charmed Apache ZooKeeper K8s is `active` and `idle`, you can create your first backup with the `create-backup` command.

```shell
juju run zookeeper-k8s/leader create-backup
```

Apache ZooKeeper K8s backups created with the command above will always be **full** backups: a copy of *all* the Apache Kafka K8s configuration will be stored in S3.

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

You can list your available backups by running the `list-backups` command:

```shell
juju run zookeeper-k8s/leader list-backups
```

This should show your available backups, like in the sample output below:

```text
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
- `Log-Sequence-number`: a database-specific number to identify its state. Learn more about the zxid on [Apache ZooKeeper documentation](https://zookeeper.apache.org/doc/r3.9.2/zookeeperProgrammers.html#sc_timeInZk).
- `Path`: path of the snapshot file in the S3 repository.

## Restore a backup

```{note}
This operation puts you at risk of losing unsaved configuration data.
We recommend creating a backup first.
```

To restore from backup, run the `restore` command and pass the `backup-id` (in the `YYYY-MM-DDTHH:MM:SSZ` format) that is listed in the `list-backups` action output:

```shell
juju run zookeeper-k8s/leader restore backup-id=<backup-id-here>
```

The restore will then proceed. Follow its progress using `juju status`.
