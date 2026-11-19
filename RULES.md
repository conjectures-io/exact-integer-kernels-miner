# Exact integer kernels, season 1: rules

## The task

Write one C file with three functions:

```c
uint32_t eik_sigmoid(uint32_t x);   /* correctly rounded 1 / (1 + e^-x) */
uint32_t eik_tanh(uint32_t x);      /* correctly rounded tanh x */
uint32_t eik_exp(uint32_t x);       /* correctly rounded e^x */
```

- `x` and the result are IEEE-754 binary32 bit patterns.
- The result must be **the binary32 value nearest to the exact real result, ties to even**, for
  **every** one of the 2³² inputs.
- **Special values:**
  - A NaN is quieted, keeping its sign and payload.
  - σ(+∞) = 1, σ(−∞) = +0, σ(±0) = ½.
  - tanh(±∞) = ±1, tanh(±0) = ±0.
  - exp(+∞) = +∞, exp(−∞) = +0, exp(±0) = 1.
  - exp overflows to +∞ from x ≈ 88.7228 (word `0x42B17218`), gives subnormal results below
    x ≈ −87.3365, and rounds to +0 below x ≈ −103.9721.

**Use only integer arithmetic.** The targets have no FPU, and floating point is not allowed in the
source.

**Starting point:** [template/entry.c](template/entry.c). It is correct on every input as it stands:
each function tries a fast path and falls back to the incumbent, `exact-c`'s implementation, which is
correct everywhere and takes ~100–200k instructions per call. The incumbent alone is in
[examples/incumbent.c](examples/incumbent.c).

## What the file may contain

The build force-includes [harness/eik.h](harness/eik.h). It provides:
- the fixed-width integer types, `size_t` and `bool`;
- `memcpy`, `memset` and `memmove`;
- the three prototypes.

**Allowed:**
- C11.
- Integer types up to 64 bits.
- `static const` tables.
- Local variables and arrays.
- Loops and `goto`.
- `static` helper functions.
- Pointers to your own locals and tables.
- These builtins: `__builtin_clz`/`clzll`/`ctz`/`ctzll`/`popcount`/`expect`/`unreachable`.

**Rejected:**

