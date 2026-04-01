## Use __sincosf intrinsic to speed up twiddle factor computation

In cufftdx_dct3d.cuh, the fused_dct_axis_kernel and fused_idct_axis_kernel
compute twiddle factors using separate cosf() and sinf() calls. These can be
replaced with the __sincosf() intrinsic which computes both in a single
instruction, potentially halving the trig computation cost.

Look at the PostProcess functions in both DCT and IDCT kernels.

---

## Explore shared memory transpose for non-X axis operations

For AXIS=1 and AXIS=2, global memory access is strided, which hurts
coalescing. Consider using shared memory as a transpose buffer:
1. Load a tile of data coalesced from global memory into shared memory
2. Transpose in shared memory
3. Perform FFT on contiguous data
4. Transpose back and store coalesced

This could significantly improve memory throughput for the Y and Z axis passes.
