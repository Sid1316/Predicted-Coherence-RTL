// crt0.S - startup code for C programs (docs/spec.md §11, §12; exec.md M4.2).
//
// _start (in .text.init, at the reset vector):
//   1. zero x1-x31 (the register file has no reset, spec §2.2);
//   2. sp = _stack_top, gp = __global_pointer$ (both from link.ld);
//   3. zero .bss (__bss_start..__bss_end, word aligned by link.ld);
//   4. call main(0, 0);
//   5. exit(main's return value).
//
// exit(code): stores (code << 1) | 1 to tohost, so 0 passes and any other
// value fails with that code (spec §11); then ECALL, which stops the core if
// the harness has not already ended the run at the tohost store.
//
// tohost/fromhost are defined here, in .tohost, as riscv-tests does; link.ld
// only places the section (spec §11, R-3).

  .section .text.init, "ax", @progbits
  .globl _start
  .type  _start, @function
_start:
  li    x1, 0
  li    x2, 0
  li    x3, 0
  li    x4, 0
  li    x5, 0
  li    x6, 0
  li    x7, 0
  li    x8, 0
  li    x9, 0
  li    x10, 0
  li    x11, 0
  li    x12, 0
  li    x13, 0
  li    x14, 0
  li    x15, 0
  li    x16, 0
  li    x17, 0
  li    x18, 0
  li    x19, 0
  li    x20, 0
  li    x21, 0
  li    x22, 0
  li    x23, 0
  li    x24, 0
  li    x25, 0
  li    x26, 0
  li    x27, 0
  li    x28, 0
  li    x29, 0
  li    x30, 0
  li    x31, 0

  // gp must be loaded without relaxation: relaxed, "la gp" would itself be
  // turned into a gp-relative access before gp is set.
  .option push
  .option norelax
  la    gp, __global_pointer$
  .option pop
  la    sp, _stack_top

  la    t0, __bss_start
  la    t1, __bss_end
1:
  bgeu  t0, t1, 2f
  sw    zero, 0(t0)
  addi  t0, t0, 4
  j     1b
2:
  li    a0, 0                     // argc
  li    a1, 0                     // argv
  call  main
  tail  exit
  .size _start, . - _start

  .text
  .globl exit
  .type  exit, @function
exit:
  slli  a0, a0, 1
  ori   a0, a0, 1
  la    t0, tohost
  sw    a0, 0(t0)
  fence
1:
  ecall
  j     1b                        // never returns
  .size exit, . - exit

  .section .tohost, "aw", @progbits
  .align 6
  .globl tohost
tohost:
  .dword 0
  .align 6
  .globl fromhost
fromhost:
  .dword 0
