# Boot-handoff traps (the FSBL and flash-XIP failures)

Concrete first-stage boot failures from real RISC-V bring-up. Each one is silent:
no output, or a stale image that ignores your rebuilds. Rule them out before you
debug the firmware logic.

## Reset-into-flash XIP is not fetchable at cold reset
A core that resets straight to the SPI-NOR XIP window is silent at cold reset,
because the flash and its config path (STARTUPE2, CCLK) is not up on the first
fetch cycle. Prove the CPU never reached your code: place a STACKLESS, register-
only UART marker as the literal first instruction. If it stays silent, the fetch
never happened. The fix is a small BRAM maskrom that runs first. Its warm-up reads
spin up the flash XIP path, then it jumps to the FSBL in flash.

## A stale image at the real boot slot runs while your rebuilds never execute
If the boot ROM jumps to the flash base (QSPI 0x0) but you flash your rebuilt FSBL
to a different offset (0x100000), the STALE image at 0x0 runs forever and your
rebuilds never execute. The fix looks like it did nothing. Confirm the EXACT
reset and jump slot from the generator, and flash there. When a change has no
effect, verify the image you flashed is the one that runs before you touch the
code again.

## A quad or QE flash mismatch boots garbage
A quad-read flash config keyed to one vendor's QE bit returns garbage on a
different vendor's part, which gives a totally silent boot. Fall back to the
standard single-lane 0x03 read, which works on any SPI part, to isolate flash-
config from everything else. If 0x03 boots, the fault is the quad/QE setup, not
the boot chain.

## FSBL scratch can collide with the destination it copies main into
Linking the FSBL's writable scratch (.data, .bss, stack) at the same DRAM base it
copies the main firmware to causes self-corruption. The copy overwrites the FSBL's
own live stack and console struct mid-copy, so it hangs before any UART, and it
looks like a DRAM fault. Place the FSBL scratch at the TOP of DRAM
(`ram_base + ram_size - region`) for full separation from the copy destination.

## Device-tree cell-size mismatch between parsers breaks memory discovery
Two hand-rolled device-tree parsers can disagree on `#address-cells` and
`#size-cells`. One hardcodes 1/1 (u32), another hardcodes 2/2 (read big-endian
64). No single DTB satisfies both: a 1-cell DTB read as 2 cells makes
`ram_base = 0x8000000008000000`, and a 2-cell reg read as 1 cell finds no usable
memory and halts. Honor the DECLARED cells (capture the root's once, and do not
let a nested node override them), and route all DT access through one cell-aware
library, not per-file parsers. Emit 2/2 for RV64. See `soc-integration` for
keeping the emitted DTB and the RTL from drifting.

## Do not assume optional CSRs or extensions exist on the target
Firmware tuned for QEMU-virt unconditionally writes optional CSRs (PMP,
mcounteren, menvcfg) and uses optional extensions (Sstc `stimecmp`), then traps on
a minimal core that lacks them. Probe each CSR under a temporary trap handler and
skip the absent ones, then fall back. For a timer with no Sstc, relay CLINT
mtimecmp with MTIE instead of writing `stimecmp`. This portable probe is what
matches real silicon, not a build flag. See `bare-metal-bringup` for the CSR probe
and trap-handler pattern.
