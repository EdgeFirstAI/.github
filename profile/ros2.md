# EdgeFirst Perception and ROS 2

EdgeFirst Perception speaks ROS 2's message language without being a ROS 2 middleware. This page explains exactly what that means, how to use EdgeFirst devices from ROS 2 today, and where we're taking the integration.

## What EdgeFirst is and isn't

| | EdgeFirst Perception today |
|---|---|
| Message definitions | ROS 2 common interfaces (`std_msgs`, `geometry_msgs`, `sensor_msgs`, `nav_msgs`), Foxglove schemas, and `edgefirst_msgs` |
| Encoding | ROS 2 CDR |
| Coordinate frames | REP-103, with `base_link` → sensor transforms on `tf_static` |
| Transport | Native Zenoh pub/sub with hostname-namespaced keys |
| ROS 2 installation on the device | Not required |
| RMW implementation | **No.** Services don't use `rcl` or an RMW, and don't appear as ROS 2 nodes |
| Interoperates with `rmw_zenoh` directly | **Not yet.** Key expressions differ — adopting them is the roadmap |
| Joins a ROS 2 graph | **Not yet.** The [`zenoh-bridge-ros2dds`](https://github.com/eclipse-zenoh/zenoh-plugin-ros2dds) route is unsolved; native `rmw_zenoh` support is the plan |

Why build it this way? A sensor shouldn't need a ROS distribution to publish data. The same services run on devices with no ROS at all and feed our Web UI and MCAP recordings, while using message types a ROS 2 system already understands — so connecting the two is a transport problem, not a data problem.

## Reaching EdgeFirst topics from ROS 2

> [!IMPORTANT]
> This path is **not yet a supported, tested recipe.** The shape below is right and the message types are already correct, but the key-to-topic mapping is an open problem we have not solved on hardware. Treat it as the direction of travel, not instructions. Native `rmw_zenoh` support — see the [roadmap](#roadmap) — is how this is intended to work properly.

```mermaid
flowchart LR
    subgraph device["EdgeFirst device"]
        svc["EdgeFirst services<br/>native Zenoh keys"] --> zenohd["zenohd<br/>TCP 7447"]
    end
    subgraph host["ROS 2 host"]
        bridge["zenoh-bridge-ros2dds"] --> dds["ROS 2 DDS graph"]
        dds --> rviz["RViz2"]
        dds --> nav["Nav2 / your nodes"]
    end
    zenohd -- "Zenoh" --> bridge
```

**What works.** `zenohd` can be enabled on the device (it is off by default — see [Remote Connections](https://doc.edgefirst.ai/latest/perception/dev/#remote-connections)), and the payloads are already ROS 2 CDR carrying standard message types. Nothing about the data needs converting.

**What doesn't, yet.** `zenoh-bridge-ros2dds` bridges a ROS 2 DDS graph to Zenoh using its own key convention. EdgeFirst services publish on native Zenoh keys under a hostname namespace — `verdin-imx8mp-15141091/radar/targets` — which is not that convention. Two specific obstacles:

- The bridge's `namespace` option *prefixes* ROS names for the multi-robot case. It does not rewrite arbitrary Zenoh keys into ROS topic names.
- ROS names permit only alphanumerics and underscores, and device hostnames contain hyphens, so the hostname cannot be used as a ROS namespace as-is.

Closing this needs either a tested key-remapping setup or a device-side namespace override. Until one exists, the dependable routes off the device are MCAP recordings in Foxglove and your own Zenoh subscribers using [`schemas`](https://github.com/EdgeFirstAI/schemas).

### What you get on the ROS 2 side

| Topic | Message type | Works with stock ROS 2 tools |
|-------|--------------|------------------------------|
| `camera/info` | `sensor_msgs/CameraInfo` | Yes |
| `camera/jpeg` | `sensor_msgs/CompressedImage` | Yes, with `image_transport` |
| `radar/targets`, `radar/clusters` | `sensor_msgs/PointCloud2` | Yes, RViz2 PointCloud2 display |
| `lidar/points`, `lidar/clusters` | `sensor_msgs/PointCloud2` | Yes |
| `fusion/radar`, `fusion/lidar`, `fusion/occupancy` | `sensor_msgs/PointCloud2` | Yes; colour by `vision_class` in RViz2 |
| `imu`, `lidar/imu` | `sensor_msgs/Imu` | Yes |
| `gps` | `sensor_msgs/NavSatFix` | Yes |
| `tf_static` | `geometry_msgs/TransformStamped` | Not directly — see below |
| `camera/h264` | `foxglove_msgs/CompressedVideo` | Needs `foxglove_msgs` and a decoder; RViz2 has no H.264 display |
| `model/output`, `model/info`, `fusion/boxes3d`, `radar/cube`, `radar/info` | `edgefirst_msgs/*` | Needs the `edgefirst_msgs` package; no stock RViz2 display |

EdgeFirst publishes `tf_static` as individual `geometry_msgs/TransformStamped` messages. ROS 2's tf2 subscribes to `/tf_static` expecting `tf2_msgs/TFMessage`, which wraps an array of transforms, so **the transforms need an adapter before RViz2 or tf2 will consume them**. Without TF, point clouds will not place correctly in RViz2. Whether the bridge can do that wrapping for you is being confirmed.

### Custom messages: `edgefirst_msgs`

[`schemas`](https://github.com/EdgeFirstAI/schemas) builds as a ROS 2 message package. Add it to your workspace and your nodes can subscribe to `model/output` for detections, masks, and tracks, `fusion/boxes3d` for 3D boxes, and `radar/cube` for raw radar tensors. They get the same types the EdgeFirst services use.

### Recordings

`recorder` writes MCAP with the schemas embedded, and channels are named `/camera/h264`, `/fusion/radar`, and so on. Recordings open in Foxglove with the [EdgeFirst plug-in](https://github.com/EdgeFirstAI/foxglove).

rosbag2 compatibility is a separate question from Foxglove: `ros2 bag` expects its own storage profile and metadata alongside the MCAP, which the recorder does not write today. Whether recordings replay directly through rosbag2 has not been verified.

## Performance when serialization is needed

A publisher encodes CDR once. The recorder, the network, and the bridge then move those encoded bytes without re-encoding them — only a subscriber that actually inspects fields pays a decode. [`schemas`](https://github.com/EdgeFirstAI/schemas) makes that decode cheap by reading CDR in place instead of materializing a copy. Against the codecs used by the two major ROS 2 middleware vendors, on a Raspberry Pi 5 ([BENCHMARKS.md](https://github.com/EdgeFirstAI/schemas/blob/main/BENCHMARKS.md)):

| Message | EdgeFirst decode | Fast-CDR | Cyclone DDS |
|---------|------------------|----------|-------------|
| `sensor_msgs/PointCloud2`, Ouster 128-beam | 123 ns | 784 µs | 819 µs |
| `edgefirst_msgs/RadarCube`, DRVEGRD-171 extra long | 58 ns | 3.4 ms | 3.4 ms |
| `foxglove_msgs/CompressedVideo`, 1 MB | 53 ns | 122 µs | 134 µs |

Decode is the cost a subscriber pays before touching the data. A node that reads, modifies, and republishes an entire HD image still pays for walking the pixels; in that workflow the advantage is about 1.9×. Both results are in BENCHMARKS.md.

Inside the device, camera frames skip serialization entirely: they move between processes as DMA-BUF handles. See [what is actually zero-copy](zenoh.md#what-is-actually-zero-copy-and-what-isnt) in the Perception Middleware.

## Roadmap

> [!IMPORTANT]
> Everything below is planned work, not shipped functionality.

We want ROS 2 teams to get EdgeFirst services as first-class participants in their graph without losing the properties that make the stack useful on embedded hardware.

### Goals

- **Discoverable graph participants.** EdgeFirst services appear to `ros2 node list`, `ros2 topic`, and `ros2 param` without an external bridge.
- **Standard lifecycle and parameters.** Lifecycle transitions and parameter services mapped onto each service's existing configuration.
- **No C/C++ ROS dependency.** The services are Rust. ROS 2 support stays an optional Cargo feature, so builds without it carry no ROS 2 code.
- **Same topics, same messages.** Topic names and message types are identical whether a service runs in Zenoh-native or ROS 2 mode.
- **Zero-copy preserved, and extended.** Camera frames continue to move as DMA-BUF handles on the device, and serialization happens only where a hop requires it. Going further in a ROS 2 graph is an open question we intend to answer: either through the ROS 2 RFCs covering custom allocators and memory regions, if that is what interoperability requires, or by reusing the [shared-memory support planned for the Zenoh services](zenoh.md#what-is-actually-zero-copy-and-what-isnt) should that work with `rmw_zenoh`. Which of the two applies is still to be determined.
- **`edgefirst_bringup`.** Launch files and presets for Maivin, Raivin, and LiDAR variants.

### Transport: we are going with `rmw_zenoh`

There were two credible ways to reach those goals from pure Rust, and they don't interoperate with each other.

| Approach | Strengths | Trade-offs |
|----------|-----------|------------|
| **Speak the `rmw_zenoh` wire protocol** — its key expressions, liveliness tokens, and attachments — directly from the existing Zenoh sessions | Keeps Zenoh end to end. Matches the Tier-1 Zenoh middleware in current ROS 2 releases. Smallest change to the services | Only interoperates with graphs running `rmw_zenoh`. Must track rmw_zenoh protocol changes across distributions |
| **Native DDS participant** through a pure-Rust ROS 2 client | Works with default DDS-based ROS 2 graphs | Adds a DDS stack to every service. Loses Zenoh's footprint and routing on the device |

**We are taking the `rmw_zenoh` route.** The services are already Zenoh-native, so this is the smallest change: adopt the `rmw_zenoh` wire details in sessions we already open. The goal is that every EdgeFirst Zenoh application gains the ability to talk to an `rmw_zenoh` ROS 2 graph *or* to direct Zenoh peers as it does today — same topics, same messages, same binary.

We would add a native DDS participant if customers running DDS-based graphs ask for it, but Zenoh is the better fit for embedded targets and it is where we already are.

If you run EdgeFirst hardware alongside ROS 2 — AMRs, agriculture, industrial, ADAS — which RMW your robots use is still the most useful thing you can tell us. [Get in touch](https://www.au-zone.com).

---

[Overview](README.md) · [Foundation](foundation.md) · [Middleware](zenoh.md) · [Profiler](profiler.md) · [GStreamer](gstreamer.md) · [Platforms](platforms.md) · [Documentation](https://doc.edgefirst.ai/latest/perception/)
