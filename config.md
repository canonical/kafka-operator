## Goals
- default.goals:
    - RackAware
    - RackAwareDistribution
    - ReplicaCapacity
    - DiskCapacity
    - NetworkInboundCapacity
    - NetworkOutboundCapacity
    - CpuCapacity
    - ReplicaDistribution
    - PotentialNwOut
    - DiskUsageDistribution
    - NetworkInboundUsageDistribution
    - NetworkOutboundUsageDistribution
    - CpuUsageDistribution
    - LeaderReplicaDistribution
    - LeaderBytesInDistribution
    - TopicReplicaDistribution
    - PreferredLeaderElection
    - IntraBrokerDiskCapacity
    - IntraBrokerDiskUsageDistribution
- goals
    - RackAware
    - RackAwareDistribution
    - ReplicaCapacity
    - DiskCapacity
    - NetworkInboundCapacity
    - NetworkOutboundCapacity
    - CpuCapacity
    - ReplicaDistribution
    - PotentialNwOut
    - DiskUsageDistribution
    - NetworkInboundUsageDistribution
    - NetworkOutboundUsageDistribution
    - CpuUsageDistribution
    - LeaderReplicaDistribution
    - LeaderBytesInDistribution
    - TopicReplicaDistribution
    - PreferredLeaderElection
    - IntraBrokerDiskCapacity
    - IntraBrokerDiskUsageDistribution
- hard.goals
    - RackAware
    - RackAwareDistribution
    - DiskCapacity
    - NetworkInboundCapacity
    - NetworkOutboundCapacity
    - CpuCapacity
    - ReplicaDistribution
    - IntraBrokerDiskCapacity

## Balance Thresholds
### Generalise to single config = 1.1?
- cpu.balance.threshold=1.1
- disk.balance.threshold=1.1
- network.inbound.balance.threshold=1.1
- network.outbound.balance.threshold=1.1
- replica.count.balance.threshold=1.1
- leader.replica.count.balance.threshold=1.1

## Capacity Thresholds
### Generalise to single config = 0.8?
- disk.capacity.threshold=0.8
- cpu.capacity.threshold=0.7
- network.inbound.capacity.threshold=0.8
- network.outbound.capacity.threshold=0.8

## Low Utilization + Overprovisioning Thresholds 
### Generalise to hardcoded value? = 0.2?
### Do we want to alert users that they're overprovisioned?
- disk.low.utilization.threshold=0.0
- cpu.low.utilization.threshold=0.0
- network.inbound.low.utilization.threshold=0.0
- network.outbound.low.utilization.threshold=0.0
- overprovisioned.min.extra.racks=2
- overprovisioned.min.brokers=3
- overprovisioned.max.replicas.per.broker=1500

## Weighting Tuning
### Not sure what to do with these, plain config?
- goal.violation.distribution.threshold.multiplier=1.0
- goal.balancedness.priority.weight=1.1
- goal.balancedness.strictness.weight=1.5

## Other
### Leave as defaults
- proposal.expiration.ms=900000
- max.replicas.per.broker=10000
- num.proposal.precompute.threads=1
- topic.replica.count.balance.threshold=3.0
- topic.replica.count.balance.min.gap=2
- topic.replica.count.balance.max.gap=40
- topics.with.min.leaders.per.broker=""
- min.topic.leaders.per.broker=1
- optimization.options.generator.class=com.linkedin.kafka.cruisecontrol.analyzer.DefaultOptimizationOptionsGenerator
- intra.broker.goals=
- allow.capacity.estimation.on.proposal.precompute=true
- fast.mode.per.broker.move.timeout.ms=500
