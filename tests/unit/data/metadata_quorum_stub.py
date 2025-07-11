#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

DESCRIBE_REPLICATION_RESPONSE = """
NodeId	DirectoryId           	LogEndOffset	Lag	LastFetchTimestamp	LastCaughtUpTimestamp	Status
0     	_u63b3fXn1jeklAC-6kmqQ	34516       	0  	1749280488535     	1749280488535        	Leader
1     	2rxcYUwQSvG8mI91fx7_gQ	34516       	0  	1749280488114     	1749280488114        	Follower
100   	DTmCiijKqa_PqGVUSLMUqw	34516       	0  	1749280488109     	1749280488109        	Observer
101   	O2MHvwsuZwvVs9f8QFLXfw	34516       	-1  	1749280488109     	1749280488109        	Observer
"""

TIMEOUT_EXCEPTION = """
org.apache.kafka.common.errors.TimeoutException: Timed out waiting for a node assignment. Call: describeMetadataQuorum
java.util.concurrent.ExecutionException: org.apache.kafka.common.errors.TimeoutException: Timed out waiting for a node assignment. Call: describeMetadataQuorum
	at java.base/java.util.concurrent.CompletableFuture.reportGet(CompletableFuture.java:396)
	at java.base/java.util.concurrent.CompletableFuture.get(CompletableFuture.java:2073)
	at org.apache.kafka.common.internals.KafkaFutureImpl.get(KafkaFutureImpl.java:165)
	at org.apache.kafka.tools.MetadataQuorumCommand.handleDescribeReplication(MetadataQuorumCommand.java:197)
	at org.apache.kafka.tools.MetadataQuorumCommand.execute(MetadataQuorumCommand.java:133)
	at org.apache.kafka.tools.MetadataQuorumCommand.mainNoExit(MetadataQuorumCommand.java:81)
	at org.apache.kafka.tools.MetadataQuorumCommand.main(MetadataQuorumCommand.java:76)
Caused by: org.apache.kafka.common.errors.TimeoutException: Timed out waiting for a node assignment. Call: describeMetadataQuorum
"""

DUPLICATE_VOTER_EXCEPTION = """
org.apache.kafka.common.errors.DuplicateVoterException: The voter id for ReplicaKey(id=1, directoryId=Optional[_u63b3fXn1jeklAC-6kmqQ]) is already part of the set of voters [ReplicaKey(id=1, directoryId=Optional[_u63b3fXn1jeklAC-6kmqQ]), ReplicaKey(id=0, directoryId=Optional[2rxcYUwQSvG8mI91fx7_gQ])].
java.util.concurrent.ExecutionException: org.apache.kafka.common.errors.DuplicateVoterException: The voter id for ReplicaKey(id=1, directoryId=Optional[_u63b3fXn1jeklAC-6kmqQ]) is already part of the set of voters [ReplicaKey(id=1, directoryId=Optional[_u63b3fXn1jeklAC-6kmqQ]), ReplicaKey(id=0, directoryId=Optional[2rxcYUwQSvG8mI91fx7_gQ])].
	at java.base/java.util.concurrent.CompletableFuture.reportGet(CompletableFuture.java:396)
	at java.base/java.util.concurrent.CompletableFuture.get(CompletableFuture.java:2073)
	at org.apache.kafka.common.internals.KafkaFutureImpl.get(KafkaFutureImpl.java:165)
	at org.apache.kafka.tools.MetadataQuorumCommand.handleAddController(MetadataQuorumCommand.java:431)
	at org.apache.kafka.tools.MetadataQuorumCommand.execute(MetadataQuorumCommand.java:147)
	at org.apache.kafka.tools.MetadataQuorumCommand.mainNoExit(MetadataQuorumCommand.java:81)
	at org.apache.kafka.tools.MetadataQuorumCommand.main(MetadataQuorumCommand.java:76)
Caused by: org.apache.kafka.common.errors.DuplicateVoterException: The voter id for ReplicaKey(id=1, directoryId=Optional[_u63b3fXn1jeklAC-6kmqQ]) is already part of the set of voters [ReplicaKey(id=1, directoryId=Optional[_u63b3fXn1jeklAC-6kmqQ]), ReplicaKey(id=0, directoryId=Optional[2rxcYUwQSvG8mI91fx7_gQ])].
"""

VOTER_NOT_FOUND_EXCEPTION = """
org.apache.kafka.common.errors.VoterNotFoundException: Cannot remove voter ReplicaKey(id=105, directoryId=Optional[abcdefghijklmnopqrstug]) from the set of voters [ReplicaKey(id=1, directoryId=Optional[_u63b3fXn1jeklAC-6kmqQ]), ReplicaKey(id=0, directoryId=Optional[2rxcYUwQSvG8mI91fx7_gQ])]
java.util.concurrent.ExecutionException: org.apache.kafka.common.errors.VoterNotFoundException: Cannot remove voter ReplicaKey(id=105, directoryId=Optional[abcdefghijklmnopqrstug]) from the set of voters [ReplicaKey(id=1, directoryId=Optional[_u63b3fXn1jeklAC-6kmqQ]), ReplicaKey(id=0, directoryId=Optional[2rxcYUwQSvG8mI91fx7_gQ])]
	at java.base/java.util.concurrent.CompletableFuture.reportGet(CompletableFuture.java:396)
	at java.base/java.util.concurrent.CompletableFuture.get(CompletableFuture.java:2073)
	at org.apache.kafka.common.internals.KafkaFutureImpl.get(KafkaFutureImpl.java:165)
	at org.apache.kafka.tools.MetadataQuorumCommand.handleRemoveController(MetadataQuorumCommand.java:499)
	at org.apache.kafka.tools.MetadataQuorumCommand.execute(MetadataQuorumCommand.java:151)
	at org.apache.kafka.tools.MetadataQuorumCommand.mainNoExit(MetadataQuorumCommand.java:81)
	at org.apache.kafka.tools.MetadataQuorumCommand.main(MetadataQuorumCommand.java:76)
Caused by: org.apache.kafka.common.errors.VoterNotFoundException: Cannot remove voter ReplicaKey(id=105, directoryId=Optional[abcdefghijklmnopqrstug]) from the set of voters [ReplicaKey(id=1, directoryId=Optional[_u63b3fXn1jeklAC-6kmqQ]), ReplicaKey(id=0, directoryId=Optional[2rxcYUwQSvG8mI91fx7_gQ])]
"""

METADATA_QUORUM_STUB = {
    "describe-replication": DESCRIBE_REPLICATION_RESPONSE,
    "timeout-exception": TIMEOUT_EXCEPTION,
    "duplicate-voter-exception": DUPLICATE_VOTER_EXCEPTION,
    "voter-not-found-exception": VOTER_NOT_FOUND_EXCEPTION,
}
