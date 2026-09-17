# EdgeFirst Perception and ROS 2

EdgeFirst Perception speaks ROS 2's message language without being a ROS 2 middleware. This page is the roadmap for closing that gap. For how to actually connect a device today, see the [Perception documentation](https://doc.edgefirst.ai/latest/perception/).

## What EdgeFirst is and isn't

| | EdgeFirst Perception today |
|---|---|
| Message definitions | ROS 2 common interfaces (`std_msgs`, `geometry_msgs`, `sensor_msgs`, `nav_msgs`), Foxglove schemas, and `edgefirst_msgs` |
| Encoding | ROS 2 CDR |
| Coordinate frames | REP-103, with `base_link` → sensor transforms on `tf_static` |
| Transport | Native Zenoh pub/sub with hostname-namespaced keys |
| ROS 2 installation on the device | Not required |
| RMW implementation | **No.** Services don't use `rcl` or an RMW, and don't appear as ROS 2 nodes |
| Interoperates with `rmw_zenoh` directly | **No.** `rmw_zenoh` keys carry the domain, type name and type hash. Adopting its wire format is roadmap work |
| Joins a ROS 2 graph | Yes, through [`zenoh-bridge-ros2dds`](https://github.com/eclipse-zenoh/zenoh-plugin-ros2dds) |

Why build it this way? A sensor shouldn't need a ROS distribution to publish data. The same services run on devices with no ROS at all, feed our Web UI and MCAP recordings, and still hand ROS 2 systems standard messages when they're connected.

## Where it stands today

`zenoh-bridge-ros2dds` maps a ROS topic name directly onto a Zenoh key expression — `/camera/h264` is the key `camera/h264` — which is exactly what EdgeFirst services publish. Zenoh's session-level `namespace` strips the device prefix, so a bridge run with the device hostname hands ROS 2 a plain `/camera/h264`. One bridge per device is what keeps two devices from colliding on the same ROS topic names, and it is why the services moved from `rt/` to hostname prefixes.

Point clouds, IMU, GPS and camera intrinsics arrive as the standard `sensor_msgs` types. `edgefirst_msgs` topics need the [`schemas`](https://github.com/EdgeFirstAI/schemas) package, which builds as a ROS 2 message package. Two rough edges are known: `tf_static` is published as `geometry_msgs/TransformStamped` where tf2 expects `tf2_msgs/TFMessage`, and the bridge creates its route on discovering a subscriber, so a topic may not be listed until something subscribes to it.

## Roadmap

> [!IMPORTANT]
> Everything below is planned work, not shipped functionality.

We want ROS 2 teams to get EdgeFirst services as first-class participants in their graph without losing the properties that make the stack useful on embedded hardware.

- **Discoverable graph participants.** Services appear to `ros2 node list`, `ros2 topic`, and `ros2 param` without an external bridge.
- **Standard lifecycle and parameters,** mapped onto each service's existing configuration.
- **No C/C++ ROS dependency.** The services are Rust; ROS 2 support stays an optional Cargo feature.
- **Same topics, same messages,** whichever mode a service runs in.
- **Zero-copy preserved, and extended.** Camera frames keep moving as DMA-BUF handles on the device. Going further inside a ROS 2 graph is an open question — either the ROS 2 RFCs covering custom allocators and memory regions, or the [shared-memory support planned for the Zenoh services](zenoh.md#what-is-actually-zero-copy-and-what-isnt) if that works with `rmw_zenoh`.
- **`edgefirst_bringup`.** Launch files and presets for Maivin, Raivin, and LiDAR variants.

### Transport: `rmw_zenoh`, as a mode

Two credible routes existed from pure Rust: speak the [`rmw_zenoh`](https://github.com/ros2/rmw_zenoh) wire protocol from the Zenoh sessions the services already open, or become a native DDS participant. **We are taking the `rmw_zenoh` route** — the services are already Zenoh-native, so it is the smaller change and it keeps Zenoh's footprint on the device. A DDS participant is something we would add if customers running DDS-based graphs ask for it.

It will be a **mode, not an addition.** A service will run either Zenoh-native, as today, or as an `rmw_zenoh` participant, chosen at launch. The two cannot be combined: `rmw_zenoh` key expressions carry the domain, type name and type hash, the bridge route above works because today's keys are the bare topic name, and upstream states the two cannot interoperate. So each mode reaches one world and not the other.

If you run EdgeFirst hardware alongside ROS 2 — AMRs, agriculture, industrial, ADAS — which RMW your robots use is the most useful thing you can tell us. [Get in touch](https://www.au-zone.com).

---

[Overview](README.md) · [Foundation](foundation.md) · [Middleware](zenoh.md) · [Profiler](profiler.md) · [GStreamer](gstreamer.md) · [Platforms](platforms.md) · [Documentation](https://doc.edgefirst.ai/latest/perception/)

<img referrerpolicy="no-referrer" src="https://px.edgefirst.ai/a.png?x-pxid=0c76d54e-56c0-46ec-b74c-60e47e60493d" alt="" width="1" height="1" style="position:absolute; width:1px; height:1px; opacity:0; pointer-events:none;" />
