#!/usr/bin/python3
# Executa o Django como CGI. Necessário porque este servidor HostGator não
# tem Passenger (sem Ruby/mod_passenger em /opt/cpanel), mas tem mod_cgid.
import os
import sys
import traceback

HOME = "/home2/prese257"
BACKEND = HOME + "/cemadenrj_backend"
LOG = BACKEND + "/cgi_error.log"

sys.path.insert(0, HOME + "/.local/lib/python3.9/site-packages")
sys.path.insert(0, BACKEND)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# O RewriteRule manda /api/... para /django.cgi/api/...; o Django deve ver
# o caminho original (/api/...), sem o nome do script como prefixo.
os.environ["SCRIPT_NAME"] = ""
uri = os.environ.get("REQUEST_URI", "")
if uri:
    os.environ["PATH_INFO"] = uri.split("?", 1)[0]

try:
    from django.core.wsgi import get_wsgi_application
    from wsgiref.handlers import CGIHandler

    CGIHandler().run(get_wsgi_application())
except Exception:
    with open(LOG, "a") as f:
        f.write(traceback.format_exc() + "\n")
    sys.stdout.write("Status: 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nErro interno (ver cgi_error.log)\r\n")
