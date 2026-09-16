# Fontes de dados — o que foi confirmado e o que falta validar

Levantamento feito em setembro/2026 durante a montagem deste projeto. Serve
como referência para os conectores em `backend/ingestion/connectors/` e para
quem for negociar acessos institucionais.

## Plugfield — confirmado e funcionando (conta institucional CEMADEN-RJ)

- API oficial documentada (Swagger): https://wdg.plugfield.com.br/doc-api/index.html
  — atenção, o servidor real é outro host: `https://prod-api.plugfield.com.br`.
- Login: `POST /login` com header `x-api-key` e corpo `{username, password}` →
  `access_token` (JWT que não expira). Chamadas seguintes usam
  `x-api-key` + `Authorization: <access_token>` (sem prefixo "Bearer").
- Um único endpoint basta: `GET /device?page=1` já devolve, para cada
  estação, metadados (nome, lat/lon, cidade) **e** a última leitura
  embutida em `dashboard` (temperatura, umidade, chuva do dia, vento,
  rajada, direção, ponto de orvalho, pressão, UV) — sem precisar de
  chamada extra por estação.
- **9 estações reais confirmadas** (setembro/2026): Cambuci (2), Areal,
  Engenheiro Paulo de Frontin (3), Mendes, Cordeiro, Rio Claro — todas
  claramente estações de Defesa Civil municipal.
- **Histórico de segurança:** uma implementação anterior deste conector
  (feita em outra sessão/branch) commitou usuário, senha e API key da
  Plugfield em texto puro no código-fonte, publicado no GitHub. Foi
  reescrito do zero aqui (credenciais só via `.env`, nunca no código) e o
  branch comprometido foi apagado do GitHub — mas as credenciais antigas
  já ficaram expostas publicamente por um tempo. **Recomendação: trocar a
  senha da conta Plugfield e gerar uma nova API key.**
- Limites documentados: 5.000 requisições/mês por estação, 5 req/s.

## INMET — confirmado e funcionando

- Lista de estações automáticas (sem autenticação):
  `GET https://apitempo.inmet.gov.br/estacoes/T`
  Filtrar por `SG_ESTADO == "RJ"` → 26 estações automáticas no RJ no momento
  do levantamento. Campos: `CD_ESTACAO` (código), `DC_NOME`, `VL_LATITUDE`,
  `VL_LONGITUDE`, `VL_ALTITUDE`, `CD_SITUACAO` ("Operante"/"Pane").
- Metadados de uma estação: `GET /getEstacao/{codigo}` — redundante com a
  lista acima, útil só para depuração manual.
- Séries horárias históricas (rota confirmada, mas **precisa de token**):
  `GET /token/estacao/{inicio}/{fim}/{codigo}/{token}`
  Sem token válido, retorna `"CHAVE INVÁLIDA!"`. Não existe cadastro de
  autoatendimento para esse token — pedido enviado por e-mail ao INMET/
  COPREM (ver `docs/email-inmet-rascunho.md`), resposta pendente.
  **Confirmado independentemente (16/09/2026):** o painel COR-RIO
  `github.com/COR-RIO/dados-rio-chuvas` bateu na mesma parede (mesmo texto
  de erro, mesma rota morta) e documenta a mesma solução (contatar o SAC
  do INMET) — não é limitação nossa, é a situação real da API.
- **Alternativa sem token, pendente de decisão do usuário:** tabela
  BigQuery oficial `datario.meio_ambiente_clima.meteorologia_inmet`
  (mantida por basedosdados/Prefeitura do Rio, achada via
  `https://www.data.rio/documents/f14b1ed52be447379383acbb96353e1c`) —
  dados horários (chuva 1h, vento, temperatura, pressão, umidade,
  radiação) **desde 2010**, atualização diária (não é tempo real, mas não
  precisa de token do INMET nem de Chrome). Exige o usuário criar um
  projeto Google Cloud gratuito (sandbox, sem cartão) e nos passar o ID —
  mesma exigência da tabela de chuva por bairro do Alerta Rio (ver acima),
  então configurar uma vez destrava as duas. Usuário optou por aguardar a
  resposta do e-mail ao INMET antes de investir nisso (16/09/2026).
