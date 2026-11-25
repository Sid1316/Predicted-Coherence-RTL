// dhry_main_renamed.c - dhrystone_main.c with its main renamed to dhry_main (exec.md M7.1).
// The rename is scoped to this file: a command-line -Dmain=... would also
// rename the "call main" in crt0.S. port.c holds the program's real main.
#define main dhry_main
#include "dhrystone_main.c"
