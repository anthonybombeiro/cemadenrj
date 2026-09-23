# Referência visual — Rede Salvar (CEMADEN nacional)

> Levantado em 2026-09-23 direto do código-fonte (JS/CSS) da página autenticada
> `salvar.cemaden.gov.br` (login feito pelo diretor da CEMADEN-RJ no navegador,
> nunca por automação) — não é achismo de tela, são os valores exatos extraídos
> de `common-pcd_table.ALL.2.8.68-min.js`, `meteorologia-table.ALL.2.8.68-min.js`
> e os CSS `datatables_custom-min.css`/`common_pcd_menu-min.css`. Ver também a
> memória `rede-salvar-cemaden` (achado da API REST JSON por trás da tela).
>
> Objetivo: extrair convenções visuais e de UX já validadas por um sistema
> nacional de referência do próprio CEMADEN, pra aplicar (com adaptação, não
> cópia 1:1) nas abas **Precipitação** e **Dados Meteorológicos** do nosso
> painel (`frontend/src/components/DataTable.tsx`).

## 1. Cor por rede/fonte (`id_rede` → cor)

Função `formatRedeRender(a)` — cor aplicada no texto da coluna "Rede":

| id_rede | slug   | Nome        | Cor       |
|---|---|---|---|
| 1  | ana        | ANA         | `#033600` (verde escuro) |
| 3  | inmet      | INMET       | `#817C13` (oliva) |
| 9  | inea       | INEA        | `#007261` (teal) |
| 11 | cemaden    | CEMADEN (nacional) | `#0047F6` (azul vivo) |
| 13 | cemaden-rj | CEMADEN-RJ  | `#720066` (roxo) |
| 14 | pcj        | PCJ         | `#543C18` (marrom) |
| 12 | simepar    | SIMEPAR     | `#F712D4` (magenta) |
| 15 | codesal    | CODESAL     | `#A91D3A` (vinho) |
| 16 | sjc        | SJC         | `#FF6500` (laranja forte) |
| 18 | cepdec-es  | CEPDEC-ES   | `#000000` (preto, cor padrão/fallback) |

**Ideia pro nosso painel:** hoje `SOURCE_LABELS` (`frontend/src/lib/api.ts`) só
mapeia slug→rótulo. Podemos somar `SOURCE_COLORS: Record<string,string>` no
mesmo espírito — uma cor fixa e distinta por fonte (`inmet`, `alerta_rio`,
`wunderground`, `plugfield`, `cemaden_rj`, `cemaden_mctic`, `niteroi`, ...) e
usar no texto/badge da coluna "Fonte" da tabela e nos marcadores do mapa.

## 2. Atraso (última recepção de dados) — 4 faixas

Função de formatação da coluna "Data" (`dataHoraRenderFromMilis`/render de data
com `moment().isBefore(...)`):

| Faixa | Cor | Ícone |
|---|---|---|
| < 4 horas (em dia) | sem estilo especial | nenhum |
| > 4h e < 120h | `#1d3e5e` (azul-marinho escuro) | `delayed.png` |
| > 120h e < 30 dias | `#808000` (oliva escuro) | `delayed.png` |
| > 30 dias | `purple` | `delayed.png` |
| Dado no futuro (clock skew) | `#8B0000` (vermelho escuro) | — |

**Ideia pro nosso painel:** hoje a coluna "Atualização" (`updated_at`/coluna
`updated` no `DataTable.tsx`) só mostra a data/hora crua, sem indicar
visualmente atraso. Dá pra portar essa lógica de 3-4 faixas coloridas —
ajustando os limiares pra nossa cadência real (nossas fontes atualizam a cada
~15min–1h, não faz sentido usar os mesmos cortes de "4h/120h/30 dias" do
Salvar, que mistura redes de cadência bem mais lenta tipo hidrológicas ANA).
Sugestão de limiares pro nosso caso: **< 1h** normal, **1h–6h** atenção
(âmbar), **6h–24h** atrasado (laranja escuro), **> 24h** muito atrasado
(vermelho/roxo).

## 3. Precipitação em 24h — ícone por faixa

Função `acc24hrRender(a)`:

| Faixa (mm em 24h) | Ícone |
|---|---|
| 10–30mm | `rainYellow.png` |
| 30–70mm | `rainOrange.png` |
| ≥ 70mm | `rainRed.png` |
| < 10mm | nenhum ícone |

**Ideia pro nosso painel:** já temos `acumulado_24h_mm` no endpoint
`/api/stations/precipitacao/` — dá pra somar uma coluna/ícone de "nível de
chuva" na tabela de Precipitação usando essas MESMAS 3 faixas (10/30/70mm),
que já são o padrão de facto do CEMADEN — evita inventar limiar próprio.

## 4. Nível de alerta (eventos) — cores puras

CSS (`datatables_custom-min.css`/`common_pcd_menu-min.css`):
```css
.em_alerta_m  { background-color: yellow; }  /* Moderado */
.em_alerta_a  { background-color: orange; }  /* Alto */
.em_alerta_ma { background-color: red;    }  /* Muito Alto */
```

**Atenção — não confundir com nosso `RISK_LEVEL_COLORS` atual**
(`frontend/src/lib/api.ts`): o nosso já usa uma paleta de 5 níveis
(`muito_baixo/baixo/moderado/alto/muito_alto`) copiada da tela oficial de
Avisos Hidrológico/Geológico/Meteorológico da Defesa Civil-RJ
(`#28a745/#ffff19/#ffc107/#bd2130/#6f42c1`) — é uma escala DIFERENTE e já
oficial pro nosso caso de uso (`RiskAlert`), não trocar. A escala 3-cores do
Salvar (amarelo/laranja/vermelho puro) é específica do evento por-estação
(`eventos` da PCD), útil só se um dia importarmos esse dado específico.

