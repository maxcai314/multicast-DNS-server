import logging
import sys
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
from zero_conf_handler import ZeroConfHandler


class HttpHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"<p style=\"font-size: 2rem\">Hello World!</p>")


def run_http_server(port=80):
    server_address = ("", port)
    httpd = HTTPServer(server_address, HttpHandler)
    logging.info("HTTP server running on port %s", port)
    httpd.serve_forever()

if __name__ == "__main__":
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    logging.basicConfig(stream=sys.stderr, level=logging.ERROR)
    logging.basicConfig(stream=sys.stdout, level=logging.WARNING)
    logging.basicConfig(stream=sys.stderr, level=logging.CRITICAL)
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)

    mDNS_handler = ZeroConfHandler()

    # use a thread to run the http server
    http_thread = threading.Thread(target=run_http_server)
    http_thread.start()

    url = "http://testing.local"

    # register the http server
    mDNS_handler.zeroconf_register("_http._tcp.local.",
                                   "http server", 80, server_url="testing.local")
    print("registered http server at http://testing.local")
    mDNS_handler.zeroconf_register("_http._tcp.local.",
                                   "Printer", 80, server_url="printer.local", address="192.168.86.88")

    mDNS_handler.zeroconf_browse("_http._tcp.local.")