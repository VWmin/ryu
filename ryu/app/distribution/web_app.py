import json
import os
import pickle

import requests
from webob.static import DirectoryApp

from ryu.app.wsgi import ControllerBase, route, Response

PATH = os.path.dirname(__file__)


class GUIServerController(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(GUIServerController, self).__init__(req, link, data, **config)
        path = "%s/html/" % PATH
        self.static_app = DirectoryApp(path)
        # self.dds_app = data['dds_app']

    # route to static file resource
    @route('topology', '/{filename:[^/]*}')
    def static_handler(self, req, **kwargs):
        if kwargs['filename']:
            req.path_info = kwargs['filename']
        return self.static_app(req)

    # @route('topology', '/v2.0/topology', methods=['GET'])
    # def topology(self, req, **kwargs):
    #     body = json.dumps(self.dds_app.global_topo)
    #     response = Response(content_type='application/json', body=body)
    #     response.headers['Access-Control-Allow-Origin'] = '*'
    #     return response
    #
    @route('switches', '/v1.0/topology/switches', methods=['GET'])
    def switches(self, req, **kwargs):
        response = requests.get("http://localhost:9002/switches")
        response = Response(content_type='application/json', body=response.content)
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response

    @route('links', '/v1.0/topology/links', methods=['GET'])
    def links(self, req, **kwargs):
        response = requests.get("http://localhost:9002/links")
        response = Response(content_type='application/json', body=response.content)
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