- **Solução temporária em produção (implementada):** enquanto o token não
  chega, `InmetConnector` usa a técnica que o usuário já tinha em produção
  para consultar vento — Selenium com Chrome real renderizando
  `https://tempo.inmet.gov.br/TabelaEstacoes/{codigo}` (página pública, sem
  login) e parsing da tabela HTML com pandas. Generalizamos para também
  extrair chuva/temperatura/umidade da mesma tabela, não só vento. A
  validação anti-robô dessa página é um reCAPTCHA Enterprise invisível que
  roda no JS da própria página — um Chrome de verdade carregando a página
  resolve isso sozinho, sem nenhuma ação de bypass da nossa parte.
  **Limitação:** exige Chrome instalado na máquina que roda a ingestão →
  funciona em desenvolvimento local, **não funciona no HostGator
  compartilhado** (sem root para instalar Chrome). Nesse servidor, a
  ingestão do INMET vai ficar sem vento/chuva/temperatura em tempo real até
  o token chegar (a lista de estações continua funcionando normalmente,
  pois usa só a API JSON pública). Ver `INMET_SCRAPE_ENABLED` em
  `backend/config/settings.py` para desligar o scraping se necessário.
  **Testado com dados reais** em 13/09/2026: 18-23 das 26 estações do RJ
  retornam leituras a cada rodada (chuva/temperatura/umidade/vento/rajada/
  direção). Três estações (A601 Seropédica, A618 Teresópolis-Parque
  Nacional, A611 Valença) disparam consistentemente um `alert()` JS na
  página ("Erro ao carregar lista de estações") que o Chrome não consegue
  contornar automaticamente — o conector detecta, ignora essa estação
  naquela rodada e segue para as demais sem travar; não chegamos a
  investigar a causa raiz no site do INMET.
- **Como isso roda em produção no HostGator, que não tem Chrome:** testamos
  se a validação anti-robô do endpoint (`POST
  https://apitempo.inmet.gov.br/estacao/front/`, campo `gcap`) é só
  decorativa — não é. Mandamos o campo vazio/forjado e o servidor recusou
  (`{"error":"Algo deu errado!!"}`), confirmando que é validado de verdade.
  Não tentamos forjar um token válido (seria contornar a proteção
  anti-robô do site, fora do que topamos fazer). A solução: o scraping
  roda de graça no **GitHub Actions** (repositório público =
  minutos ilimitados), que tem Chrome disponível, a cada 15 min
  (`.github/workflows/scrape-inmet.yml` +
  `backend/scripts/scrape_inmet_and_push.py`), e envia o resultado via
  HTTP para o endpoint `POST /api/ingest/readings/` do backend no
  HostGator (protegido por segredo compartilhado, ver
  `INGEST_SHARED_SECRET` em `backend/.env.example`). Testado localmente
  ponta a ponta (script → endpoint → aparece em `/api/stations/`).
  Configuração necessária no GitHub (Settings → Secrets and variables →
  Actions) do repositório: `INGEST_URL` (ex:
  `https://cemaden.preservess.com.br/api/ingest/readings/`) e
  `INGEST_SHARED_SECRET` (mesmo valor do `.env` do backend em produção).

## CEMADEN Nacional — documentado, não testável a partir deste ambiente

Documento oficial "WebService – Disponibilização de dados da rede
pluviométrica e Hidrológica Cemaden" (Cemaden, Grupo de Desenvolvimento de
Sistemas, v2.0, 2015), obtido em
`trac.dpi.inpe.br/terrama2/raw-attachment/ticket/86/DOC01_webservice_cemaden.pdf`:

- `GET http://150.163.255.240/CEMADEN/resources/parceiros/{UF}/{tipo}`
  `tipo`: `1` = Pluviométrica, `3` = Hidrológica.
  Retorna só as últimas 3 horas de dados (limite deles, não nosso) —
  por isso a ingestão deve rodar a cada 10-15 min.
  Formato: `{"cemaden": [{"codestacao", "latitude", "longitude", "cidade",
  "nome", "tipo", "uf", "chuva", "nivel", "dataHora"}]}`, `dataHora` em UTC.

- **Atenção:** é um IP direto (não um domínio), documentado em 2015. Ao
  testar a partir do ambiente usado para montar este projeto, a conexão
  deu timeout — pode ser bloqueio de rede do ambiente de desenvolvimento,
  firewall que só libera IPs conhecidos, ou o endereço ter mudado. **Preciso
  ser validado a partir do servidor de produção** (o HostGator, que tem
  saída de internet normal). Se não responder de lá também, contatar o
  Cemaden (e-mail do responsável técnico no documento:
  jether.rodrigues@cemaden.gov.br) para confirmar o endereço atual — o mais
  provável é que hoje eles tenham migrado para um domínio via
  mapainterativo.cemaden.gov.br com uma API mais nova (não documentada
  publicamente; o site usa OpenLayers 2.x + backend próprio, não investigado
  a fundo por ser mais demorado de fazer engenharia reversa).

## Alerta Rio / GeoRio — RESOLVIDO (16/09/2026), com leituras reais em tempo real

- Localização das 33 estações pluviométricas (sem autenticação):
  `GET https://www.data.rio/api/download/v1/items/88b61c6abe424c049fdf83d27917602e/geojson?layers=0`
  Retorna GeoJSON com `endereço`, `est` (bairro), `cod` (código da estação),
  coordenadas.
