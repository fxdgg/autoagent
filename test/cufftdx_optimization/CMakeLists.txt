cmake_minimum_required(VERSION 3.12)

project(cufftdx_optimization)

set(CMAKE_CXX_STANDARD 17)

set(THIRD_PARTY_DIR "D:/silasshen/DawnAcousticsBaker/DawnAcousticsBaker/ThirdParty")

set(CMAKE_CUDA_COMPILER "${THIRD_PARTY_DIR}/CUDA/v12.4/bin/nvcc.exe")
set(CUDAToolkit_DIR "${THIRD_PARTY_DIR}/CUDA/v12.4")
find_package(CUDAToolkit REQUIRED)

add_executable(main main.cpp)

target_link_libraries(main PRIVATE CUDA::cufft CUDA::cudart CUDA::cuda_driver)

include(${CMAKE_CURRENT_SOURCE_DIR}/build_cufftdx.cmake)
add_cufftdx_dependency(main)