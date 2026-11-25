# Silent width and instantiation traps

Two RTL bugs that pass every sim and waste days on the bench: a width operation
that quietly does nothing, and a whole block that was never built.

## zeroExtend then signExtend is a silent no-op
`raw.zeroExtend(width).signExtend(width)` does NOT sign-extend. The `zeroExtend`
widens the value to full width first, so the later `signExtend` sees a value that
already fills the width and has nothing to extend. Every negative field then reads
as its zero-extended value. A store offset of -4 becomes base + 0xFFC.

Sign-extend the RAW narrow field directly, before any widening:
`rawOffset.signExtend(width)`. The order is the bug. Extend from the real sign bit,
not from a value you already zero-filled.

This class hides in test data. If every store in the suite uses offset 0, the
sign-extend path is never exercised and the bug ships. Test with non-zero,
non-default operands to reach it. See `hdl-module-design` on operand coverage.

## Verify the block is even instantiated before debugging its internals
A whole feature can be gated off by a default parameter the generator never
passes. The block then emits as dead wires, and days of "the timing is wrong"
chase a path that was never built. One write-leveling block never built because
the generator call omitted `writeLevel:`, so it defaulted to false and the entire
sub-block was absent from the netlist.

Before you debug a block's internals, confirm the block EXISTS in the emitted
design. Grep the generated SystemVerilog for the module name or a known port. If
the port is not there, the bug is the missing instantiation, not the logic.

## Size a sentinel or override field for the VALUE, not the count
A field that must carry a sentinel or an override value larger than the normal range
silently falls back when it is sized for the count instead of the value. An override
declared `4*laneCount` wide (4 bits for a one-lane x8 part) rejected an 8-bit
register value, and a lane index sized `(dataBits-1).bitLength` (3 bits for x8) made
the DQS sentinel value 8 unreachable, so the IDELAY `VAR_LOAD` quietly fell back to
`FIXED`. When a value must exceed the normal range, size the field for that value,
not for how many lanes or entries there are, or the fallback path hides the bug.

## The sum of two in-range values needs one more bit
Eye-center arithmetic `(passLo + passHi) / 2` computed in 5 bits overflowed:
`12 + 20 = 32` wrapped to 0 before the divide. `zeroExtend` the operands to one
extra bit before the add. Any sum of two full-range values needs one more bit than
the operands, even when the final result fits.

## Confirm you actually regenerated (path-dependency codegen caches)
The instantiation trap above has a sibling: you fixed the generator but ran stale
RTL. A Dart generator caches a compiled snapshot (`.dart_tool/pub/bin/.../*.snapshot`)
and editing a path-dependency package (harbor under river) does not reliably
invalidate it. Delete the snapshot before you regenerate whenever the dependency
changed. Distrust the codegen cache and force-clear it, then grep the emitted
SystemVerilog to confirm the fix is really in the netlist.

## Verify a debug register decodes what you think on the ACTIVE config
Read-back muxes differ between build modes. A diagnostic register can return a
DIFFERENT field on a trainable build than on the base build. One read for a
capture value returned a delay register instead on the trainable path, so every
conclusion drawn from it was invalid. Confirm the debug register decodes the field
you assume on the EXACT config you are running before you trust its readback.
