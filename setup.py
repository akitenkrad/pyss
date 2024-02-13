import sys

import setuptools

with open("README.md", mode="r") as f:
    long_description = f.read()

version_range_max = max(sys.version_info[1], 10) + 1
python_min_version = (3, 11, 0)

setuptools.setup(
    name="pyss",
    version="0.0.1",
    author="akitenkrad",
    author_email="akitenkrad@gmail.com",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
    ]
    + [
        "Programming Language :: Python :: 3.{}".format(i)
        for i in range(python_min_version[1], version_range_max)
    ],
    long_description=long_description,
    install_requires=[
        "attrdict @ git+https://github.com/akitenkrad/attrdict",
        "nltk",
        "numpy",
        "pandas",
        "plotly",
        "progressbar",
        "py-cpuinfo",
        "python-dateutil",
        "spacy",
        "janome",
        "sumeval",
        "tqdm",
    ],
)
