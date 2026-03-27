set(CUFFTDX_DIR "${THIRD_PARTY_DIR}/cufftdx/25.12")

set(CUFFTDX_CU_SOURCE
    ${CMAKE_CURRENT_SOURCE_DIR}/cufftdx_dct3d_dispatch.cu
)

set(CUFFTDX_CU_HEADER
    ${CMAKE_CURRENT_SOURCE_DIR}/cufftdx_dct3d.cuh
)

set(CUFFTDX_CU_OBJ
    ${CMAKE_CURRENT_BINARY_DIR}/cufftdx_dct3d_dispatch_$<CONFIG>.obj
)

set(CUFFTDX_NVCC_INCLUDE_DIRS
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CUFFTDX_DIR}/include
    ${CUFFTDX_DIR}/external/cutlass/include
    ${THIRD_PARTY_DIR}/CUDA/v12.4/include
)

# Build per-directory -I"path" arguments as a list so each is a separate
# command-line token (avoids the string-concat bug where all paths end up
# in a single argument that confuses cl.exe behind nvcc).
set(CUFFTDX_NVCC_INCLUDE_FLAGS "")
foreach(_inc_dir IN LISTS CUFFTDX_NVCC_INCLUDE_DIRS)
    list(APPEND CUFFTDX_NVCC_INCLUDE_FLAGS "-I${_inc_dir}")
endforeach()

# Match the MSVC runtime library (/MDd for Debug, /MD for Release) so that
# the .obj produced by nvcc links against the same CRT as the main target.
set(CUFFTDX_MSVC_RUNTIME "$<IF:$<CONFIG:Debug>,/MDd,/MD>")

# Match _ITERATOR_DEBUG_LEVEL: 2 for Debug (MSVC default), 0 for Release
set(CUFFTDX_ITERATOR_DBG_LEVEL "$<IF:$<CONFIG:Debug>,2,0>")

# Compile the .cu file with the embedded nvcc to avoid version mismatch
# from enable_language(CUDA) which picks the system CUDA installation.
add_custom_command(
    OUTPUT ${CUFFTDX_CU_OBJ}
    COMMAND ${CMAKE_CUDA_COMPILER}
        -arch=sm_75
        -std=c++17
        -Xcompiler "/std:c++17 /Zc:__cplusplus ${CUFFTDX_MSVC_RUNTIME}"
        -D_ITERATOR_DEBUG_LEVEL=${CUFFTDX_ITERATOR_DBG_LEVEL}
        ${CUFFTDX_NVCC_INCLUDE_FLAGS}
        -c ${CUFFTDX_CU_SOURCE}
        -o ${CUFFTDX_CU_OBJ}
    DEPENDS ${CUFFTDX_CU_SOURCE} ${CUFFTDX_CU_HEADER}
    COMMENT "${CMAKE_CUDA_COMPILER} -arch=sm_75 -std=c++17 -Xcompiler \"/std:c++17 /Zc:__cplusplus ${CUFFTDX_MSVC_RUNTIME}\" ${CUFFTDX_NVCC_INCLUDE_FLAGS} -c ${CUFFTDX_CU_SOURCE} -o ${CUFFTDX_CU_OBJ}"
    VERBATIM
)
add_custom_target(CuFFTDxKernels DEPENDS ${CUFFTDX_CU_OBJ})

function(add_cufftdx_dependency _target)

    add_dependencies(${_target} CuFFTDxKernels)

    # Link the compiled .obj and CUDA device runtime libraries
    target_link_libraries(${_target} PRIVATE
        ${CUFFTDX_CU_OBJ}
        ${THIRD_PARTY_DIR}/CUDA/v12.4/lib/x64/cudadevrt.lib
    )

    target_include_directories(${_target} PRIVATE
        ${CUFFTDX_DIR}/include
    )

endfunction()