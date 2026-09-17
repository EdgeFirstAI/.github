# EdgeFirst Perception Foundation

The Foundation is the set of libraries every other layer is built from. The [Perception Middleware](zenoh.md), the [GStreamer elements](gstreamer.md), the [Profiler](profiler.md), and your own applications all use the same code for buffers, image processing, model decoding, tracking, video, and messages.

## Core principle: keep data where it is

Every Foundation library is designed so data stays in the buffer it was produced in:

- A camera frame is captured into a DMA-BUF and never copied into a CPU array on the way to the NPU.
- Colour conversion, resize, and letterboxing run on GPU- or G2D-backed tensors.
- A received message is read in place instead of being deserialized into a new structure.

On embedded SoCs, memory bandwidth is usually the bottleneck before compute is, so these choices decide whether a pipeline meets its frame budget.

## Libraries

### Tensors, image processing, decoding, tracking

| Repository | Bindings | Description |
|-----------|----------|-------------|
| [`hal`](https://github.com/EdgeFirstAI/hal) | Rust · Python · C | Hardware abstraction for inference pipelines. Zero-copy tensors over DMA-BUF, PBO, shared memory, IOSurface, and AHardwareBuffer; image conversion dispatched across OpenGL ES, NXP G2D, and CPU; YOLO (v5, v8, v11, v26) and ModelPack decoding; ByteTrack multi-object tracking; tiled inference (SAHI). Published as `edgefirst-tensor`, `edgefirst-image`, `edgefirst-decoder`, `edgefirst-tracker`, and `edgefirst-codec` |

### Video

| Repository | Bindings | Description |
|-----------|----------|-------------|
| [`videostream`](https://github.com/EdgeFirstAI/videostream) | C · Rust · GStreamer | V4L2 capture with DMA-BUF export, hardware H.264/H.265 encoding (Hantro on i.MX 8M Plus, Wave6 on i.MX 95), and zero-copy frame sharing between processes |

### Messaging

| Repository | Bindings | Description |
|-----------|----------|-------------|
| [`schemas`](https://github.com/EdgeFirstAI/schemas) | Rust · Python · C++ | ROS 2 common interfaces (`std_msgs`, `geometry_msgs`, `sensor_msgs`, `nav_msgs`), Foxglove schemas, and custom `edgefirst_msgs` with a borrowing CDR codec. Used by every microservice, by the GStreamer Zenoh elements, and buildable as a ROS 2 message package. See [Borrowing CDR decode](#borrowing-cdr-decode) |

`schemas` lives in the Foundation rather than the Zenoh layer because nothing about it is Zenoh-specific: it encodes and decodes CDR bytes, whatever carries them.

### Inference runtimes

| Repository | Bindings | Description |
|-----------|----------|-------------|
| [`tflite-rs`](https://github.com/EdgeFirstAI/tflite-rs) | Rust | TensorFlow Lite bindings published as [`edgefirst-tflite`](https://crates.io/crates/edgefirst-tflite), with DMA-BUF input and CameraAdaptor runtime support on NPUs that provide it (currently i.MX 8M Plus) |
| [`tflite-vx-delegate-imx`](https://github.com/EdgeFirstAI/tflite-vx-delegate-imx) | C++ | TensorFlow Lite delegate for the i.MX 8M Plus Vivante NPU with DMA-BUF passthrough and CameraAdaptor support |
| [`tim-vx-imx`](https://github.com/EdgeFirstAI/tim-vx-imx) | C++ | TIM-VX for the i.MX 8M Plus NPU with DMA-BUF and CameraAdaptor support |
| [`tflite-neutron-delegate`](https://github.com/EdgeFirstAI/tflite-neutron-delegate) | C++ | DMA-BUF support for the NXP Neutron NPU delegate on i.MX 95 |
| [`ara2-rs`](https://github.com/EdgeFirstAI/ara2-rs) | Rust | Library for the NXP Ara240 (Kinara Ara-2) neural accelerator |
| [`packaging`](https://github.com/EdgeFirstAI/packaging) | — | Vendor-curated binary distributions of ONNX Runtime and TensorFlow Lite C for EdgeFirst deployment targets |

### Model training for native sensor formats

| Repository | Description |
|-----------|-------------|
| [`cameraadaptor`](https://github.com/EdgeFirstAI/cameraadaptor) | Python training library for models that take camera-native formats (YUV, Bayer, BGR) directly, removing runtime colour conversion |
| [`ultralytics`](https://github.com/EdgeFirstAI/ultralytics) | Fork of Ultralytics YOLO with CameraAdaptor integration |

### Drivers and system libraries

| Repository | Description |
|-----------|-------------|
| [`g2d-rs`](https://github.com/EdgeFirstAI/g2d-rs) | Rust API for NXP G2D 2D acceleration |
| [`gbm.rs`](https://github.com/EdgeFirstAI/gbm.rs) | Rust bindings for libgbm buffer allocation |
| [`kernel-module-uiodma`](https://github.com/EdgeFirstAI/kernel-module-uiodma) | User-space DMA driver for direct hardware buffer access |
| [`bno08x-rs`](https://github.com/EdgeFirstAI/bno08x-rs) | Rust driver for the BNO08x IMU family |

### Platform builds

| Repository | Description |
|-----------|-------------|
| [`yocto`](https://github.com/EdgeFirstAI/yocto) | Yocto manifests for complete EdgeFirst builds |
| [`meta-edgefirst`](https://github.com/EdgeFirstAI/meta-edgefirst) | Yocto recipes for EdgeFirst Perception |
| [`meta-kinara`](https://github.com/EdgeFirstAI/meta-kinara) | Yocto enablement for the NXP Ara240 (Kinara Ara-2) |

## How the microservices use the Foundation

Each microservice is a thin process wrapped around Foundation libraries. The service owns configuration, sensor I/O, and topics; the Foundation does the heavy lifting. How much a service leans on it varies, and the variation is informative.

| Service | Foundation libraries | What they do in the service |
|---------|---------------------|-----------------------------|
| `camera` | `videostream`, `schemas` | V4L2 capture into DMA-BUF, hardware H.264 encode, `CameraFrame` handles for zero-copy sharing |
| `model` | `hal` (`edgefirst-hal`, `edgefirst-tracker`), `edgefirst-tflite`, `schemas` | Frame import and letterbox, NPU inference, box and mask decoding, ByteTrack, `Model` message |
| `fusion` | `schemas` | Point cloud projection, tracking, and occupancy. Works its own DMA-BUF, G2D, and tensor paths directly rather than through HAL, and vendors its own TFLite binding for the fusion model |
| `radarpub` | `schemas` | smartmicro CAN and Ethernet ingest to `PointCloud2` and `RadarCube` |
| `lidarpub` | `schemas` | Robosense and Ouster ingest, clustering, ground filter, `PointCloud2` and `Imu` |
| `imu` | `bno08x-rs`, `schemas` | Orientation and motion to `sensor_msgs/Imu` |
| `navsat` | `schemas` | GPS position from `gpsd` to `sensor_msgs/NavSatFix` |
| `recorder` | — | Writes MCAP with the schemas embedded. It never decodes a message: CDR payloads pass from Zenoh to the file untouched, which is why recording cost is independent of what is being recorded |

`recorder` is the clearest case for the architecture. Because every payload is already ROS 2 CDR with a schema attached, a recorder needs no knowledge of any message type — it copies bytes and embeds the schema definition alongside them.

## Borrowing CDR decode

A conventional CDR codec walks the entire buffer and copies every field into a new object. `edgefirst-schemas` takes a different approach:

1. `from_cdr` scans the buffer once and records offsets for the variable-length fields.
2. Field accessors read at those offsets on demand.
3. Strings come back as slices into the original buffer, and typed numeric arrays are reinterpreted in place.

The buffer is never copied, so decode cost stays flat as the payload grows. Selected results from [BENCHMARKS.md](https://github.com/EdgeFirstAI/schemas/blob/main/BENCHMARKS.md) on a Raspberry Pi 5, against the codecs used by the two major ROS 2 middleware vendors:

| Message | EdgeFirst | Fast-CDR | Cyclone DDS |
|---------|-----------|----------|-------------|
| `CompressedVideo`, 1 MB payload | 53 ns | 122 µs | 134 µs |
| `RadarCube`, DRVEGRD-171 extra long | 58 ns | 3.4 ms | 3.4 ms |
| `PointCloud2`, Ouster 128-beam | 123 ns | 784 µs | 819 µs |
| `Mask`, 640×640, 8 classes | 53 ns | 28.1 µs | 26.8 µs |

**Read these numbers carefully.** They measure decode, which is what a subscriber pays before it touches the data.

- A subscriber that reads a few fields, or forwards the bytes to a recorder or bridge, gets nearly all of that advantage.
- A subscriber that reads, modifies, and republishes an entire HD image still pays for walking the pixels. In that workflow the benchmark shows about 1.9× over Fast-CDR, not thousands.

BENCHMARKS.md includes both the decode and the full-workflow results, with the method for reproducing them.

## Supported hardware

- **NXP i.MX 8M Plus and i.MX 95** — G2D, VPU encoding, DMA-BUF, NPU inference
- **NVIDIA Jetson (Orin series)** — OpenGL ES with zero-copy CUDA tensor mapping for TensorRT
- **Raspberry Pi 5** — including Hailo-8 and Hailo-8L accelerators
- **NXP Ara240 (Kinara Ara-2)**
- **Development hosts** — Linux, macOS, and Windows for the portable libraries

Each repository's README lists the tiers it supports on each target. The [Profiler](profiler.md) runs on this same set, so you can measure a model on a target before committing to it.

---

[Overview](README.md) · [Middleware](zenoh.md) · [Profiler](profiler.md) · [GStreamer](gstreamer.md) · [ROS 2](ros2.md) · [Platforms](platforms.md) · [Documentation](https://doc.edgefirst.ai/latest/perception/)
