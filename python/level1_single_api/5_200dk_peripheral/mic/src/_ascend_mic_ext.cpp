/**
 * Copyright 2020 Huawei Technologies Co., Ltd
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 * @brief  pybind11 C++ extension that wraps the Ascend 200 DK peripheral
 *         microphone API (peripheral_api.h / libmedia_mini) so it can be
 *         consumed from Python with a sounddevice-compatible interface.
 *
 * Exposed to Python
 * -----------------
 *   Class MicDevice  – thin wrapper around the C library functions
 *   Constants        – all MIC_* enum values needed to configure properties
 */

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>

#include <cstring>
#include <mutex>
#include <condition_variable>
#include <queue>
#include <stdexcept>
#include <string>
#include <vector>

extern "C" {
#include "peripheral_api.h"
}

namespace py = pybind11;

// ---------------------------------------------------------------------------
// Internal buffer used by the passive (callback) capture path
// ---------------------------------------------------------------------------
struct CallbackCtx {
    std::mutex              mtx;
    std::condition_variable cv;
    std::queue<std::vector<uint8_t>> queue;
    bool                    stopped{false};
};

static int mic_callback_impl(const void *pdata, int size, void *param)
{
    auto *ctx = static_cast<CallbackCtx *>(param);
    {
        std::lock_guard<std::mutex> lk(ctx->mtx);
        const auto *src = static_cast<const uint8_t *>(pdata);
        ctx->queue.emplace(src, src + size);
    }
    ctx->cv.notify_one();
    return 0;
}

// ---------------------------------------------------------------------------
// MicDevice class
// ---------------------------------------------------------------------------
class MicDevice {
public:
    MicDevice()
    {
        int ret = MediaLibInit();
        if (ret == LIBMEDIA_STATUS_FAILED) {
            throw std::runtime_error("MediaLibInit failed");
        }
    }

    ~MicDevice() { close(); }

    // --- lifecycle ----------------------------------------------------------

    void open()
    {
        if (m_open) { return; }
        if (OpenMIC() == LIBMEDIA_STATUS_FAILED) {
            throw std::runtime_error("OpenMIC failed");
        }
        m_open = true;
    }

    void close()
    {
        if (!m_open) { return; }
        if (m_ctx) {
            {
                std::lock_guard<std::mutex> lk(m_ctx->mtx);
                m_ctx->stopped = true;
            }
            m_ctx->cv.notify_all();
            m_ctx.reset();
        }
        CloseMIC();
        m_open = false;
    }

    // --- configuration ------------------------------------------------------

    /**
     * Configure the microphone.
     *
     * @param sample_rate       One of the MIC_AUDIO_SAMPLE_RATE_* integer values.
     * @param frame_sample_rate One of the MIC_SAMPLE_NUM_* integer values.
     * @param cap_mode          MIC_CAP_ACTIVE (0) or MIC_CAP_PASSIVE (1).
     * @param bit_width         MIC_AUDIO_BIT_WIDTH_16 or MIC_AUDIO_BIT_WIDTH_24.
     * @param sound_mode        MIC_AUDIO_SOUND_MODE_MONO or MIC_AUDIO_SOUND_MODE_STEREO.
     */
    void set_property(int sample_rate, int frame_sample_rate,
                      int cap_mode,    int bit_width, int sound_mode)
    {
        MICProperties p{};
        p.sample_rate        = static_cast<MICAudioSampleRate>(sample_rate);
        p.frame_sample_rate  = static_cast<MICSampleNum>(frame_sample_rate);
        p.cap_mode           = static_cast<MICCapMode>(cap_mode);
        p.bit_width          = static_cast<MICAudioBitWidth>(bit_width);
        p.sound_mode         = static_cast<MICAudioSoundMode>(sound_mode);

        if (SetMICProperty(&p) == LIBMEDIA_STATUS_FAILED) {
            throw std::runtime_error("SetMICProperty failed");
        }
    }

    py::dict get_property()
    {
        MICProperties p{};
        if (GetMICProperty(&p) == LIBMEDIA_STATUS_FAILED) {
            throw std::runtime_error("GetMICProperty failed");
        }
        py::dict d;
        d["sample_rate"]       = static_cast<int>(p.sample_rate);
        d["frame_sample_rate"] = static_cast<int>(p.frame_sample_rate);
        d["cap_mode"]          = static_cast<int>(p.cap_mode);
        d["bit_width"]         = static_cast<int>(p.bit_width);
        d["sound_mode"]        = static_cast<int>(p.sound_mode);
        return d;
    }

    // --- active read (MIC_CAP_ACTIVE) ---------------------------------------

