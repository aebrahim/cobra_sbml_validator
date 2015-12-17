from StringIO import StringIO
from gzip import GzipFile
from bz2 import BZ2File

from json import dumps
import re
from warnings import catch_warnings

import tornado
import tornado.ioloop
import tornado.web

import jsonschema

import cobra

from validator import validate_model


class Upload(tornado.web.RequestHandler):
    def write_error(self, status_code, reason="", **kwargs):
        self.write(reason)

    def post(self):
        fileinfo = self.request.files["file"][0]
        filename = fileinfo["filename"]
        body = fileinfo["body"]
        if filename.endswith(".gz"):
            zip_contents = StringIO(body)
            contents = StringIO()
            with GzipFile(fileobj=zip_contents, mode='rb') as zip_read:
                try:
                    contents = StringIO(zip_read.read())
                except IOError as e:
                    self.send_error(415,
                                    reason="Error decompressing gzip file: " +
                                    e.message)
                    return

            zip_contents.close()
        elif filename.endswith(".bz2"):
            zip_contents = StringIO(body)
            contents = StringIO()
            with BZ2File(fileobj=zip_contents, mode='rb') as zip_read:
                contents = StringIO(zip_read.read())
            zip_contents.close()
        else:
            contents = StringIO(body)

        # syntax validation
        # if the model can't be loaded from the file it's considered invalid
        if filename.endswith(".json") or filename.endswith(".json.gz") or \
                filename.endswith(".json.bz2"):
            try:
                model_json = cobra.io.json.json.load(contents)
            except ValueError as e:
                self.send_error(415, reason="Invalid JSON:" + e.message)
                return
            try:
                model = cobra.io.json._from_dict(model_json)
            except Exception as e:
                self.send_error(415, reason="Invalid model:" + e.message)
                return
            try:
                jsonschema.validate(model_json, cobra.io.json.json_schema)
            except jsonschema.ValidationError as e:
                errors = [e.message]
            else:
                errors = []

        else:  # SBML validation
            try:  # this function fails if a model can not be created
                model, errors = cobra.io.sbml3.validate_sbml_model(
                    contents, check_model=False)  # checks are run later
            except cobra.io.sbml3.CobraSBMLError as e:
                self.send_error(415, reason=e.message)
                return

        if model is None:
            self.finish(dumps({"errors": errors, "warnings": []}))
            return

        # model validation
        result = validate_model(model, errors=errors)
        self.finish(dumps(result))


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
