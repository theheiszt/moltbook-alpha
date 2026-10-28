from setuptools import setup, find_packages

setup(
    name="moltbook-intel-sdk",
    version="1.0.0",
    description="Official Python SDK for the Moltbook Alpha Market Intelligence & Payment API",
    author="Moltbook Alpha Team",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[],
    extras_require={
        "crypto": ["pycryptodome>=3.20.0"],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
