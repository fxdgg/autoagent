#include "cufftdx_dct3d.cuh"

#include <cufftdx.hpp>
#include <cuda_runtime.h>
#include <cassert>

namespace cufftdx_dct3d 
{
    template<unsigned int N>
    using FFT_fwd = decltype(
        cufftdx::Size<N>() +
        cufftdx::Type<cufftdx::fft_type::c2c>() +
        cufftdx::Direction<cufftdx::fft_direction::forward>() +
        cufftdx::Precision<float>() +
        cufftdx::SM<750>() +
        cufftdx::Block()
    );

    template<unsigned int N>
    using FFT_inv = decltype(
        cufftdx::Size<N>() +
        cufftdx::Type<cufftdx::fft_type::c2c>() +
        cufftdx::Direction<cufftdx::fft_direction::inverse>() +
        cufftdx::Precision<float>() +
        cufftdx::SM<750>() +
        cufftdx::Block()
    );

    template<unsigned int N, unsigned int AXIS>
    static void launch_dct_axis(
        const float* input, float* output,
        unsigned int nx, unsigned int ny, unsigned int nz,
        size_t input_offset, size_t output_offset,
        cudaStream_t stream)
    {
        using FFT = FFT_fwd<N>;
        
        unsigned int slice_count;
        if constexpr (AXIS == 0) slice_count = ny * nz;
        else if constexpr (AXIS == 1) slice_count = nx * nz;
        else slice_count = nx * ny;
        
        const unsigned int block_size = FFT::max_threads_per_block;
        const unsigned int shared_mem = FFT::shared_memory_size;
        
        fused_dct_axis_kernel<FFT, AXIS><<<slice_count, block_size, shared_mem, stream>>>(
            input, output, nx, ny, nz, input_offset, output_offset);
    }

    template<unsigned int N, unsigned int AXIS>
    static void launch_idct_axis(
        const float* input, float* output,
        unsigned int nx, unsigned int ny, unsigned int nz,
        size_t input_offset, size_t output_offset,
        cudaStream_t stream)
    {
        using FFT = FFT_inv<N>;
        
        unsigned int slice_count;
        if constexpr (AXIS == 0) slice_count = ny * nz;
        else if constexpr (AXIS == 1) slice_count = nx * nz;
        else slice_count = nx * ny;
        
        const unsigned int block_size = FFT::max_threads_per_block;
        const unsigned int shared_mem = FFT::shared_memory_size;
        
        fused_idct_axis_kernel<FFT, AXIS><<<slice_count, block_size, shared_mem, stream>>>(
            input, output, nx, ny, nz, input_offset, output_offset);
    }

    #define DISPATCH_DCT_AXIS(AXIS, N_val, input, output, nx, ny, nz, in_off, out_off, stream) \
        switch (N_val) { \
            /* Note: comment them out to speed up compilation time. */ \
            /* case 2: launch_dct_axis<2, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 3: launch_dct_axis<3, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 4: launch_dct_axis<4, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 5: launch_dct_axis<5, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 6: launch_dct_axis<6, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 7: launch_dct_axis<7, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 8: launch_dct_axis<8, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 9: launch_dct_axis<9, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 10: launch_dct_axis<10, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 11: launch_dct_axis<11, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 12: launch_dct_axis<12, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 13: launch_dct_axis<13, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 14: launch_dct_axis<14, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 15: launch_dct_axis<15, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 16: launch_dct_axis<16, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 17: launch_dct_axis<17, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 18: launch_dct_axis<18, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 19: launch_dct_axis<19, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 20: launch_dct_axis<20, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 21: launch_dct_axis<21, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 22: launch_dct_axis<22, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 23: launch_dct_axis<23, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 24: launch_dct_axis<24, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 25: launch_dct_axis<25, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 26: launch_dct_axis<26, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 27: launch_dct_axis<27, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 28: launch_dct_axis<28, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 29: launch_dct_axis<29, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 30: launch_dct_axis<30, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 31: launch_dct_axis<31, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 32: launch_dct_axis<32, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 33: launch_dct_axis<33, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 34: launch_dct_axis<34, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 35: launch_dct_axis<35, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 36: launch_dct_axis<36, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 37: launch_dct_axis<37, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 38: launch_dct_axis<38, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 39: launch_dct_axis<39, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 40: launch_dct_axis<40, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 41: launch_dct_axis<41, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 42: launch_dct_axis<42, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 43: launch_dct_axis<43, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 44: launch_dct_axis<44, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 45: launch_dct_axis<45, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 46: launch_dct_axis<46, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 47: launch_dct_axis<47, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 48: launch_dct_axis<48, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 49: launch_dct_axis<49, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 50: launch_dct_axis<50, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 51: launch_dct_axis<51, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 52: launch_dct_axis<52, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 53: launch_dct_axis<53, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 54: launch_dct_axis<54, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 55: launch_dct_axis<55, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 56: launch_dct_axis<56, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 57: launch_dct_axis<57, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 58: launch_dct_axis<58, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 59: launch_dct_axis<59, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 60: launch_dct_axis<60, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 61: launch_dct_axis<61, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 62: launch_dct_axis<62, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 63: launch_dct_axis<63, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; */ \
            case 64: launch_dct_axis<64, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            default: \
                assert(false && "Unsupported FFT size for cuFFTDx DCT."); \
                break; \
        } \

