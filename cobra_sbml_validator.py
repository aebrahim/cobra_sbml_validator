from gzip import GzipFile
from bz2 import decompress as bz2_decompress
from tempfile import NamedTemporaryFile
from json import dumps
import re
from warnings import catch_warnings
from os import unlink, path
from codecs import getreader

import tornado
import tornado.ioloop
import tornado.web
import tornado.gen
import tornado.concurrent

from six import BytesIO, StringIO, iteritems
import jsonschema

import cobra
from cobra.core.Gene import parse_gpr
from cobra.manipulation import check_mass_balance, check_reaction_bounds, \
    check_metabolite_compartment_formula

from libsbml import SBMLValidator

executor = tornado.concurrent.futures.ThreadPoolExecutor(8)

validator_form = path.join(path.abspath(path.dirname(__file__)),
                           "validator_form.html")


def load_JSON(contents):
    """returns model, [model_errors], "parse_errors" or None """
    errors = []
    try:
        model_json = cobra.io.json.json.load(getreader("utf-8")(contents))
    except ValueError as e:
        return None, errors, "Invalid JSON: " + str(e)
    try:
        model = cobra.io.json._from_dict(model_json)
    except Exception as e:
        errors.append("Invalid model: " + str(e))
        model = None
    try:
        jsonschema.validate(model_json, cobra.io.json.json_schema)
    except jsonschema.ValidationError as e:
        # render an infomrative error message
        if len(e.absolute_path) > 0:
            error_msg = "Error in "
            for i in e.absolute_path:
                if isinstance(i, int):
                    error_msg = error_msg.rstrip(".") + "[%d]." % i
                else:
                    error_msg += str(i) + "."
            errors.append(error_msg.rstrip(".") + ": " + e.message)
        else:
            errors.append(e.message)
    return model, errors, None


def load_SBML(contents, filename):
    """returns model, [model_errors], "parse_errors" or None """
    try:  # this function fails if a model can not be created
        model, errors = cobra.io.sbml3.validate_sbml_model(
            contents, check_model=False)  # checks are run later
    except cobra.io.sbml3.CobraSBMLError as e:
        return None, [], str(e)
    else:
        return model, errors, None


def run_libsbml_validation(contents, filename):
    if filename.endswith(".gz"):
        filename = filename[:-3]
    elif filename.endswith(".bz2"):
        filename = filename[:-4]
    with NamedTemporaryFile(suffix=filename, delete=False) as outfile:
        outfile.write(contents.read())
        contents.seek(0)  # so the buffer can be re-read
    validator = SBMLValidator()
    validator.validate(str(outfile.name))
    unlink(outfile.name)
    errors = []
    for i in range(validator.getNumFailures()):
        failure = validator.getFailure(i)
        if failure.isWarning():
            continue
        errors.append("L%d C%d: %s" % (failure.getLine(), failure.getColumn(),
                                       failure.getMessage()))
    return errors


def decompress_file(body, filename):
    """returns BytesIO of decompressed file"""
    if filename.endswith(".gz"):
        # contents = zlib.decompress(body, 16 + zlib.MAX_WBITS)
        zip_contents = BytesIO(body)
        with GzipFile(fileobj=zip_contents, mode='rb') as zip_read:
            try:
                contents = BytesIO(zip_read.read())
            except (IOError, OSError) as e:
                return None, "Error decompressing gzip file: " + str(e)
        zip_contents.close()
    elif filename.endswith(".bz2"):
        try:
            contents = BytesIO((bz2_decompress(body)))
        except IOError as e:
            return None, "Error decompressing bz2 file: " + str(e)
    else:
        contents = BytesIO((body))
    return contents, None


def validate_model(model):
    errors = []
    warnings = []
    errors.extend(check_reaction_bounds(model))
    errors.extend(check_metabolite_compartment_formula(model))
    # test gpr
    for reaction in model.reactions:
        try:
            parse_gpr(reaction.gene_reaction_rule)
        except SyntaxError:
            errors.append("reaction '%s' has invalid gpr '%s'" %
                          (reaction.id, reaction.gene_reaction_rule))
    # test mass balance
    for reaction, balance in iteritems(check_mass_balance(model)):
        # check if it's a demand or exchange reaction
        if len(reaction.metabolites) == 1:
            warnings.append("reaction '%s' is not balanced. Should it "
                            "be annotated as a demand or exchange "
                            "reaction?" % reaction.id)
        elif "biomass" in reaction.id.lower():
            warnings.append("reaction '%s' is not balanced. Should it "
                            "be annotated as a biomass reaction?" %
                            reaction.id)
        else:
            warnings.append("reaction '%s' is not balanced for %s" %
                            (reaction.id, ", ".join(sorted(balance))))

    # try solving
    solution = model.optimize(solver="esolver")
    if solution.status != "optimal":
        errors.append("model can not be solved (status '%s')" %
                      solution.status)
        return {"errors": errors, "warnings": warnings}

    # if there is no objective, then we know why the objective was low
    if len(model.objective) == 0:
        warnings.append("model has no objective function")
    elif solution.f <= 0:
        warnings.append("model can not produce nonzero biomass")
    elif solution.f <= 1e-3:
        warnings.append("biomass flux %s too low" % str(solution.f))
    if len(model.objective) > 1:
        warnings.append("model should only have one reaction as the objective")

    return {"errors": errors, "warnings": warnings, "objective": solution.f}


class Upload(tornado.web.RequestHandler):
    def write_error(self, status_code, reason="", **kwargs):
        self.write(reason)

    @tornado.web.asynchronous
    @tornado.gen.engine
    def post(self):
        fileinfo = self.request.files["file"][0]
        filename = fileinfo["filename"]

        contents, error = yield executor.submit(
            decompress_file, fileinfo["body"], filename)
        if error:
            self.send_error(415, reason=error)
            return

        # syntax validation
        # if the model can't be loaded from the file it's considered invalid

        # if not explicitly JSON, assumed to be SBML
        warnings = []
        if filename.endswith(".json") or filename.endswith(".json.gz") or \
                filename.endswith(".json.bz2"):
            model, errors, parse_errors = \
                yield executor.submit(load_JSON, contents)

        else:
            model, errors, parse_errors = \
                yield executor.submit(load_SBML, contents, filename)
            libsbml_errors = yield executor.submit(
                run_libsbml_validation, contents, filename)
            warnings.extend("(from libSBML) " + i for i in libsbml_errors)

        # if parsing failed, then send the error
        if parse_errors:
            self.send_error(415, reason=parse_errors)
            return
        elif model is None:  # parsed, but still could not generate model
            self.finish({"errors": errors, "warnings": warnings})
            return

        # model validation
        result = yield executor.submit(validate_model, model)
        result["errors"].extend(errors)
        result["warnings"].extend(warnings)
        self.finish(result)


class ValidatorFormHandler(tornado.web.RequestHandler):
        def get(self):
            self.render(validator_form)


def run_standalone_server(prefix="", port=5000, debug=False):
    application = tornado.web.Application([
        (prefix + r"/", ValidatorFormHandler),
        (prefix + r"/upload", Upload),
        ],
        debug=True)
    application.listen(port)
    tornado.ioloop.IOLoop.instance().start()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="web-based validator for COBRA models in SBML and JSON")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--prefix", default="")
    parser.add_argument("--debug", action="store_true")

    args = parser.parse_args()

    prefix = args.prefix
    if len(prefix) > 0 and not prefix.startswith("/"):
        prefix = "/" + prefix

    run_standalone_server(
        prefix=prefix,
        port=args.port,
        debug=args.debug)
