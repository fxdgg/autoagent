#pragma once

#include <cufftdx.hpp>
#include <cuda_runtime.h>

#ifndef M_PIf
#define M_PIf 3.14159265358979323846f
#endif

namespace cufftdx_dct3d 
{
    // =============================================================================
    // Utility: twiddle factor computation
    // =============================================================================
    __device__ __forceinline__ float2 twiddle_dct(unsigned int k, unsigned int N)
    {
        const float phase = -(M_PIf * k) / (2.0f * N);
        return make_float2(cosf(phase), sinf(phase));
    }

    __device__ __forceinline__ float2 twiddle_idct(unsigned int k, unsigned int N)
    {
        const float phase = (M_PIf * k) / (2.0f * N);
        return make_float2(cosf(phase), sinf(phase));
    }

    // =============================================================================
    // DCT-II via FFT (one axis, fused kernel)
    //
    // For each 1D slice along the target axis of length N:
    //   1. PreProcess: reorder input   x[k] = input[k<=N/2 ? 2k : 2(N-k)-1]
    //   2. FFT(x) -> X
    //   3. PostProcess: X[k] * exp(-j*pi*k/(2N)) -> real part -> output
    //
    // The kernel processes the entire 3D volume. Each thread block handles
    // one or more 1D slices using cuFFTDx's thread-level or block-level FFT.
    // =============================================================================

    // Template parameters:
    //   FFT   - cuFFTDx FFT descriptor type
    //   AXIS  - 0=X, 1=Y, 2=Z
    template<class FFT, unsigned int AXIS>
    __launch_bounds__(FFT::max_threads_per_block)
    __global__ void fused_dct_axis_kernel(
        const float* __restrict__ input,
        float*       __restrict__ output,
        unsigned int nx, unsigned int ny, unsigned int nz,
        size_t input_offset, size_t output_offset)
    {
        using complex_type = typename FFT::value_type;
        
        // Determine which 1D slice this block handles
        // For AXIS=0: slice indexed by (y, z), length = nx
        // For AXIS=1: slice indexed by (x, z), length = ny
        // For AXIS=2: slice indexed by (x, y), length = nz
        
        unsigned int N, slice_count, slice_idx;
        if constexpr (AXIS == 0) {
            N = nx;
            slice_count = ny * nz;
        } else if constexpr (AXIS == 1) {
            N = ny;
            slice_count = nx * nz;
        } else {
            N = nz;
            slice_count = nx * ny;
        }
        
        slice_idx = blockIdx.x;
        if (slice_idx >= slice_count) return;
        
        // Decode slice index into the two non-transform coordinates
        unsigned int coord_a, coord_b;
        if constexpr (AXIS == 0) {
            coord_a = slice_idx % ny;  // y
            coord_b = slice_idx / ny;  // z
        } else if constexpr (AXIS == 1) {
            coord_a = slice_idx % nx;  // x
            coord_b = slice_idx / nx;  // z
        } else {
            coord_a = slice_idx % nx;  // x
            coord_b = slice_idx / nx;  // y
        }
    
        // Shared memory for FFT
        extern __shared__ __align__(16) char shared_mem[];
        
        // Thread-data storage for cuFFTDx
        complex_type thread_data[FFT::storage_size];
        
        const unsigned int tid = threadIdx.x;
        const unsigned int stride = FFT::stride; // = blockDim.x for block-level FFT
        
        // Step 1: PreProcess - load and reorder input into thread_data
        // DCT-II reordering: y[k] = x[k <= (N-1)/2 ? 2k : 2(N-k)-1]
        for (unsigned int i = tid; i < N; i += stride)
        {
            unsigned int src_idx = (i <= ((N - 1) >> 1)) ? (i * 2) : (2 * (N - i) - 1);
            
            // Compute linear index in the 3D array
            unsigned int lin_src;
            if constexpr (AXIS == 0) {
                lin_src = src_idx + coord_a * nx + coord_b * nx * ny;
            } else if constexpr (AXIS == 1) {
                lin_src = coord_a + src_idx * nx + coord_b * nx * ny;
            } else {
                lin_src = coord_a + coord_b * nx + src_idx * nx * ny;
            }
            
            // Load as real, store in complex (imaginary = 0)
            unsigned int local_idx = i / stride; // which element this thread handles
            if (i % stride == tid) {
                thread_data[local_idx].x = input[lin_src + input_offset];
                thread_data[local_idx].y = 0.0f;
            }
        }
        
        __syncthreads();
        
        // Step 2: Execute FFT via cuFFTDx
        FFT().execute(thread_data, shared_mem);
        
        __syncthreads();
        
        // Step 3: PostProcess - apply twiddle factors and extract real part
        // DCT[k] = Re( X[k] * exp(-j*pi*k/(2N)) ) * norm_coeff
        const float norm = sqrtf(2.0f / static_cast<float>(N));
        const float norm0 = norm / sqrtf(2.0f);
        
        for (unsigned int i = tid; i < N; i += stride)
        {
            unsigned int local_idx = i / stride;
            if (i % stride == tid)
            {
                float2 tw = twiddle_dct(i, N);
                float real_part = thread_data[local_idx].x * tw.x 
                                - thread_data[local_idx].y * tw.y;
                float coeff = (i == 0) ? norm0 : norm;
                
                // Write to output
                unsigned int lin_dst;
                if constexpr (AXIS == 0) {
                    lin_dst = i + coord_a * nx + coord_b * nx * ny;
                } else if constexpr (AXIS == 1) {
                    lin_dst = coord_a + i * nx + coord_b * nx * ny;
                } else {
                    lin_dst = coord_a + coord_b * nx + i * nx * ny;
                }
                
                output[lin_dst + output_offset] = real_part * coeff;
            }
        }
    }

