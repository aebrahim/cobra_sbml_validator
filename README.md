# cobra_sbml_validator
web-based validator for COBRA models in SBML and JSON

To run the server on your own machine, do the following (only tested on Linux):

1) Install the beta latest version of cobrapy (use ```pip install cobra --pre```).
Ensure that libglpk is installed correctly, as stated in the
[installation directions](https://github.com/opencobra/cobrapy/blob/master/INSTALL.md).

2) Install the latest versions of ```python-libsbml```, ```lxml```, and ```jsonschema```

3) Install [esolver](http://www.dii.uchile.cl/~daespino/ESolver_doc/main.html).
A pre-compiled version available with ABSOLUTELY NO WARRANTY is available
[here](https://opencobra.github.io/pypi_cobrapy_travis/esolver.gz)

4) run ```python cobra_sbml_validator.py```

5) Navigate to http://localhost:5000/
