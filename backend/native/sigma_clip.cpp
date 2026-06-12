#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <cmath>
#include <stdexcept>
#include <array>

namespace py = pybind11;

py::array_t<bool> sigma_clip_rgb(
    py::array_t<float, py::array::c_style | py::array::forcecast> aligned_rgb,
    py::array_t<float, py::array::c_style | py::array::forcecast> current,
    py::array_t<bool, py::array::c_style | py::array::forcecast> valid_mask,
    float sigma_mult = 3.0f
) {
    auto a = aligned_rgb.unchecked<3>();
    auto c = current.unchecked<3>();
    auto v = valid_mask.unchecked<2>();

    py::ssize_t h = a.shape(0);
    py::ssize_t w = a.shape(1);
    py::ssize_t ch = a.shape(2);

    if (ch != 3) {
        throw std::runtime_error("aligned_rgb must have 3 channels");
    }

    if (c.shape(0) != h || c.shape(1) != w || c.shape(2) != 3) {
        throw std::runtime_error("current shape must match aligned_rgb");
    }

    if (v.shape(0) != h || v.shape(1) != w) {
        throw std::runtime_error("valid_mask shape must match image height/width");
    }

    double sum0 = 0.0, sum1 = 0.0, sum2 = 0.0;
    double sq0 = 0.0, sq1 = 0.0, sq2 = 0.0;
    long long count = 0;

    #pragma omp parallel
    {
        double lsum0 = 0.0, lsum1 = 0.0, lsum2 = 0.0;
        double lsq0 = 0.0, lsq1 = 0.0, lsq2 = 0.0;
        long long lcount = 0;

        #pragma omp for nowait
        for (py::ssize_t y = 0; y < h; y++) {
            for (py::ssize_t x = 0; x < w; x++) {
                if (!v(y, x)) {
                    continue;
                }

                double d0 = std::abs((double)a(y, x, 0) - (double)c(y, x, 0));
                double d1 = std::abs((double)a(y, x, 1) - (double)c(y, x, 1));
                double d2 = std::abs((double)a(y, x, 2) - (double)c(y, x, 2));

                lsum0 += d0;
                lsum1 += d1;
                lsum2 += d2;

                lsq0 += d0 * d0;
                lsq1 += d1 * d1;
                lsq2 += d2 * d2;

                lcount++;
            }
        }

        #pragma omp critical
        {
            sum0 += lsum0;
            sum1 += lsum1;
            sum2 += lsum2;

            sq0 += lsq0;
            sq1 += lsq1;
            sq2 += lsq2;

            count += lcount;
        }
    }

    float sigma0 = 0.0f;
    float sigma1 = 0.0f;
    float sigma2 = 0.0f;

    if (count > 0) {
        double mean0 = sum0 / count;
        double mean1 = sum1 / count;
        double mean2 = sum2 / count;

        double var0 = sq0 / count - mean0 * mean0;
        double var1 = sq1 / count - mean1 * mean1;
        double var2 = sq2 / count - mean2 * mean2;

        if (var0 < 0.0) var0 = 0.0;
        if (var1 < 0.0) var1 = 0.0;
        if (var2 < 0.0) var2 = 0.0;

        sigma0 = (float)std::sqrt(var0);
        sigma1 = (float)std::sqrt(var1);
        sigma2 = (float)std::sqrt(var2);
    }

    py::array_t<bool> result({h, w});
    auto r = result.mutable_unchecked<2>();

    float t0 = sigma_mult * sigma0;
    float t1 = sigma_mult * sigma1;
    float t2 = sigma_mult * sigma2;

    #pragma omp parallel for
    for (py::ssize_t y = 0; y < h; y++) {
        for (py::ssize_t x = 0; x < w; x++) {
            if (!v(y, x)) {
                r(y, x) = false;
                continue;
            }

            float d0 = std::abs(a(y, x, 0) - c(y, x, 0));
            float d1 = std::abs(a(y, x, 1) - c(y, x, 1));
            float d2 = std::abs(a(y, x, 2) - c(y, x, 2));

            r(y, x) = d0 < t0 && d1 < t1 && d2 < t2;
        }
    }

    return result;
}

PYBIND11_MODULE(sigma_clip_ext, m) {
    m.def(
        "sigma_clip_rgb",
        &sigma_clip_rgb,
        py::arg("aligned_rgb"),
        py::arg("current"),
        py::arg("valid_mask"),
        py::arg("sigma_mult") = 3.0f
    );
}