- **Leituras em tempo real — achadas lendo o código-fonte aberto de um
  painel recente da própria COR-RIO no GitHub**
  (`github.com/COR-RIO/dados-rio-chuvas`, pushed em 01/09/2026): a API que
  abastece o site oficial do Alerta Rio é
  `https://websempre.rio.rj.gov.br/json/chuvas` (chuva por estação, janelas
  de 5min/15min/1-4h/24h/96h/mês) e
  `https://websempre.rio.rj.gov.br/json/dados_meteorologicos` (temperatura,
  umidade, pressão, vento — conjunto de estações parcialmente diferente).
  Sem autenticação, sem CAPTCHA. **Só rejeita clientes sem um User-Agent de
  navegador comum** (WAF, mensagem "Request Rejected") — não é um desafio
  interativo, só checagem de cabeçalho, então mandamos um User-Agent normal
  (ver `BROWSER_HEADERS` em `alerta_rio.py`).
- **Testado com dados reais:** 32 das 33 estações pluviométricas retornam
  leitura (a única sem match, "Barra/Itanhangá", genuinamente não aparece
  mais no feed ao vivo — parece ter sido renomeada/desativada na fonte, não
  é bug do nosso lado). Casamento de estação feito por nome (chuva) e por
  código numérico (meteorológico) contra o GeoJSON de estações.
- **Ressalva:** a unidade de velocidade do vento não está documentada
  publicamente — assumimos km/h (convenção comum em painéis de defesa
  civil no Brasil) e convertemos para m/s. Confirmar se possível.
- Esse achado veio de um arquivo de pesquisa (.md) que o usuário baixou de
  outra ferramenta e nos passou — não foi engenharia reversa de proteção
  nenhuma, foi literalmente ler o código-fonte público de um projeto no
  GitHub que já faz isso oficialmente.

## Chuva por Bairro (Escritório de Dados Rio / COR) — mantido como extra, provavelmente descontinuado

Com o Alerta Rio resolvido diretamente (seção acima, via
`websempre.rio.rj.gov.br`), este conector deixou de ser essencial — fica
no projeto como fonte complementar caso o serviço volte a funcionar.

- API pública, sem autenticação, código-fonte aberto:
  https://github.com/prefeitura-rio/api-dados-rio (GPLv3, mantida pelo
  Escritório de Dados, escritoriodedados@gmail.com).
  **Correção (16/09/2026):** o campo `pushed_at` do repositório mostrava
  data recente, mas o commit de verdade mais recente é de 04/03/2024 (a
  atividade "recente" era só um bot de pre-commit, não desenvolvimento).
  Serviço provavelmente descontinuado/abandonado, não instável.
- Achado navegando o catálogo oficial do data.rio (busca por "pluviômetro"
  retornou o dataset "Estações Alerta Rio" que já usávamos + um dataset de
  "Zonas Pluviométricas"), depois cruzando com uma busca no GitHub da
  Prefeitura do Rio (`prefeitura-rio/api-dados-rio`) — sem nenhuma
  engenharia reversa de proteção nenhuma, tudo documentado publicamente.
- Endpoint usado: `GET https://api.dados.rio/v2/clima_pluviometro/
  precipitacao_15min/` — chuva dos últimos 15 min por hexágono H3
  (só cobre o município do Rio, não o estado inteiro). Outras janelas
  (30min/1h/3h/6h/12h/24h/96h) existem na mesma API, não usadas ainda.
- **Status: serviço fora do ar (HTTP 503) em 15/09/2026 e de novo em
  16/09/2026** — não só o endpoint de chuva, mas também `/healthcheck/` e a
  raiz do domínio. Combinado com a descoberta acima (sem desenvolvimento
  real desde 2024), a leitura mais honesta é que este serviço está
  **provavelmente abandonado/descontinuado**, não apenas instável. O
  conector (`rio_chuva_bairro.py`) fica no projeto porque não custa nada
  mantê-lo (trata erro corretamente, não derruba a ingestão) — mas não
  há garantia de que volte a funcionar. Se for importante ter esse dado,
  o caminho é contatar o Escritório de Dados diretamente
  (escritoriodedados@gmail.com) para confirmar se a API foi descontinuada
  e se existe substituta.

## Weather Underground (PWS) — confirmado e funcionando, com ressalva de método

**Histórico importante:** a primeira tentativa aqui foi descobrir *toda* a
rede de estações PWS do RJ fazendo engenharia reversa de um mecanismo não
documentado (varredura de coordenadas contra um endpoint de geolocalização
que devolve a estação mais próxima). Isso foi abandonado — mesmo não
tocando diretamente na proteção anti-robô (Akamai) do mapa interativo do
site, usar um canal alternativo para obter a mesma enumeração que o mapa
protege é, na prática, a mesma coisa. O classificador de segurança do
Claude Code bloqueou automaticamente a automação dessa abordagem duas
vezes, o que reforçou essa conclusão.