    /**
     * Blocking read of raw PCM bytes from the microphone.
     *
     * Call this after set_property(..., cap_mode=MIC_CAP_ACTIVE, ...).
     *
     * @param num_bytes  How many bytes to request.
     * @return (bytes_data, overflowed)
     *         bytes_data  – Python bytes object with the raw PCM samples.
     *         overflowed  – True when the hardware returned fewer bytes than
     *                       requested or signalled an error.
     */
    py::tuple read_sound(int num_bytes)
    {
        if (num_bytes <= 0) {
            throw std::invalid_argument("num_bytes must be positive");
        }
        std::vector<uint8_t> buf(static_cast<std::size_t>(num_bytes), 0);
        int size = num_bytes;
        int ret  = ReadMicSound(buf.data(), &size);

        bool overflowed = (ret == LIBMEDIA_STATUS_FAILED) || (size < num_bytes);
        int  actual     = (ret == LIBMEDIA_STATUS_FAILED) ? 0 : size;

        return py::make_tuple(
            py::bytes(reinterpret_cast<const char *>(buf.data()), actual),
            overflowed);
    }

    // --- passive capture (MIC_CAP_PASSIVE) ----------------------------------

    /**
     * Start passive capture.  Internally registers a C callback that pushes
     * each incoming frame into a thread-safe queue so that Python can retrieve
     * them with read_passive().
     */
    void start_capture()
    {
        m_ctx = std::make_unique<CallbackCtx>();
        if (CapMIC(mic_callback_impl, m_ctx.get()) == LIBMEDIA_STATUS_FAILED) {
            m_ctx.reset();
            throw std::runtime_error("CapMIC failed");
        }
    }

    /**
     * Retrieve the next frame from the passive capture queue.
     * Blocks until a frame is available or the capture is stopped.
     *
     * @return (bytes_data, overflowed)
     */
    py::tuple read_passive()
    {
        if (!m_ctx) {
            throw std::runtime_error("Passive capture not started. Call start_capture() first.");
        }
        std::unique_lock<std::mutex> lk(m_ctx->mtx);
        m_ctx->cv.wait(lk, [this]{ return !m_ctx->queue.empty() || m_ctx->stopped; });

        if (m_ctx->queue.empty()) {
            return py::make_tuple(py::bytes("", 0), true);
        }
        auto frame = std::move(m_ctx->queue.front());
        m_ctx->queue.pop();
        return py::make_tuple(
            py::bytes(reinterpret_cast<const char *>(frame.data()), frame.size()),
            false);
    }

    // --- status -------------------------------------------------------------

    int query_status()
    {
        return QueryMICStatus();
    }

    bool is_open() const { return m_open; }

private:
    bool                          m_open{false};
    std::unique_ptr<CallbackCtx>  m_ctx;
};

