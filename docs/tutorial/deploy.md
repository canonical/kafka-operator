(tutorial-deploy)=
# 3. Deploy Apache Kafka

This is a part of the [Charmed Apache Kafka Tutorial](index.md).

## Deploy Charmed Apache Kafka

To deploy Charmed Apache Kafka, all you need to do is run the following commands, which will automatically fetch [Apache Kafka](https://charmhub.io/kafka?channel=4/edge) from [Charmhub](https://charmhub.io/) and deploy it to your model.

Charmed Apache Kafka can run both with `roles=broker` and/or `roles=controller`. With this configuration option, the charm can be deployed either as a single application running both Apache Kafka brokers and KRaft controllers, or as multiple applications with a separate controller cluster and broker cluster.

For this tutorial, we will deploy brokers separately.
To deploy a cluster of three Apache Kafka brokers:

```shell
juju deploy kafka -n 3 --channel 4/edge --config roles=broker
```

Now check the Juju model status:

```shell
juju status
```

````{warning}
If you encounter the following error message: 

```text
cannot get available image metadata: failed getting published images metadata from default ubuntu cloud images: cannot read index data, attempt count exceeded: cannot access URL "http://cloud-images.ubuntu.com/releases/streams/v1/index.sjson"`
```

Force Juju to use HTTPS (and stop using the default HTTP sources):

```shell
juju model-config \
  container-image-metadata-defaults-disabled=true \
  container-image-metadata-url=https://cloud-images.ubuntu.com/releases/ \
  image-metadata-defaults-disabled=true \
  image-metadata-url=https://cloud-images.ubuntu.com/releases/

juju retry-provisioning --all
```

````

Apache Kafka also uses the KRaft consensus protocol for coordinating broker information, topic + partition metadata and Access Control Lists (ACLs), ran as a quorum of controller nodes using the Raft consensus algorithm. KRaft replaces the dependency on Apache ZooKeeper for metadata management. For more information on the differences between the two solutions, please refer to the [upstream Apache Kafka documentation](https://kafka.apache.org/40/documentation/zk2kraft.html)

To deploy a cluster of three KRaft controllers, run:

```shell
juju deploy kafka -n 3 --channel 4/edge --config roles=controller kraft
```

After this, it is necessary to connect the two clusters, taking care to specify which cluster is the orchestrator:

```shell
juju integrate kafka:peer-cluster-orchestrator kraft:peer-cluster
```

Juju will now fetch Charmed Apache Kafka and begin deploying both applications to the LXD cloud before connecting them to exchange access credentials and machine endpoints. This process can take several minutes depending on the resources available on your machine. You can track the progress by running:

```shell
watch -n 1 --color juju status --color
```

This command is useful for checking the status of both Charmed Apache Kafka applications, and for gathering information about the machines hosting the two applications. Some of the helpful information it displays includes IP addresses, ports, status etc. 
The command updates the status of the cluster every second and as the application starts you can watch the status and messages both applications change. 

Wait until the application is ready - when it is ready, `watch -n 1 --color juju status --color` will show:

```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  3.6.12   unsupported  00:49:46Z

App    Version  Status  Scale  Charm  Channel  Rev  Exposed  Message
kafka  4.0.0    active      3  kafka  4/edge   244  no       
kraft  4.0.0    active      3  kafka  4/edge   244  no       

Unit      Workload  Agent  Machine  Public address  Ports      Message
kafka/0*  active    idle   0        10.160.139.193  19093/tcp  
kafka/1   active    idle   1        10.160.139.127  19093/tcp  
kafka/2   active    idle   2        10.160.139.2    19093/tcp  
kraft/0*  active    idle   3        10.160.139.44   9098/tcp   
kraft/1   active    idle   4        10.160.139.126  9098/tcp   
kraft/2   active    idle   5        10.160.139.170  9098/tcp   

Machine  State    Address         Inst id        Base          AZ                    Message
0        started  10.160.139.193  juju-73091a-0  ubuntu@24.04  Lenovo-Fortress-Lin2  Running
1        started  10.160.139.127  juju-73091a-1  ubuntu@24.04  Lenovo-Fortress-Lin2  Running
2        started  10.160.139.2    juju-73091a-2  ubuntu@24.04  Lenovo-Fortress-Lin2  Running
3        started  10.160.139.44   juju-73091a-3  ubuntu@24.04  Lenovo-Fortress-Lin2  Running
4        started  10.160.139.126  juju-73091a-4  ubuntu@24.04  Lenovo-Fortress-Lin2  Running
5        started  10.160.139.170  juju-73091a-5  ubuntu@24.04  Lenovo-Fortress-Lin2  Running
```

To exit the screen, push `Ctrl+C`.

## Access Apache Kafka brokers

Once all the units are shown as `active|idle`, the credentials can be retrieved.

All sensitive configuration data used by Charmed Apache Kafka, such as passwords and SSL certificates, is stored in Juju secrets. See the [Juju secrets documentation](https://documentation.ubuntu.com/juju/3.6/reference/secret/) for more information.

To reveal the contents of the Juju secret containing sensitive cluster data for the Charmed Apache Kafka application, you can run:

```shell
juju show-secret --reveal cluster.kafka.app
```

The output of the previous command will look something like this:

```shell
d5ipahpdormt02antvpg:
  revision: 1
  checksum: f84bf383e76ddda391543d57a8b76dbef4e95813b820a466fb4815b098bda3b2
  owner: kafka
  label: cluster.kafka.app
  created: 2026-01-13T00:43:58Z
  updated: 2026-01-13T00:43:58Z
  content:
    internal-ca: |-
      -----BEGIN CERTIFICATE-----
        ...
      -----END CERTIFICATE-----
    internal-ca-key: |-
      -----BEGIN RSA PRIVATE KEY-----
        ...
      -----END RSA PRIVATE KEY-----
    operator-password: 0g7010iwtBrChk00Ad1pznzaZW0i2Pdt
    replication-password: tatsvzFV3de4Ce2NEL2HVQWAlSpx7gyv
```

The important line here for accessing the Apache Kafka cluster itself is `operator-password`, which tells us that `username=admin` and `password=0g7010iwtBrChk00Ad1pznzaZW0i2Pdt`. These are the credentials to use to successfully authenticate to the cluster.

For simplicity, the password can also be directly retrieved by parsing the YAML response from the previous command directly using `yq`:

```shell
juju show-secret --reveal cluster.kafka.app | yq -r '.[].content["operator-password"]'
```

```{caution}
When no other application is integrated to Charmed Apache Kafka, the cluster is secured-by-default and external listeners (bound to port `9092`) are disabled, thus preventing any external incoming connection. 
```

We will also need a bootstrap server Apache Kafka broker address and port to initially connect to. When any application connects for the first time to a `bootstrap-server`, the client will automatically make a metadata request that returns the full set of Apache Kafka brokers with their addresses and ports.

To use `kafka/0` as the `bootstrap-server`, retrieve its IP address and add a port with:

```shell
bootstrap_address=$(juju show-unit kafka/0 | yq '.. | ."public-address"? // ""' | tr -d '"' | tr -d '\r\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

export BOOTSTRAP_SERVER="${bootstrap_address}:19093"
```

where `19093` refers to the available open internal port on the broker unit.

It is always possible to run a command from within the Apache Kafka cluster using the internal listeners and ports in place of the external ones. For an explanation of Charmed Apache Kafka listeners, please refer to [Apache Kafka listeners](reference-broker-listeners).

To jump in to a running Charmed Apache Kafka unit and run a command, for example listing files in a directory, you can do the following:

```shell
juju ssh kafka/leader sudo -i "ls \$BIN/bin"
```

where the printed result will be the output from the `ls \$BIN/bin` command being executed on the `kafka` leader unit.

```{note}
Charmed Apache Kafka exports (among others) four different environment variables for conveniently referencing various file-system directories relevant to the workload, `$BIN`, `$LOGS`, `$CONF` and `$DATA` - more information on these directories can be found in [File system paths](reference-file-system-paths).
```

When the unit has started, the Charmed Apache Kafka Operator installs the [`charmed-kafka`](https://snapcraft.io/charmed-kafka) snap in the unit that provides a number of snap commands (that corresponds to the shell-script `bin/kafka-*.sh` commands in the Apache Kafka distribution) for performing various administrative and operational tasks.

Within the machine, Charmed Apache Kafka also creates a `$CONF/client.properties` file that already provides the relevant settings to connect to the cluster using the CLI.

For example, in order to create a topic, you can run:

```shell
juju ssh kafka/0 sudo -i \
    "charmed-kafka.topics \
        --create \
        --topic test-topic \
        --bootstrap-server $BOOTSTRAP_SERVER \
        --command-config \$CONF/client.properties"
```

You can similarly then list the topic, using:

```shell
juju ssh kafka/0 sudo -i \
    "charmed-kafka.topics \
        --list \
        --bootstrap-server $BOOTSTRAP_SERVER \
        --command-config \$CONF/client.properties"
```

making sure the topic was successfully created.

You can finally delete the topic, using:

```shell
juju ssh kafka/0 sudo -i \
    "charmed-kafka.topics \
        --delete \
        --topic test-topic \
        --bootstrap-server $BOOTSTRAP_SERVER \
        --command-config \$CONF/client.properties"
```

For a full list of the available Charmed Kafka command-line tools, please refer to [snap commands](reference-snap-commands).

## What's next?

Although the commands above can run within the cluster, it is generally recommended during operations to enable external listeners and use these for running the admin commands from outside the cluster. 
To do so, as we will see in the next section, we will deploy a [data-integrator](https://charmhub.io/data-integrator) charm and relate it to Charmed Apache Kafka.

