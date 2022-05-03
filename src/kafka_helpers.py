from charms.operator_libs_linux.v1 import snap
from charms.operator_libs_linux.v0 import apt


def install_packages():
    apt.update()
    apt.add_package("snapd")

    cache = snap.SnapCache()
    kafka = cache["kafka"]

    if not kafka.present:
        kafka.ensure(snap.SnapState.Latest, channel="rock/edge")
