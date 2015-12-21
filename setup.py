try:
    from setuptools import setup, find_packages
except ImportError:
    from distutils.core import setup

setup(name="cobra_sbml_validator",
      version="0.0.1",
      author="Ali Ebrahim",
      author_email="aebrahim@ucsd.edu",
      url="https://github.com/aebrahim/cobra_sbml_validator",
      py_modules=["cobra_sbml_validator"],
      description="web-based validator for COBRA models in SBML and JSON",
      package_data={'': ["validator_form.html"]},
      license="MIT")
