# Deploy no HostGator compartilhado (sem Passenger, sem shell)

Este servidor não tem Passenger (não existe Ruby nem mod_passenger em
`/opt/cpanel`), então o "Gerenciar Aplicações" do cPanel não consegue
rotear o domínio. O Apache tem `mod_cgid`, então o Django roda como CGI.

Layout no servidor (usuário `prese257`):

- `~/cemadenrj_backend/`  código Django + `.env` de produção (fora do web root)
- `~/cemadenrj.preserve.rio.br/`  document root do subdomínio:
  - build estático do Next.js (`frontend/out/`, gerado com
    `NEXT_PUBLIC_API_BASE_URL=https://cemadenrj.preserve.rio.br/api npm run build`
    — a variável de ambiente é obrigatória, senão o `.env.local` sobrescreve)
  - `django.cgi` (chmod 755) e `.htaccess` (arquivos desta pasta) — o
    RewriteRule manda `/api/*` para o CGI

Dependências: instaladas pelo botão "Ensure dependencies" do cPanel (ou
`PassengerApps/ensure_deps` na API, com `type=pip&app_path=cemadenrj_backend`),
em `~/.local/lib/python3.9/site-packages`.

Banco: MySQL 5.7 (o Django 4.2 exige 8+, contornado por
`backend/config/mysql_compat`). Migrations e ingestão são disparadas por
HTTP em `/api/admin/run/` (header `X-Admin-Secret`), chamadas pelos Cron
Jobs do cPanel.
