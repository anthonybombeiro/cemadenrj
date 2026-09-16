"""
Ponto de entrada que o Phusion Passenger (cPanel > Gerenciar aplicações)
procura por convenção nesse nome exato, na raiz da aplicação registrada.
Só repassa para o WSGI de verdade do Django (config/wsgi.py) — mantido
separado para não misturar a config real do projeto com a convenção do
Passenger.
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config.wsgi import application  # noqa: E402,F401
