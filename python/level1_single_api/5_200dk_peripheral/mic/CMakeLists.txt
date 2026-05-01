# Copyright (c) Huawei Technologies Co., Ltd. 2020. All rights reserved.

# CMake lowest version requirement
cmake_minimum_required(VERSION 3.5.1)

project(ascend_mic_python)

# ---------------------------------------------------------------------------
# Require toolkit path environment variables (same convention as the rest of
# this repository)
# ---------------------------------------------------------------------------
if(NOT DEFINED ENV{INSTALL_DIR})
    message(FATAL_ERROR "INSTALL_DIR environment variable is not set. "
            "Set it to the Ascend toolkit root, e.g. "
            "/usr/local/Ascend/ascend-toolkit/latest")
endif()

if(NOT DEFINED ENV{THIRDPART_PATH})
    message(FATAL_ERROR "THIRDPART_PATH environment variable is not set.")
endif()

# ---------------------------------------------------------------------------
# Locate Python and pybind11
# ---------------------------------------------------------------------------
find_package(Python3 REQUIRED COMPONENTS Interpreter Development)

# Try to find pybind11 via cmake; fall back to python -m pybind11 --cmakedir
find_package(pybind11 QUIET)
if(NOT pybind11_FOUND)
    execute_process(
        COMMAND "${Python3_EXECUTABLE}" -m pybind11 --cmakedir
        OUTPUT_VARIABLE PYBIND11_CMAKE_DIR
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET
    )
    if(PYBIND11_CMAKE_DIR)
        list(APPEND CMAKE_PREFIX_PATH "${PYBIND11_CMAKE_DIR}")
        find_package(pybind11 REQUIRED)
    else()
        message(FATAL_ERROR
            "pybind11 not found. Install it with:  pip install pybind11")
    endif()
endif()

# ---------------------------------------------------------------------------
# Build the C++ extension module
# ---------------------------------------------------------------------------
pybind11_add_module(_ascend_mic_ext
    src/_ascend_mic_ext.cpp
)

target_compile_options(_ascend_mic_ext PRIVATE
    -std=c++11
    -fPIC
    -Wall
)

target_include_directories(_ascend_mic_ext PRIVATE
    $ENV{INSTALL_DIR}/runtime/include
    $ENV{INSTALL_DIR}/driver
)

target_link_directories(_ascend_mic_ext PRIVATE
    $ENV{INSTALL_DIR}/runtime/lib64/stub
    $ENV{INSTALL_DIR}/driver
)

target_link_libraries(_ascend_mic_ext PRIVATE
    media_mini
    ascend_hal
    pthread
    c_sec
    mmpa
)

# Place the .so next to the Python package so it can be imported in-place
set_target_properties(_ascend_mic_ext PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/src/ascend_mic"
)

# ---------------------------------------------------------------------------
# Install via pip after building the .so (optional convenience target)
# ---------------------------------------------------------------------------
add_custom_target(pip_install
    COMMAND "${Python3_EXECUTABLE}" -m pip install --no-build-isolation -e
            "${CMAKE_CURRENT_SOURCE_DIR}"
    DEPENDS _ascend_mic_ext
    COMMENT "Installing ascend_mic Python package in editable mode"
)
