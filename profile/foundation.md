# EdgeFirst Perception Foundation

The Foundation layer provides the low-level building blocks that every other layer of EdgeFirst Perception depends on — hardware abstraction, optimized video I/O, and accelerated neural network inference on embedded SoCs.

## Core Philosophy

All Foundation libraries are designed around **zero-copy data flow** and **DMA buffer management**. From the moment a sensor produces data to the moment inference results are consumed, EdgeFirst minimizes — and where possible eliminates — memory copies. This is essential for meeting the real-time latency and power constraints of edge deployments.

## Repositories

### Hardware Abstraction

| Repository | Description |
|-----------|-------------|
| [`hal`](https://github.com/EdgeFirstAI/hal) | Hardware abstraction layer providing unified APIs for sensor access, DMA buffer management, and platform-specific acceleration across supported SoCs |
| [`videostream`](https://github.com/EdgeFirstAI/videostream) | High-performance video capture and output library with V4L2 integration, DMA buffer passthrough, and hardware codec support |
| [`tflite-rs`](https://github.com/EdgeFirstAI/tflite-rs) | Rust bindings for TensorFlow Lite (published as `edgefirst-tflite` on [crates.io](https://crates.io/crates/edgefirst-tflite)), with DMA buffer passthrough and CameraAdaptor runtime support on platforms with supported NPUs (currently i.MX 8M Plus) |

### Model Training & Export

| Repository | Description |
|-----------|-------------|
| [`cameraadaptor`](https://github.com/EdgeFirstAI/cameraadaptor) | Python training library for creating models that accept native camera/hardware formats (YUV, Bayer, BGR) directly, eliminating costly runtime color conversion |
| [`ultralytics`](https://github.com/EdgeFirstAI/ultralytics) | Fork of Ultralytics YOLO with CameraAdaptor integration for training edge-optimized detection models that consume native sensor formats |

### NXP i.MX Libraries

| Repository | Description |
|-----------|-------------|
| [`tim-vx-imx`](https://github.com/EdgeFirstAI/tim-vx-imx) | TIM-VX integration for i.MX 8M Plus NPU acceleration with DMA buffer and CameraAdaptor runtime support |
| [`tflite-vx-delegate-imx`](https://github.com/EdgeFirstAI/tflite-vx-delegate-imx) | TensorFlow Lite delegate for the i.MX 8M Plus Vivante NPU with DMA buffer passthrough and CameraAdaptor runtime support |
| [`g2d-rs`](https://github.com/EdgeFirstAI/g2d-rs) | Rust API for NXP G2D 2D graphics acceleration |
| [`kernel-module-uiodma`](https://github.com/EdgeFirstAI/kernel-module-uiodma) | Linux user-space DMA driver for direct hardware buffer access |
| [`ara2-rs`](https://github.com/EdgeFirstAI/ara2-rs) | Rust library for the Kinara Ara-2 neural accelerator |

### Cross-Platform Libraries

| Repository | Description |
|-----------|-------------|
| [`gbm.rs`](https://github.com/EdgeFirstAI/gbm.rs) | Rust bindings for libgbm (Generic Buffer Manager) for DMA buffer allocation |
| [`bno08x-rs`](https://github.com/EdgeFirstAI/bno08x-rs) | Rust driver for the BNO08x IMU sensor family |

### Platform & Build

| Repository | Description |
|-----------|-------------|
| [`yocto`](https://github.com/EdgeFirstAI/yocto) | Yocto manifests for complete EdgeFirst platform builds |
| [`meta-edgefirst`](https://github.com/EdgeFirstAI/meta-edgefirst) | Yocto recipes for building EdgeFirst Perception on embedded Linux |
| [`meta-kinara`](https://github.com/EdgeFirstAI/meta-kinara) | Yocto enablement layer for the Kinara Ara-2 neural accelerator |

## Design Principles

- **Platform awareness** — Foundation libraries know the hardware they run on and select optimal code paths automatically
- **Buffer ownership semantics** — Clear DMA buffer lifecycle management prevents leaks and enables safe zero-copy sharing across components
- **Minimal dependencies** — Each library is focused and self-contained, suitable for deeply embedded environments
- **C and Rust APIs** — Core interfaces are available in both C (for system integration) and Rust (for safe, high-performance application development)

## Supported Hardware

EdgeFirst Foundation currently supports:

- **NXP i.MX family** — SoCs with Vivante NPUs (i.MX 8M Plus, i.MX 93, i.MX 95) with DMA buffer and CameraAdaptor runtime acceleration
- **NVIDIA Jetson** — Jetson family with CUDA and TensorRT acceleration
- **Raspberry Pi 5** — Including Hailo-8 and Hailo-8L AI HAT accelerators
- **Kinara Ara-2** — High-performance neural accelerator for edge inference

The architecture is designed for portability across embedded Linux platforms. Contact [Au-Zone Technologies](https://www.au-zone.com) for information on additional platform support.

## EdgeFirst Studio Integration

Foundation libraries power the full perception development lifecycle with [EdgeFirst Studio](https://edgefirst.studio). Models trained in Studio — using CameraAdaptor for native sensor format support — are deployed to edge devices via the [`client`](https://github.com/EdgeFirstAI/client) CLI, where `edgefirst-tflite` executes them with DMA buffer passthrough and NPU acceleration. Studio's free tier supports individual projects.

## Additional Resources

| Resource | Description |
|----------|-------------|
| [Documentation](https://doc.edgefirst.ai/latest/) | EdgeFirst Studio and Perception documentation |
| [`client`](https://github.com/EdgeFirstAI/client) | EdgeFirst Studio CLI client for dataset management and model deployment |

---

[Back to Overview](README.md) · [Zenoh](zenoh.md) · [GStreamer](gstreamer.md) · [ROS 2](ros2.md) · [Documentation](https://doc.edgefirst.ai/latest/)