    // =============================================================================
    // IDCT-II via IFFT (one axis, fused kernel)
    //
    // For each 1D slice along the target axis of length N:
    //   1. PreProcess: construct complex input from DCT coefficients
    //      X[k].re = c[k]*cos(phase) + c[N-k]*sin(phase)
    //      X[k].im = c[k]*sin(phase) - c[N-k]*cos(phase)
    //      (for k in [0, N/2])
    //   2. IFFT(X) -> x
    //   3. PostProcess: un-reorder and normalize
    //      output[2k]       = x[k]        for k = 0..N/2-1
    //      output[2k+1]     = x[N-1-k]    for k = 0..N/2-1
    // =============================================================================

    template<class FFT, unsigned int AXIS>
    __launch_bounds__(FFT::max_threads_per_block)
    __global__ void fused_idct_axis_kernel(
        const float* __restrict__ input,
        float*       __restrict__ output,
        unsigned int nx, unsigned int ny, unsigned int nz,
        size_t input_offset, size_t output_offset)
    {
        using complex_type = typename FFT::value_type;
        
        unsigned int N, slice_count, slice_idx;
        if constexpr (AXIS == 0) {
            N = nx;
            slice_count = ny * nz;
        } else if constexpr (AXIS == 1) {
            N = ny;
            slice_count = nx * nz;
        } else {
            N = nz;
            slice_count = nx * ny;
        }
        
        slice_idx = blockIdx.x;
        if (slice_idx >= slice_count) return;
        
        unsigned int coord_a, coord_b;
        if constexpr (AXIS == 0) {
            coord_a = slice_idx % ny;
            coord_b = slice_idx / ny;
        } else if constexpr (AXIS == 1) {
            coord_a = slice_idx % nx;
            coord_b = slice_idx / nx;
        } else {
            coord_a = slice_idx % nx;
            coord_b = slice_idx / nx;
        }
        
        extern __shared__ __align__(16) char shared_mem[];
        complex_type thread_data[FFT::storage_size];
        
        const unsigned int tid = threadIdx.x;
        const unsigned int stride = FFT::stride;
        
        const float norm_coeff = sqrtf(static_cast<float>(N) / 2.0f);
        const float norm_coeff0 = norm_coeff * sqrtf(2.0f);
        
        // Step 1: PreProcess - build complex spectrum for IFFT
        // For each frequency k in [0, N):
        //   v0 = input[k], v1 = input[N-k] (with v1=0 for k=0)
        //   phase = pi*k / (2N)
        //   X[k] = (v0*cos + v1*sin, v0*sin - v1*cos) * norm
        for (unsigned int i = tid; i < N; i += stride)
        {
            unsigned int local_idx = i / stride;
            if (i % stride == tid)
            {
                unsigned int lin_k, lin_nk;
                unsigned int nk = (i == 0) ? 0 : (N - i);
                
                if constexpr (AXIS == 0) {
                    lin_k  = i  + coord_a * nx + coord_b * nx * ny;
                    lin_nk = nk + coord_a * nx + coord_b * nx * ny;
                } else if constexpr (AXIS == 1) {
                    lin_k  = coord_a + i  * nx + coord_b * nx * ny;
                    lin_nk = coord_a + nk * nx + coord_b * nx * ny;
                } else {
                    lin_k  = coord_a + coord_b * nx + i  * nx * ny;
                    lin_nk = coord_a + coord_b * nx + nk * nx * ny;
                }
                
                float v0 = input[lin_k + input_offset];
                float v1 = (i == 0) ? 0.0f : input[lin_nk + input_offset];
                
                float2 tw = twiddle_idct(i, N);
                float c = tw.x, s = tw.y;
                
                float scale = (i == 0) ? norm_coeff0 : norm_coeff;
                thread_data[local_idx].x = (v0 * c + v1 * s) * scale;
                thread_data[local_idx].y = (v0 * s - v1 * c) * scale;
            }
        }
        
        __syncthreads();
        
        // Step 2: Execute IFFT via cuFFTDx
        FFT().execute(thread_data, shared_mem);
        
        __syncthreads();
        
        // Step 3: PostProcess - un-reorder and normalize
        // IFFT output needs to be reordered: output[2k] = x[k], output[2(N-k)-1] = x[k]
        const float inv_N = 1.0f / static_cast<float>(N);
        
        for (unsigned int i = tid; i < N; i += stride)
        {
            unsigned int local_idx = i / stride;
            if (i % stride == tid)
            {
                float val = thread_data[local_idx].x * inv_N; // Take real part, IFFT normalization
                unsigned int dst_idx = (i <= ((N - 1) >> 1)) ? (i * 2) : (2 * (N - i) - 1);
                
                unsigned int lin_dst;
                if constexpr (AXIS == 0) {
                    lin_dst = dst_idx + coord_a * nx + coord_b * nx * ny;
                } else if constexpr (AXIS == 1) {
                    lin_dst = coord_a + dst_idx * nx + coord_b * nx * ny;
                } else {
                    lin_dst = coord_a + coord_b * nx + dst_idx * nx * ny;
                }
                
                output[lin_dst + output_offset] = val;
            }
        }
    }

