# ROHD: net_connect inout, BridgeModule wiring, and the per-test sim slowdown

Three ROHD/rohd_bridge gotchas that cost real debug time on an ECP5 SoC.

## 1. `net_connect` duplicate-port form breaks yosys synthesis

ROHD emits a helper module for inter-module bidirectional (`inOut`) nets:

```systemverilog
module net_connect #(parameter int WIDTH=1) (w, w);   // DUPLICATE port name
inout wire[WIDTH-1:0] w;
endmodule
```

yosys (`read_verilog -sv`) **rejects this**: `ERROR: Duplicate module port 'w'`.
It is emitted whenever an `inOut` subset/bit crosses a module boundary (e.g. a
quad-SPI `spi_io[1]` status read, a DDR `DQ` bit, a USB `D+/D-` pad routed up
through a wrapper). A design with no top-level inout never hits it; the first one
that does fails synth.

**Fix (synthesis form):** rewrite the generated `net_connect.sv` to two NAMED
ports with a bidirectional assign; yosys parses it and `tribuf`/`opt` resolve the
tristate nets:

```systemverilog
module net_connect #(parameter int WIDTH=1) (w0, w1);
  inout wire [WIDTH-1:0] w0;
  inout wire [WIDTH-1:0] w1;
  assign w0 = w1;
  assign w1 = w0;
endmodule
```

The ROHD positional instantiation `net_connect nc (a, b)` maps onto `(w0, w1)`
unchanged. This is a generated file, so patch it post-generation in the build
script, OR fix it permanently in the codegen (emit the synth form), OR avoid the
inter-module inout by doing the tristate at the top level directly (`assign pad =
oe ? out : 1'bz; assign in = pad;` with the submodule exposing separate
in/out/oe directional ports instead of an `inOut`).

## 2. BridgeModule sub-module port wiring: the cascade `<=` fails

`BridgeModule.createPort(name, PortDirection.input)` pre-connects the port's
`Logic` to a mergeable dummy via `gets()`, so a second `<=` throws "already
connected". The cascade idiom does NOT work:

```dart
sub..input('clk') <= myClk;   // throws: already connected
```

Correct idiom (connect the dummy source the port samples to your signal):

```dart
sub.input('clk').srcConnection! <= myClk;
```

This is the pattern real rohd_bridge code uses (e.g. power-domain wiring).

## 3. Per-test Simulator slowdown reads as a "hang"

Each ROHD `Wire` arms `Simulator.preTick`/`postTick` listeners and re-subscribes
on `Simulator.resetRequested`; that closure pins the wire in memory. So every
test that builds fresh modules and then hits a `tearDown` `Simulator.reset()`
permanently adds its wires' listeners to the live Simulator. Each later tick fans
out to ALL wires from ALL prior tests in the isolate, so per-tick time grows
test-by-test. A heavy module test that runs late can read as a HANG when it is
actually just crawling (measured: same sim 614 ms at test 1 -> 7.5 s by test 10
with build+reset each).

This is a SIM-INFRA artifact, not a logic bug. Mitigations:
- Split heavy module tests into separate FILES (each file is its own isolate;
  `dart test` parallelizes per-file, not within).
- Or share ONE built harness across scenarios in a group and reset the DUT's
  `reset` port between scenarios instead of rebuilding the module each test.
- Declare the heaviest groups FIRST so they run while the accumulated wire set is
  small.
Do not chase it as a DUT bug; confirm by running the "hung" test in isolation (it
passes fast).