## 5. Códigos de evento/alerta por estação (campo `eventos` da API)

Função `eventosRender(eventos, tipoRender)` — cada PCD pode ter múltiplos
eventos ativos simultâneos, cada um com tipo de risco + severidade:

| Código | Tipo | Severidade |
|---|---|---|
| 1 | Movimento de Massa | Muito Alto |
| 2 | Enxurrada | Moderado |
| 3 | Inundação | Moderado |
| 4 | Movimento de Massa | Moderado |
| 5 | Movimento de Massa | Alto |
| 7 | Inundação | Alto |
| 8 | Inundação | Muito Alto |
| 9 | Enxurrada | Alto |
| 10 | Enxurrada | Muito Alto |
| 14 | Risco Hidrológico | Moderado |
| 15 | Risco Hidrológico | Alto |
| 16 | Risco Hidrológico | Muito Alto |

Cada tipo de risco tem uma letra-badge (mostra até 4 letras juntas se a
estação tiver múltiplos tipos de evento ativos ao mesmo tempo — ex: "HM" nas
estações de Nova Friburgo = Hidrológico + Movimento de Massa):
- `H` = Risco Hidrológico
- `M` = Movimento de Massa
- `E` = Enxurrada
- `I` = Inundação

Cor do badge = a mesma escala de 3 cores da seção 4 (amarelo/laranja/vermelho
conforme a maior severidade entre os eventos daquele tipo).

**Relevância pro nosso projeto:** essa é uma classificação de risco
por-estação MUITO mais granular que a nossa (que hoje só tem `RiskAlert` a
nível de REDEC/município, ver `cemaden_rj_alertas.py`). Se algum dia
integrarmos a Rede Salvar de verdade (pendente, ver memória
`rede-salvar-cemaden`), esse esquema de 4 tipos × 3 severidades é uma boa
referência pronta pra modelar nosso futuro `AlertRule`/`AlertEvent`
(Fase 2 do projeto, ainda com 0 regras configuradas).

## 6. Sufixo de tipo de estação (`id_tipoestacao`)

Função `nomeRender`:

| id_tipoestacao | Sufixo | Tipo |
|---|---|---|
| 1  | `[A/B]` | Pluviométrica |
| 3  | `[H]`   | Hidrológica |
| 4  | `[U]`   | Agrometeorológica |
| 5  | `[C]`   | Acqua (qualidade da água?) |
| 10 | `[G]`   | Geotécnica |

**Correção pro nosso `cemaden_rj_pluviometros.py`:** a mesma numeração
(`tipoestacao`) usada em `getJson2.php` (nossa fonte atual do conector
`cemaden_mctic`) bate com essa tabela — confirma que `tipoestacao==1` é
realmente Pluviométrica (o filtro que já usamos está certo). A dúvida que
tínhamos sobre o tipo `4` (antes registrada como "unclear" no docstring do
conector) está resolvida: é **Agrometeorológica**, não geotécnica nem
hidrológica — não precisamos incluir no filtro de chuva mesmo assim.

## 7. Indicador "monitorado" (ícone de olho)

Ícone `glyphicon-eye-open` mostrado SÓ quando `monitorado == true`, com
tooltip = data de início do monitoramento (`data_monit` formatada). Se
`monitorado == false`, a célula fica vazia (sem ícone).

**Ideia pro nosso painel:** não temos hoje um conceito de "estação
monitorada vs. cadastrada mas não usada" — não é prioridade replicar agora,
mas é um padrão limpo pra sinalizar estações que existem na base mas não
entram em nenhum cálculo/alerta.

## 8. Exportação de tabela

Botões via extensão **DataTables Buttons** (biblioteca padrão, mesma que já
poderíamos usar): "Copiar" (área de transferência), "CSV", "Excel" — exportam
exatamente as colunas visíveis da tabela renderizada (respeitando filtro e
ordenação atuais), mais os campos ocultos `id_estacao`/`id_tipoestacao`.

**Ideia pro nosso painel:** as tabelas de Precipitação e Dados Meteorológicos
(`DataTable.tsx`) hoje não têm exportação nenhuma. Adicionar CSV/Excel é uma
melhoria de baixo custo e alto valor operacional (útil pra Defesa Civil gerar
relatório rápido) — já estava listado como pendência de Fase 3
("relatórios exportáveis") no plano original do projeto.

## 9. Outros detalhes de UX úteis

- Valor acumulado ausente pra uma janela = célula com `"---"` e tooltip
  "Sem dados para o período" (em vez de célula vazia ou "0") — evita
  confundir "não choveu" com "não tem dado". Já fazemos algo parecido
  (`va == null` tratado à parte no sort do `DataTable.tsx`), mas vale conferir
  se a tabela renderiza visualmente distinto de "0".
- Filtros persistem na URL como query params (`?nets=11-9-1-3-13&uf=RJ...`) —
  permite compartilhar um link já filtrado. Não é prioridade agora, mas é um
  padrão bom pra UX de painel operacional.
- Município (coluna "Cidade") é clicável e filtra a tabela por aquele
  município direto (tooltip "Clique para filtrar") — interação rápida sem
  precisar abrir o dropdown.
