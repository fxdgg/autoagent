#include <random>

#include <cuda_runtime.h>

#include "saformat17.h"

namespace cufftdx_dct3d 
{
    bool is_size_supported(unsigned int nx, unsigned int ny, unsigned int nz);

    void launch_fused_dct3d(
        const float* input, float* output,
        unsigned int nx, unsigned int ny, unsigned int nz,
        size_t input_offset, size_t output_offset,
        cudaStream_t stream
    );

    void launch_fused_idct3d(
        const float* input, float* output,
        unsigned int nx, unsigned int ny, unsigned int nz,
        size_t input_offset, size_t output_offset,
        cudaStream_t stream
    );
}

struct CUDAStream
{
    cudaStream_t stream;

    CUDAStream()
    {
        cudaStreamCreate(&stream);
    }

    ~CUDAStream()
    {
        cudaStreamDestroy(stream);
    }

    void Synchronize()
    {
        cudaStreamSynchronize(stream);
    }
};

CUDAStream defaultStream;

// 3D DCT Helper
static void DCT3D(float* data, int Nx, int Ny, int Nz, bool inverse)
{
    if (inverse)
    {
        cufftdx_dct3d::launch_fused_idct3d(data, data, Nx, Ny, Nz, 0, 0, defaultStream.stream);
    }
    else 
    {
        cufftdx_dct3d::launch_fused_dct3d(data, data, Nx, Ny, Nz, 0, 0, defaultStream.stream);
    }
}

float CalError(const std::vector<float>& orig, const std::vector<float>& data)
{
    float error = 0;
    for (size_t i = 0; i < orig.size(); ++i) 
    {
        error += std::fabsf(orig[i] - data[i]);
    }
    return error / orig.size();
}

int main()
{
    uint32_t testX = 64, testY = 64, testZ = 64;
    std::vector<float> dataIn(testX * testY * testZ, 0.0f);
    std::vector<float> dataOut(testX * testY * testZ, 0.0f);
    float* dctBuffer;
    cudaMalloc(&dctBuffer, sizeof(float) * testX * testY * testZ);

    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_real_distribution<> dis(0.0f, 1.0f);

    int score = 0;
    for (int T = 0; T < 100; T++)
    {
        for (int z = 0; z < testZ; ++z) {
            for (int y = 0; y < testY; ++y) {
                for (int x = 0; x < testX; ++x) {
                    dataIn[x + y * testX + z * testX * testY] = dis(gen);   
                }
            }
        }

        cudaMemcpyAsync(dctBuffer, dataIn.data(), sizeof(float) * testX * testY * testZ, cudaMemcpyHostToDevice, defaultStream.stream);
        DCT3D(dctBuffer, testX, testY, testZ, false);
        DCT3D(dctBuffer, testX, testY, testZ, true);
        cudaMemcpyAsync(dataOut.data(), dctBuffer, sizeof(float) * testX * testY * testZ, cudaMemcpyDeviceToHost, defaultStream.stream);
        
        if (CalError(dataIn, dataOut) < 1e-5f)
            score++;
    }

    safmt::println("Score: {}/100", score);
    std::cout.flush();

    cudaFree(dctBuffer);
    return 0;
}