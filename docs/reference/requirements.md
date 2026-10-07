---
myst:
  html_meta:
    description: Charmed Apache Kafka system requirements - Juju version, recommended hardware, storage, memory, CPU, and supported architectures.
---

(reference-requirements)=

# Requirements

## Juju version

The charm currently runs on and is tested against
[Juju 3.6 LTS](https://github.com/juju/juju/releases).

The minimum supported Juju version is [Juju 3.6+](https://github.com/juju/juju/releases).

## Recommended hardware

The below requirements are a good baseline upon which to size your Charmed Apache Kafka
applications, but will not be appropriate for every use-case, based on device, data, network and
cost constraints.

Note that while these requirements are recommended for a broad-range of production use-cases, each
component can run with much lower requirements for use in staging or test environments.

|    Component     | Nodes | External Storage  |  Memory   |                               CPU                                |
| :--------------: | :---: | :---------------: | :-------: | :--------------------------------------------------------------: |
|     Brokers      |  3+   | 12 x 1TB disk/SSD | 64 GB RAM |                             12 cores                             |
| KRaft controller |  3-5  |   1 x 64GB SSD    | 6 GB RAM  |                             4 cores                              |
|     Connect      |   3   |         -         | 6 GB RAM  | Typically not CPU-bound. More cores is better than faster cores. |
|     Karapace     |   2   |         -         | 6 GB RAM  | Typically not CPU-bound. More cores is better than faster cores. |

```{note}
For production VM deployments, ensure that all nodes are deployed on separate
physical machines and that each component node is in a different availability
zone (AZ). For K8s, schedule units on separate Kubernetes worker nodes and spread
each component's units across availability zones.
```

## Supported architectures

`````{tab-set}
---
sync-group: substrate
---
````{tab-item} VM
:sync: vm

The `charmed-kafka` [snap](https://snapcraft.io/charmed-kafka) is fully tested
and supported on `amd64`. Builds for `arm64` are published but not yet validated
for production use.

````

````{tab-item} K8s
:sync: k8s

The `charmed-kafka` OCI image (rock) used by the K8s charm is fully tested and
supported on `amd64`. Builds for `arm64` are available but not yet validated
for production use.

````

`````

Please [get in touch](contributing-contact) if you are interested in a new architecture to be
supported!