    #define DISPATCH_IDCT_AXIS(AXIS, N_val, input, output, nx, ny, nz, in_off, out_off, stream) \
        switch (N_val) { \
            /* Note: comment them out to speed up compilation time. */ \
            /* case 2: launch_idct_axis<2, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 3: launch_idct_axis<3, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 4: launch_idct_axis<4, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 5: launch_idct_axis<5, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 6: launch_idct_axis<6, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 7: launch_idct_axis<7, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 8: launch_idct_axis<8, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 9: launch_idct_axis<9, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 10: launch_idct_axis<10, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 11: launch_idct_axis<11, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 12: launch_idct_axis<12, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 13: launch_idct_axis<13, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 14: launch_idct_axis<14, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 15: launch_idct_axis<15, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 16: launch_idct_axis<16, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 17: launch_idct_axis<17, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 18: launch_idct_axis<18, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 19: launch_idct_axis<19, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 20: launch_idct_axis<20, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 21: launch_idct_axis<21, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 22: launch_idct_axis<22, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 23: launch_idct_axis<23, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 24: launch_idct_axis<24, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 25: launch_idct_axis<25, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 26: launch_idct_axis<26, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 27: launch_idct_axis<27, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 28: launch_idct_axis<28, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 29: launch_idct_axis<29, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 30: launch_idct_axis<30, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 31: launch_idct_axis<31, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 32: launch_idct_axis<32, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 33: launch_idct_axis<33, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 34: launch_idct_axis<34, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 35: launch_idct_axis<35, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 36: launch_idct_axis<36, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 37: launch_idct_axis<37, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 38: launch_idct_axis<38, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 39: launch_idct_axis<39, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 40: launch_idct_axis<40, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 41: launch_idct_axis<41, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 42: launch_idct_axis<42, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 43: launch_idct_axis<43, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 44: launch_idct_axis<44, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 45: launch_idct_axis<45, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 46: launch_idct_axis<46, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 47: launch_idct_axis<47, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 48: launch_idct_axis<48, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 49: launch_idct_axis<49, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 50: launch_idct_axis<50, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 51: launch_idct_axis<51, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 52: launch_idct_axis<52, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 53: launch_idct_axis<53, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 54: launch_idct_axis<54, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 55: launch_idct_axis<55, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 56: launch_idct_axis<56, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 57: launch_idct_axis<57, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 58: launch_idct_axis<58, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 59: launch_idct_axis<59, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 60: launch_idct_axis<60, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 61: launch_idct_axis<61, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 62: launch_idct_axis<62, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            case 63: launch_idct_axis<63, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; */ \
            case 64: launch_idct_axis<64, AXIS>(input, output, nx, ny, nz, in_off, out_off, stream); break; \
            default: \
                assert(false && "Unsupported FFT size for cuFFTDx IDCT."); \
                break; \
        } \

    bool is_single_size_supported(unsigned int n)
    {
        return n == 64;
        // return n >= 1 && n <= 64;
    }

    bool is_size_supported(unsigned int nx, unsigned int ny, unsigned int nz)
    {
        return is_single_size_supported(nx)
            && is_single_size_supported(ny)
            && is_single_size_supported(nz);
    }

