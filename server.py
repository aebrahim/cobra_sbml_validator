from StringIO import StringIO
from gzip import GzipFile
from bz2 import decompress as bz2_decompress
from tempfile import NamedTemporaryFile

from json import dumps
import re
from warnings import catch_warnings

import tornado
import tornado.ioloop
import tornado.web
import tornado.gen
import tornado.concurrent

import jsonschema

import cobra
from libsbml import SBMLValidator

from validator import validate_model


executor = tornado.concurrent.futures.ThreadPoolExecutor(8)


def load_JSON(contents):
    """returns model, [model_errors], "parse_errors" or None """
    errors = []
    try:
        model_json = cobra.io.json.json.load(contents)
    except ValueError as e:
        return None, errors, "Invalid JSON: " + e.message
    try:
        model = cobra.io.json._from_dict(model_json)
    except Exception as e:
        errors.append("Invalid model: " + e.message)
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
        return None, [], e.message
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
    outfile.unlink(outfile.name)
    errors = []
    for i in range(validator.getNumFailures()):
        failure = validator.getFailure(i)
        if failure.isWarning():
            continue
        errors.append("L%d C%d: %s" % (failure.getLine(), failure.getColumn(),
                                       failure.getMessage()))
    return errors


def decompress_file(body, filename):
    """returns StringIO of decompressed file"""
    if filename.endswith(".gz"):
        # contents = zlib.decompress(body, 16 + zlib.MAX_WBITS)
        contents = StringIO()
        zip_contents = StringIO(body)
        with GzipFile(fileobj=zip_contents, mode='rb') as zip_read:
            try:
                contents = StringIO(zip_read.read())
            except IOError as e:
                return None, "Error decompressing gzip file: " + e.message
        zip_contents.close()
    elif filename.endswith(".bz2"):
        try:
            contents = StringIO(bz2_decompress(body))
        except IOError as e:
            return None, "Error decompressing bz2 file: " + e.message
    else:
        contents = StringIO(body)
    return contents, None


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

if __name__ == "__main__":
    class Userform(tornado.web.RequestHandler):
        def get(self):
            self.render("index.html")

    prefix = r"/cobra_sbml_validator"

    application = tornado.web.Application([
        (prefix + r"/", Userform),
        (prefix + r"/upload", Upload),
        ],
        debug=True)

    application.listen(5000)
    tornado.ioloop.IOLoop.instance().start()