    // =============================================================================
    // Host-callable launcher (templated on FFT size N)
    //
    // cuFFTDx requires the FFT size as a compile-time constant. We provide a
    // dispatch table for common room sizes found in Adaptive Rectangular Decomposition.
    // =============================================================================

    // Forward declarations for the dispatch functions
    // These are defined in the .cu compilation unit

    bool is_single_size_supported(unsigned int n);

    void launch_fused_dct3d(
        const float* input, float* output,
        unsigned int nx, unsigned int ny, unsigned int nz,
        size_t input_offset, size_t output_offset,
        cudaStream_t stream);

    void launch_fused_idct3d(
        const float* input, float* output,
        unsigned int nx, unsigned int ny, unsigned int nz,
        size_t input_offset, size_t output_offset,
        cudaStream_t stream);

    // Per-axis launch functions.
    // These launch a single fused cuFFTDx DCT/IDCT kernel on one axis only.
    // The data is expected to be in the standard XYZ memory layout
    // (i.e. x is the fastest-varying dimension).
    // @param axis  0=X, 1=Y, 2=Z
    void launch_fused_dct_axis(unsigned int axis,
        const float* input, float* output,
        unsigned int nx, unsigned int ny, unsigned int nz,
        size_t input_offset, size_t output_offset,
        cudaStream_t stream);

    void launch_fused_idct_axis(unsigned int axis,
        const float* input, float* output,
        unsigned int nx, unsigned int ny, unsigned int nz,
        size_t input_offset, size_t output_offset,
        cudaStream_t stream);

} // namespace cufftdx_dct3d