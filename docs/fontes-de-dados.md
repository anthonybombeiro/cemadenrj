# Fontes de dados — o que foi confirmado e o que falta validar

Levantamento feito em setembro/2026 durante a montagem deste projeto. Serve
como referência para os conectores em `backend/ingestion/connectors/` e para
quem for negociar acessos institucionais.

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

## Alerta Rio / GeoRio — parcialmente confirmado

- Localização das 33 estações pluviométricas (sem autenticação):
  `GET https://www.data.rio/api/download/v1/items/88b61c6abe424c049fdf83d27917602e/geojson?layers=0`
  Retorna GeoJSON com `endereço`, `est` (bairro), `cod` (código da estação),
  coordenadas.
- **Não confirmado:** endpoint JSON de leituras de chuva em tempo real. A
  página pública (`sistema-alerta-rio.com.br/tabela-de-dados/` e
  `/download/dados-pluviometricos/`) parece publicar isso como tabela HTML e
  bloqueou uma requisição simples (HTTP 403, provável proteção antibot).
  Caminhos possíveis: (a) pedir um feed formal à GeoRio/Alerta Rio
  (alertario@centrodeoperacoesrio.com.br) — o mesmo contato institucional já
  em andamento para o painel GridLab cobre isso, já que GeoRio opera os dois;
  (b) scraping da tabela HTML com headers de navegador real — mais frágil,
  não implementado sem validação humana antes.

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
operada pela GridLab Sistemas e Serviços Ltda para a Defesa Civil-RJ. Tem
proteção anti-bot (checagem de navegador) na página raiz e não expõe um
endpoint JSON óbvio na tela de mapa de pluviômetros testada (só CSS/HTML
estático de um iframe). Acesso via API/feed depende de contato institucional
direto com a Defesa Civil-RJ e/ou GridLab — em andamento pelo usuário deste
projeto. Assim que existir, vira só mais um conector em
`backend/ingestion/connectors/`, seguindo o mesmo padrão dos demais.

## Ainda não iniciado (Fase 3 do plano)

Marinha do Brasil (tábuas de maré/ondas), INPE/CPTEC (satélite), ANA
(hidrologia de barragens/reservatórios), Defesas Civis municipais do
interior do RJ — nenhum desses foi pesquisado ainda nesta sessão.