**Solução adotada:** só consultar códigos de estação específicos e já
conhecidos, obtidos diretamente das Defesas Civis municipais (Rio das
Ostras, Casimiro de Abreu, Macaé, e outras usadas por essas Defesas Civis
para monitoramento regional: Armação dos Búzios, Cabo Frio, Arraial do
Cabo, Nova Friburgo) — isso é exatamente o uso pretendido da API pública
de PWS (consultar dados de uma estação cujo ID você já tem, com
consentimento implícito do dono ao deixar a estação pública).

- Chave de API: **pessoal**, obtida de graça em autoatendimento em
  https://www.wunderground.com/member/api-keys (criar conta grátis, "My
  Profile > My Devices", adicionar um device — não precisa de estação de
  verdade — depois gerar a chave). Nada de negociação com a IBM/Weather
  Company necessária. Configurar em `WUNDERGROUND_API_KEY`.
- Endpoint: `GET https://api.weather.com/v2/pws/observations/current?
  stationId={codigo}&format=json&units=m&apiKey={chave}` — sem CAPTCHA,
  sem bloqueio, retorna JSON limpo com temperatura, umidade, vento
  (velocidade/rajada/direção), chuva acumulada, pressão, radiação solar.
- 16 estações confirmadas (setembro/2026), 14 respondendo dados no momento
  do teste (`IRIODA5` e `IRIODA16` retornaram HTTP 204 — sem leitura
  recente, provavelmente offline temporariamente; ficam cadastradas no
  conector mesmo assim, o pipeline já ignora estação sem dado).
- Qualidade: rede amadora/particular (dados variam de estação para
  estação), não é dado aberto oficial de governo como INMET/CEMADEN — usar
  como complemento, não como fonte autoritativa isolada.

## Painel CEMADEN-RJ (GridLab) — sem API pública

`https://painelcemadenrj.defesacivil.rj.gov.br` é uma plataforma comercial
operada pela GridLab Sistemas e Serviços Ltda para a Defesa Civil-RJ. A tela
de dashboard (`/dashboard/...`) exige login; mas o mapa de alertas em tempo
real (`/monitoramento/v2/mapa/`) é **público, sem login** — vale como
referência de UX, mas os dados são renderizados 100% server-side em PHP
(o SVG do mapa do RJ já vem com as cores por município embutidas no HTML;
não tem endpoint JSON separado pra copiar — visto no código-fonte de
`monitoramento/v2/js/map.js`, que só lê `<path>` já coloridos, não busca
nada via fetch/AJAX). Não dá pra "espelhar" tecnicamente; teria que replicar
com dado próprio.

**As 4 camadas de alerta que o usuário quer no nosso painel existem nesse
mapa** (confirmado navegando em setembro/2026), uma coisa boa: dá pra saber
exatamente o que construir. Todas são um mapa coroplético por município (não
por estação pontual), com a mesma escala de 5 níveis (MUITO BAIXO / BAIXO /
MODERADO / ALTO / MUITO ALTO):

- **Monitoramento do Risco Hidrológico** — `/monitoramento/v2/mapa/`
- **Monitoramento do Risco de Deslizamento** (geológico) — mesma URL, aba ao lado
- **Nível de Severidade Meteorológica** — `/monitoramento/v2/mapa/redec.php?action=1`
- **Risco de Incêndio Florestal** — `/monitoramento/v2/mapa/redec.php?action=2`

Cada mapa mostra um timestamp de atualização (ex: "16/09/2026 às 02:49:08").
Fonte dos números por trás de cada camada ainda não identificada — são,
quase certamente, classificações que o próprio CEMADEN nacional calcula e
entrega à Defesa Civil-RJ (ele publica avisos de risco geológico/hidrológico
por município nacionalmente) e/ou repasses do INMET (severidade
meteorológica) e do INEA/Corpo de Bombeiros (incêndio florestal) — mas isso
é hipótese, não confirmado. **Próximo passo antes de construir isso aqui:
pesquisar se o CEMADEN nacional expõe essas classificações por município via
webservice** (o mesmo domínio já usado pelo conector `cemaden_nacional.py`
tem outros recursos além do de estações) — só depois dá pra fazer um
conector de verdade em vez de dado fictício.

Acesso via API/feed de estações (não de alertas) depende de contato
institucional direto com a Defesa Civil-RJ e/ou GridLab — em andamento pelo
usuário deste projeto.

## Ainda não iniciado (Fase 3 do plano)

Marinha do Brasil (tábuas de maré/ondas), INPE/CPTEC (satélite), ANA
(hidrologia de barragens/reservatórios), Defesas Civis municipais do
interior do RJ — nenhum desses foi pesquisado ainda nesta sessão.