    // cufftdx call entry
    void launch_fused_dct3d(
        const float* input, float* output,
        unsigned int nx, unsigned int ny, unsigned int nz,
        size_t input_offset, size_t output_offset,
        cudaStream_t stream)
    {
        // For n=1: DCT-II of a single element is the identity transform.
        // Skip the axis entirely.
        
        // The first axis that actually executes reads from `input` and writes to
        // `output`. Subsequent axes work in-place on `output`. If we skip the
        // first axis (Z) we must still feed `input` to the next non-skipped axis.
        // Track this with `cur_in` / `cur_in_offset`.
        const float* cur_in  = input;
        size_t cur_in_offset = input_offset;

        // X axis
        if (nx > 1) {
            DISPATCH_DCT_AXIS(0, nx, cur_in, output, nx, ny, nz, cur_in_offset, output_offset, stream);
            cur_in        = output;
            cur_in_offset = output_offset;
        }
        
        // Y axis
        if (ny > 1) {
            DISPATCH_DCT_AXIS(1, ny, cur_in, output, nx, ny, nz, cur_in_offset, output_offset, stream);
            cur_in        = output;
            cur_in_offset = output_offset;
        }
        
        // Z axis
        if (nz > 1) {
            DISPATCH_DCT_AXIS(2, nz, cur_in, output, nx, ny, nz, cur_in_offset, output_offset, stream);
            cur_in        = output;
            cur_in_offset = output_offset;
        }

        // If all axes were skipped (degenerate 1x1x1 case), copy input to output.
        if (cur_in == input && input != output) {
            cudaMemcpyAsync(
                output + output_offset,
                input + input_offset,
                sizeof(float) * nx * ny * nz,
                cudaMemcpyDeviceToDevice,
                stream);
        }
    }

    void launch_fused_idct3d(
        const float* input, float* output,
        unsigned int nx, unsigned int ny, unsigned int nz,
        size_t input_offset, size_t output_offset,
        cudaStream_t stream)
    {
        // For n=1: IDCT-II of a single element is the identity transform.
        // Skip the axis entirely.
        
        // The first axis that actually executes reads from `input` and writes to
        // `output`. Subsequent axes work in-place on `output`. If we skip the
        // first axis (Z) we must still feed `input` to the next non-skipped axis.
        // Track this with `cur_in` / `cur_in_offset`.
        const float* cur_in  = input;
        size_t cur_in_offset = input_offset;

        // Z axis
        if (nz > 1) {
            DISPATCH_IDCT_AXIS(2, nz, cur_in, output, nx, ny, nz, cur_in_offset, output_offset, stream);
            cur_in        = output;
            cur_in_offset = output_offset;
        }
        
        // Y axis
        if (ny > 1) {
            DISPATCH_IDCT_AXIS(1, ny, cur_in, output, nx, ny, nz, cur_in_offset, output_offset, stream);
            cur_in        = output;
            cur_in_offset = output_offset;
        }
        
        // X axis
        if (nx > 1) {
            DISPATCH_IDCT_AXIS(0, nx, cur_in, output, nx, ny, nz, cur_in_offset, output_offset, stream);
            cur_in        = output;
            cur_in_offset = output_offset;
        }

        // If all axes were skipped (degenerate 1x1x1 case), copy input to output.
        if (cur_in == input && input != output) {
            cudaMemcpyAsync(
                output + output_offset,
                input + input_offset,
                sizeof(float) * nx * ny * nz,
                cudaMemcpyDeviceToDevice,
                stream);
        }
    }

    void launch_fused_dct_axis(unsigned int axis,
        const float* input, float* output,
        unsigned int nx, unsigned int ny, unsigned int nz,
        size_t input_offset, size_t output_offset,
        cudaStream_t stream)
    {
        unsigned int n;
        switch (axis) {
            case 0: n = nx; break;
            case 1: n = ny; break;
            case 2: n = nz; break;
            default: assert(false && "Invalid axis"); return;
        }

        if (n <= 1) 
            return; 

        switch (axis) {
            case 0: DISPATCH_DCT_AXIS(0, n, input, output, nx, ny, nz, input_offset, output_offset, stream); break;
            case 1: DISPATCH_DCT_AXIS(1, n, input, output, nx, ny, nz, input_offset, output_offset, stream); break;
            case 2: DISPATCH_DCT_AXIS(2, n, input, output, nx, ny, nz, input_offset, output_offset, stream); break;
        }
    }

    void launch_fused_idct_axis(unsigned int axis,
        const float* input, float* output,
        unsigned int nx, unsigned int ny, unsigned int nz,
        size_t input_offset, size_t output_offset,
        cudaStream_t stream)
    {
        unsigned int n;
        switch (axis) {
            case 0: n = nx; break;
            case 1: n = ny; break;
            case 2: n = nz; break;
            default: assert(false && "Invalid axis"); return;
        }

        if (n <= 1) 
            return; 

        switch (axis) {
            case 0: DISPATCH_IDCT_AXIS(0, n, input, output, nx, ny, nz, input_offset, output_offset, stream); break;
            case 1: DISPATCH_IDCT_AXIS(1, n, input, output, nx, ny, nz, input_offset, output_offset, stream); break;
            case 2: DISPATCH_IDCT_AXIS(2, n, input, output, nx, ny, nz, input_offset, output_offset, stream); break;
        }
    }

    #undef DISPATCH_DCT_AXIS
    #undef DISPATCH_IDCT_AXIS

} // namespace cufftdx_dct3d