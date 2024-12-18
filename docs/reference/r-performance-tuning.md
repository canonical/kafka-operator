# Performance tuning

This section contains some suggested values to get a better performance from Charmed Apache Kafka.

## Virtual memory handling (recommended)

Apache Kafka brokers make heavy use of the OS page cache to maintain performance. They never normally explicitly issue a command to ensure messages have been persisted to disk (`sync`), relying instead on the underlying OS to ensure that larger chunks (pages) of data are persisted from the page cache to the disk when the OS deems it efficient and/or necessary to do so. As such, there is a range of runtime kernel parameter tuning that is recommended to be set on machines running Apache Kafka to improve performance.

To configure these settings, one can write them to `/etc/sysctl.conf` using `sudo echo $SETTING >> /etc/sysctl.conf`. Note that the settings shown below are simply sensible defaults that may not apply to every workload:
```bash
# ensures a low likelihood of memory being assigned to swap space rather than drop pages from the page cache
vm.swappiness=1

# higher ratio results in less frequent disk flushes and better disk I/O performance
vm.dirty_ratio=80
vm.dirty_background_ratio=5
```

## Memory maps (recommended)

Each Apache Kafka log segment requires an `index` file and a `timeindex` file, both requiring one map area. The default OS maximum number of memory map areas a process can have is set by `vm.max_map_count=65536`. For production deployments with a large number of partitions and log-segments, it is likely to exceed the maximum OS limit.

It is recommended to set the mmap number sufficiently higher than the number of memory mapped files. This can also be written to `/etc/sysctl.conf`:

```bash
vm.max_map_count=<new_mmap_value>
```

## File descriptors (recommended)

Apache Kafka uses file descriptors for log segments and open connections. If a broker hosts many partitions, keep in mind that the broker requires **at least** `(number_of_partitions)*(partition_size/segment_size)` file descriptors to track all the log segments and number of connections.

To configure those limits, update the values and add the following to `/etc/security/limits.d/root.conf`:

```bash
#<domain> <type> <item> <value>
root soft nofile 262144
root hard nofile 1024288
```

## Networking (optional)

If you are expecting a large amount of network traffic, kernel parameter tuning may help meet that expected demand. These can also be written to `/etc/sysctl.conf`:

```bash
# default send socket buffer size
net.core.wmem_default=
# default receive socket buffer size
net.core.rmem_default=
# maximum send socket buffer size
net.core.wmem_max=
# maximum receive socket buffer size
net.core.rmem_max=
# memory reserved for TCP send buffers
net.ipv4.tcp_wmem=
# memory reserved for TCP receive buffers
net.ipv4.tcp_rmem=
# TCP Window Scaling option
net.ipv4.tcp_window_scaling=
# maximum number of outstanding TCP connection requests
net.ipv4.tcp_max_syn_backlog=
# maximum number of queued packets on the kernel input side (useful to deal with spike of network requests).
net.core.netdev_max_backlog=
```