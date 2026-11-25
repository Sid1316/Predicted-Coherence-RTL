/* link.ld - linker script for programs on rv_soc_sim (docs/spec.md §2.3, §11, §12).
 *
 * RAM: 64 KiB at 0x8000_0000 (MEM_BASE, MEM_SIZE_BYTES), the reset vector at
 * its base. Section order: .text.init first (entry code of the directed
 * tests, both upstream test suites and crt0.S), then .text, .rodata, .data,
 * .bss and .tohost.
 *
 * .tohost is placed here but tohost/fromhost are NOT defined here: the
 * program defines them in assembly (spec §11, review item R-3).
 */

OUTPUT_ARCH("riscv")
ENTRY(_start)

MEMORY
{
  /* 64 KiB (spec §2.4 MEM_SIZE_BYTES). A larger simulator RAM is selected
     with -Wl,--defsym=__ram_size=<bytes>; RISCOF runs use 2 MiB. */
  RAM (rwx) : ORIGIN = 0x80000000, LENGTH = DEFINED(__ram_size) ? __ram_size : 64K
}

SECTIONS
{
  .text.init : { KEEP(*(.text.init)) } > RAM

  .text : { *(.text .text.*) } > RAM

  .rodata : ALIGN(4) { *(.rodata .rodata.* .srodata .srodata.*) } > RAM

  .data : ALIGN(4)
  {
    *(.data .data.*)
    /* gp-relative addressing reaches +-2 KiB around __global_pointer$. */
    __global_pointer$ = . + 0x800;
    *(.sdata .sdata.*)
  } > RAM

  .bss (NOLOAD) : ALIGN(4)
  {
    __bss_start = .;
    *(.sbss .sbss.*)
    *(.bss .bss.*)
    *(COMMON)
    . = ALIGN(4);
    __bss_end = .;
  } > RAM

  .tohost : ALIGN(64) { KEEP(*(.tohost)) } > RAM

  _end = .;

  /* Unwind tables and notes: not used by these freestanding programs. */
  /DISCARD/ : { *(.eh_frame .eh_frame_hdr .note .note.*) }

  /* Stack grows down from the end of RAM (16-byte aligned, ilp32 ABI). */
  _stack_top = ALIGN(ORIGIN(RAM) + LENGTH(RAM), 16);
  ASSERT(_end <= _stack_top - 0x400, "program leaves less than 1 KiB of RAM for the stack")
}
