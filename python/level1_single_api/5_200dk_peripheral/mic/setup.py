# Copyright 2020 Huawei Technologies Co., Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Build script for the ascend_mic Python package.

Prerequisites
-------------
* Ascend 200 DK toolkit installed; set ``INSTALL_DIR`` env var to the
  toolkit root (e.g. ``/usr/local/Ascend/ascend-toolkit/latest``).
* pybind11 installed: ``pip install pybind11``.
* numpy installed: ``pip install numpy``.

Build
-----
::

    export INSTALL_DIR=/usr/local/Ascend/ascend-toolkit/latest
    pip install .

Or in editable / development mode::

    pip install -e .
"""

import os
import sys

from setuptools import Extension, find_packages, setup

try:
    import pybind11
    PYBIND11_INCLUDE = pybind11.get_include()
except ImportError:
    sys.exit(
        "pybind11 is required to build this package.\n"
        "Install it with:  pip install pybind11"
    )

# ---------------------------------------------------------------------------
# Paths from environment (mirrors the CMakeLists.txt convention used by the
# rest of this repository)
# ---------------------------------------------------------------------------
INSTALL_DIR = os.environ.get(
    "INSTALL_DIR", "/usr/local/Ascend/ascend-toolkit/latest"
)

_ascend_mic_ext = Extension(
    # installs as  ascend_mic/_ascend_mic_ext.<cpython>.so
    name="ascend_mic._ascend_mic_ext",
    sources=["src/_ascend_mic_ext.cpp"],
    include_dirs=[
        PYBIND11_INCLUDE,
        os.path.join(INSTALL_DIR, "runtime", "include"),
        os.path.join(INSTALL_DIR, "driver"),
    ],
    library_dirs=[
        os.path.join(INSTALL_DIR, "runtime", "lib64", "stub"),
        os.path.join(INSTALL_DIR, "driver"),
    ],
    libraries=[
        "media_mini",
        "ascend_hal",
        "pthread",
        "c_sec",
        "mmpa",
    ],
    extra_compile_args=["-std=c++11", "-fPIC", "-Wall"],
    language="c++",
)

setup(
    name="ascend_mic",
    version="1.0.0",
    description=(
        "Ascend 200 DK microphone Python library with a "
        "sounddevice-compatible InputStream interface"
    ),
    long_description=open(
        os.path.join(os.path.dirname(__file__), "README.md"), encoding="utf-8"
    ).read(),
    long_description_content_type="text/markdown",
    license="Apache-2.0",
    python_requires=">=3.6",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    ext_modules=[_ascend_mic_ext],
    install_requires=[
        "numpy>=1.16.0",
    ],
    extras_require={
        "dev": ["pybind11>=2.6.0"],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: POSIX :: Linux",
        "Topic :: Multimedia :: Sound/Audio :: Capture/Recording",
    ],
)
