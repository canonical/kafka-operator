(reference-requirements)=
# Requirements

## Juju version

The charm currently runs on and is tested against [Juju 3.6 LTS](https://github.com/juju/juju/releases).

The minimum supported Juju version is [Juju 3.5+](https://github.com/juju/juju/releases). 

## Recommended hardware

The below requirements are a good baseline upon which to size your Charmed Apache Kafka applications, but will not be appropriate for every use-case, based on device, data, network and cost constraints.

Note that while these requirements are recommended for a broad-range of production use-cases, each component can run with much lower requirements for use in staging or test environments.

|     Component    | Nodes |  External Storage |   Memory  |                                CPU                               |
|:----------------:|:-----:|:-----------------:|:---------:|:----------------------------------------------------------------:|
|      Brokers     |   3+  | 12 x 1TB disk/SSD | 64 GB RAM |                             12 cores                             |
| KRaft controller |  3-5  |    1 x 64GB SSD   |  6 GB RAM |                              4 cores                             |
|      Connect     |   3   |         -         |  6 GB RAM | Typically not CPU-bound. More cores is better than faster cores. |
|     Karapace     |   2   |         -         |  6 GB RAM | Typically not CPU-bound. More cores is better than faster cores. |

```{note}
For production deployments, ensure that all nodes are deployed on separate physical machines and that each component node is in a different availability-zone (AZ) for redundancy.
```

## Supported architectures

The charm uses the `charmed-kafka` [snap](https://snapcraft.io/charmed-kafka), which is currently available for `amd64` only. The `arm64` architecture support is planned.

Please [contact us](contact) if you are interested in a new architecture to be supported!

