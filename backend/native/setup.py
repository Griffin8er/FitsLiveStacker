from setuptools import setup, Extension
import pybind11

ext_modules = [
    Extension(
        "sigma_clip_ext",
        ["sigma_clip.cpp"],
        include_dirs=[pybind11.get_include()],
        language="c++",
        extra_compile_args=["/O2", "/openmp"],  # MSVC
    )
]

setup(
    name="sigma_clip_ext",
    ext_modules=ext_modules,
)