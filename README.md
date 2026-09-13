# Painel Agregador Meteorológico/Hidrológico — CEMADEN-RJ

Sistema web único (responsivo — PC, Smart TV, Android, iPhone via navegador)
que agrega dados de chuva/nível de rio/condições meteorológicas do estado do
Rio de Janeiro a partir de múltiplas fontes públicas, para uso operacional
pela CEMADEN-RJ (Defesa Civil do Estado do RJ).

Ver plano completo e contexto em `docs/fontes-de-dados.md` e no histórico do
projeto. Este README cobre só o "como rodar".

> **Onde desenvolver:** este projeto tem uma cópia "fonte" no Google Drive
> (`H:\Meu Drive\Claude\cemaden-rj-painel`) e uma cópia de trabalho local
> (`C:\Users\<usuário>\projects\cemaden-rj-painel`). Rode `npm install` e
> `pip install`/`venv` sempre na cópia **local** — testamos instalar direto
> no Google Drive e o sync do Drive corrompeu a instalação no meio do
> processo (erros `EBADF`/`ENOTEMPTY`, porque o Drive tenta sincronizar
> milhares de arquivos pequenos do `node_modules`/`venv` enquanto eles são
> criados). Edite o código em qualquer uma das cópias, mas rode servidores e
> instale dependências só na local; sincronize o código-fonte de volta pro
> Drive com o comando abaixo quando quiser salvar uma versão lá (backup/
> visibilidade), sem nunca copiar `node_modules`/`venv`/`.next`:
> ```powershell
> robocopy "C:\Users\<usuário>\projects\cemaden-rj-painel" "H:\Meu Drive\Claude\cemaden-rj-painel" /E /XD node_modules venv .next __pycache__ /XF db.sqlite3
> ```
> Melhor ainda a médio prazo: colocar o projeto num repositório git (GitHub/
> GitLab) em vez de depender do Google Drive para isso.

## Estrutura

```
backend/    Django + Django REST Framework + Celery (API + ingestão de dados)
frontend/   Next.js (mapa + painel, responsivo)
docs/       Levantamento das APIs de cada fonte de dados
```

## Rodando localmente (sem Docker)

### Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/Mac
pip install -r requirements.txt
copy .env.example .env         # Windows: copy | Linux/Mac: cp
python manage.py migrate
python manage.py createsuperuser
python manage.py ingest inmet  # popula estações reais do INMET no RJ
python manage.py runserver
```

API disponível em `http://localhost:8000/api/stations/`. Admin em
`http://localhost:8000/admin/`.

Outras fontes: `python manage.py ingest cemaden_nacional`,
`python manage.py ingest alerta_rio`, ou `python manage.py ingest all`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Abre em `http://localhost:3000`. Espera a API em
`NEXT_PUBLIC_API_BASE_URL` (padrão `http://localhost:8000/api`, configurável
em `frontend/.env.local`).

## Rodando com Docker (produção / servidor)

```bash
cp backend/.env.example backend/.env   # editar valores reais
docker compose up -d --build
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser
```

## Ingestão automática

Em produção, `celery_beat` (ver `docker-compose.yml`) agenda a coleta de cada
fonte a cada 15 minutos automaticamente — não precisa rodar `ingest`
manualmente. Ajuste a cadência em `backend/config/celery.py`.

## Status das fontes de dados

Ver `docs/fontes-de-dados.md` para o que já funciona, o que precisa de um
token (INMET) e o que depende de acesso institucional (GridLab/CEMADEN-RJ,
leituras em tempo real do Alerta Rio).