| Rule | Why |
|---|---|
| Any directive except `#define`, `#undef`, `#if`, `#ifdef`, `#ifndef`, `#elif`, `#else`, `#endif`, in any spelling (`%:include`, a directive split by `\`-newline or around comments, `#include_next`, `#import`, `#embed`, `#pragma`, `#line`, …) | One prelude, no compiler control, no other files read |
| Trigraphs (`??=`, `??/`, …) | They are replaced before everything else and can hide directives |
| `_Pragma` (also when a macro assembles it), `__attribute__`, `[[…]]`, `asm`, `__has_include`, `__has_embed` | No compiler control, no probing of the file system |
| Code that depends on predefined macros (`__clang__`, `__riscv`, `__arm__`, `__x86_64__`, `__SANITIZE_ADDRESS__`, …) | Every build (each target, and the host's full check) must compile exactly the same tokens, or the full check would verify different code |
| Subtraction, shifts, division, remainder, comparisons, bitwise operators, `~` or `-` on a `sizeof` result or a pointer difference, or widening one to 64 bits | `sizeof` is 64-bit on the host and 32-bit on the targets, so these can give different answers. `+`, `*`, `sizeof a / sizeof a[0]` and storing into a 32-bit variable are fine; otherwise cast first: `(uint32_t)sizeof x` |
| Any floating-point type, literal or cast | Integer-only targets; floats could slip in via soft-float |
| File-scope or `static` variables that are not `const` | No state survives a call, so no caching of results |
| Non-`static` functions other than the three entry points | Only the entry points are exported |
| `volatile`, `_Atomic`, function pointers, indirect calls, pointer↔integer casts | Determinism and analysability |
| Plain `char`, `long` | Their signedness and width differ between the targets and the 64-bit host |
| Recursion | Bounded stack |
| Calls to anything but your own functions, the three memory functions and the builtins above | No hidden library code |

The object file for each target is also checked:
- It has no writable data.
- It references only integer compiler-rt helpers, such as `__aeabi_lmul` and `__muldi3`. Any
  soft-float helper fails the check.
- It exports only the three entry points.

## Builds

- **Targets:** pinned clang (the `ziglang` wheel), with these flags:

  ```
  -std=c11 -O2 -ffreestanding -fno-builtin -ftrivial-auto-var-init=zero -fno-unwind-tables
  ```

  for `riscv32` (RV32IM), `thumbv6m` (Cortex-M0+) and `thumbv7em` (Cortex-M4/M33).
- **Host check:** gcc with `-fsanitize=undefined,address`.

`-ftrivial-auto-var-init=zero` gives an uninitialised local the same value (zero) on every target.
Its cost is counted in your score, so initialise only what you need.

## Correctness: every input

1. **Scored inputs.** Every output the scorer sees must be right.
2. **Target sample.** 32,768 words, one from each equal slice of the 2³² inputs at a seeded offset,
   are run on each emulated target per function and compared with the reference.
3. **Full host check.** All 2³² inputs per function are run under UBSan and ASan, which abort on the
   first undefined behaviour. The outputs are compared with SHA-256 digests of the reference over
   1M-word chunks.

Step 3 runs for every entry that would take over a board. A single wrong output or a single
undefined behaviour on any input rejects the entry. A board-winning entry's object code is also run
on every input for each target, in QEMU.

**Why the host check stands for the targets:**
- The rules remove the usual sources of difference between 32-bit targets and the 64-bit host:
  `long`, `char`, `sizeof` arithmetic, uninitialised reads and pointer/integer casts.
- UBSan proves the absence of the remaining undefined behaviour on every input.
- What is left is the compilers' correctness. The target sample and the per-target check cover that.

**The reference.** The digests come from `exact-c` ([third_party/exact-c](third_party/exact-c)). An
independent implementation on GNU MPFR agrees with it on all 2³² inputs of every function.

## Score (lower is better)

There is one score per target board (`rv32im`, `thumbv6m`):

```
S = GM over {sigmoid, tanh, exp} of [ mean_typ^0.5 · mean_wide^0.3 · mean_hard^0.2 · (1 + max(0, p99.9_hard − 20·mean_typ)/10^6)^0.1 ]
    · (1 + code_and_table_bytes / 64 KiB)^0.25
```

- **The means** are retired instructions per call in the emulator, on inputs drawn fresh for each
  evaluation from a recorded seed:

  | Set | Count per function | Content |
  |---|---|---|
  | Typical | 2,000 | sigmoid, tanh: N(0, 3) and N(0, 1) pre-activations. exp: softmax's x − max, −\|N(0, 3)\| (80%), and N(0, 3) (20%) |
  | Wide | 1,000 | Uniform over exponents for \|x\| ∈ [2⁻³¹, 2⁸] |
  | Hard | 300 | Near-midpoint inputs (within 2⁻¹⁸ ulp of a rounding boundary), specials, each function's thresholds, subnormals |

- **The tail term** stops an entry from sending whole regions to a slow fallback.
- **The size term** charges for code and tables.
- **`overall` board:** √(S_rv32im · S_thumbv6m).
- **`thumbv7em`:** measured and reported, not scored.

**Takeover:**
- On each board, an entry needs **S ≤ 0.97 × the champion's S, measured on the same fresh inputs**,
  then a clean full check.
- The metric has no noise. The same file with the same seed always gives the same counts, and the
  champion is re-measured with the challenger's seed.

**Caps:**
- 64 KiB of code plus tables per target.
- 8 KiB peak stack.
- 20M instructions per call.
- 256 KB of source.

**Duplicates:** an entry whose preprocessed source matches an accepted entry is rejected. The
comparison ignores whitespace, comments, macro wrappers and the names of everything the entry
declares, so a renamed copy is still a copy.

## Submitting

One submission is one file, `entry.c` (at most 256 KB, UTF-8). Each subnet registration buys one
submission, and a rejected entry still uses it, so check first:

```bash
python -m eik check entry.c                     # static rules and builds (seconds)
python -m eik evaluate entry.c --quick          # score against the incumbent, 3% of inputs checked
python -m eik fullcheck entry.c --function tanh # every input of one function
python miner/submit.py submit entry.c --hotkey ~/.bittensor/wallets/W/hotkeys/H
```

The upload is signed by your hotkey over the competition slug `exact-integer-kernels`, the file's
SHA-256 and a timestamp. The validator runs the same checks and scoring as `eik evaluate`, on a seed
you cannot know in advance.

## Licence

Submitting grants the code under MIT or Apache-2.0 (at the recipient's option), so that winners can
ship in `exact-c`.
