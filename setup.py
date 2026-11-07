from setuptools import setup, find_packages

setup(
    name="jobfinder",
    version="1.0.0",
    description="CLI tool to fetch jobs from corporate career portals (Workday, Eightfold, Greenhouse, iCIMS)",
    packages=find_packages(),
    package_data={"jobfinder": ["templates/*.html"]},
    include_package_data=True,
    py_modules=["cli"],
    python_requires=">=3.9",
    install_requires=[
        "requests>=2.28",
        "click>=8.0",
        "rich>=13.0",
    ],
    entry_points={
        "console_scripts": [
            "jobfinder=cli:cli",
        ],
    },
)