// ---------------------------------------------------------------------------
// Module definition
// ---------------------------------------------------------------------------
PYBIND11_MODULE(_ascend_mic_ext, m)
{
    m.doc() = "Low-level Python bindings for the Ascend 200 DK microphone API.";

    py::class_<MicDevice>(m, "MicDevice",
        "Wraps the Ascend 200 DK peripheral microphone C API.\n\n"
        "Prefer using the high-level ``ascend_mic.InputStream`` class instead.")
        .def(py::init<>())
        .def("open",          &MicDevice::open,
             "Open the microphone device.")
        .def("close",         &MicDevice::close,
             "Close the microphone device.")
        .def("set_property",  &MicDevice::set_property,
             py::arg("sample_rate"),
             py::arg("frame_sample_rate"),
             py::arg("cap_mode"),
             py::arg("bit_width"),
             py::arg("sound_mode"),
             "Configure microphone properties.")
        .def("get_property",  &MicDevice::get_property,
             "Return current microphone properties as a dict.")
        .def("read_sound",    &MicDevice::read_sound,
             py::arg("num_bytes"),
             "Read *num_bytes* bytes of raw PCM data (active mode).\n\n"
             "Returns (bytes_data, overflowed).")
        .def("start_capture", &MicDevice::start_capture,
             "Begin passive capture (register internal callback).")
        .def("read_passive",  &MicDevice::read_passive,
             "Retrieve the next captured frame (passive mode).\n\n"
             "Blocks until a frame is available. Returns (bytes_data, overflowed).")
        .def("query_status",  &MicDevice::query_status,
             "Return mic status: MIC_STATUS_OPEN, MIC_STATUS_CLOSED, or MIC_NOT_EXISTS.")
        .def_property_readonly("is_open", &MicDevice::is_open,
             "True if the microphone device is currently open.");

    // -----------------------------------------------------------------------
    // Sample-rate constants
    // -----------------------------------------------------------------------
    m.attr("MIC_AUDIO_SAMPLE_RATE_8000")  = static_cast<int>(MIC_AUDIO_SAMPLE_RATE_8000);
    m.attr("MIC_AUDIO_SAMPLE_RATE_11025") = static_cast<int>(MIC_AUDIO_SAMPLE_RATE_11025);
    m.attr("MIC_AUDIO_SAMPLE_RATE_12000") = static_cast<int>(MIC_AUDIO_SAMPLE_RATE_12000);
    m.attr("MIC_AUDIO_SAMPLE_RATE_16000") = static_cast<int>(MIC_AUDIO_SAMPLE_RATE_16000);
    m.attr("MIC_AUDIO_SAMPLE_RATE_22050") = static_cast<int>(MIC_AUDIO_SAMPLE_RATE_22050);
    m.attr("MIC_AUDIO_SAMPLE_RATE_24000") = static_cast<int>(MIC_AUDIO_SAMPLE_RATE_24000);
    m.attr("MIC_AUDIO_SAMPLE_RATE_32000") = static_cast<int>(MIC_AUDIO_SAMPLE_RATE_32000);
    m.attr("MIC_AUDIO_SAMPLE_RATE_44100") = static_cast<int>(MIC_AUDIO_SAMPLE_RATE_44100);
    m.attr("MIC_AUDIO_SAMPLE_RATE_48000") = static_cast<int>(MIC_AUDIO_SAMPLE_RATE_48000);
    m.attr("MIC_AUDIO_SAMPLE_RATE_64000") = static_cast<int>(MIC_AUDIO_SAMPLE_RATE_64000);
    m.attr("MIC_AUDIO_SAMPLE_RATE_96000") = static_cast<int>(MIC_AUDIO_SAMPLE_RATE_96000);

    // -----------------------------------------------------------------------
    // Frame-size constants (samples per frame per channel)
    // -----------------------------------------------------------------------
    m.attr("MIC_SAMPLE_NUM_80")   = static_cast<int>(MIC_SAMPLE_NUM_80);
    m.attr("MIC_SAMPLE_NUM_160")  = static_cast<int>(MIC_SAMPLE_NUM_160);
    m.attr("MIC_SAMPLE_NUM_240")  = static_cast<int>(MIC_SAMPLE_NUM_240);
    m.attr("MIC_SAMPLE_NUM_320")  = static_cast<int>(MIC_SAMPLE_NUM_320);
    m.attr("MIC_SAMPLE_NUM_480")  = static_cast<int>(MIC_SAMPLE_NUM_480);
    m.attr("MIC_SAMPLE_NUM_1024") = static_cast<int>(MIC_SAMPLE_NUM_1024);
    m.attr("MIC_SAMPLE_NUM_2048") = static_cast<int>(MIC_SAMPLE_NUM_2048);

    // -----------------------------------------------------------------------
    // Capture-mode constants
    // -----------------------------------------------------------------------
    m.attr("MIC_CAP_ACTIVE")  = static_cast<int>(MIC_CAP_ACTIVE);
    m.attr("MIC_CAP_PASSIVE") = static_cast<int>(MIC_CAP_PASSIVE);

    // -----------------------------------------------------------------------
    // Bit-width constants
    // -----------------------------------------------------------------------
    m.attr("MIC_AUDIO_BIT_WIDTH_16") = static_cast<int>(MIC_AUDIO_BIT_WIDTH_16);
    m.attr("MIC_AUDIO_BIT_WIDTH_24") = static_cast<int>(MIC_AUDIO_BIT_WIDTH_24);

    // -----------------------------------------------------------------------
    // Sound-mode constants
    // -----------------------------------------------------------------------
    m.attr("MIC_AUDIO_SOUND_MODE_MONO")   = static_cast<int>(MIC_AUDIO_SOUND_MODE_MONO);
    m.attr("MIC_AUDIO_SOUND_MODE_STEREO") = static_cast<int>(MIC_AUDIO_SOUND_MODE_STEREO);

    // -----------------------------------------------------------------------
    // Status constants
    // -----------------------------------------------------------------------
    m.attr("MIC_STATUS_OPEN")   = static_cast<int>(MIC_STATUS_OPEN);
    m.attr("MIC_STATUS_CLOSED") = static_cast<int>(MIC_STATUS_CLOSED);
    m.attr("MIC_NOT_EXISTS")    = static_cast<int>(MIC_NOT_EXISTS);
}
