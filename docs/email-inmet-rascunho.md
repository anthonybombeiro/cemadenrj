# Rascunho de e-mail — solicitação de acesso à API de tempo real do INMET

**Para:** inmet@inmet.gov.br (contato geral oficial do INMET)
**Cc (se quiser tentar diretamente):** alex.oliveira@inmet.gov.br — encontrado como
contato do coordenador da COPREM (Coordenação de Planejamento e Operação da Rede
Meteorológica) em uma busca na web. **Não confirmei esse e-mail em uma fonte
oficial do INMET** (pode estar desatualizado) — por isso o corpo do e-mail já
menciona "COPREM" explicitamente, para ajudar o pessoal do atendimento geral a
rotear corretamente mesmo que o Cc não chegue a essa pessoa específica.
**Assunto:** Solicitação de acesso à API de dados horários em tempo real (rede de
estações automáticas) — uso institucional CEMADEN-RJ

---

Prezados,

Meu nome é [SEU NOME], e trabalho com [SEU CARGO/INSTITUIÇÃO — ex: "a Defesa
Civil do Estado do Rio de Janeiro (CEMADEN-RJ)"].

Estamos desenvolvendo um painel de agregação de dados meteorológicos e
hidrológicos para o estado do Rio de Janeiro, com o objetivo de apoiar o
monitoramento e a tomada de decisão da Defesa Civil estadual (CEMADEN-RJ) em
situações de risco de desastres naturais relacionados a chuva.

Já utilizamos o endpoint público de metadados de estações automáticas
(`https://apitempo.inmet.gov.br/estacoes/T`) para localizar as estações do
INMET no RJ, e identificamos que o endpoint de séries horárias
(`https://apitempo.inmet.gov.br/token/estacao/{data_inicio}/{data_fim}/
{codigo_estacao}/{token}`) exige um token de acesso, mas não encontramos um
processo de autoatendimento para solicitá-lo (o BDMEP, por exemplo, atende
apenas pedidos pontuais de dados históricos por e-mail, não ingestão contínua
via API).

Gostaríamos de solicitar, se possível:
1. Um token de API válido para o endpoint acima, para uso automatizado e
   contínuo (consulta programada a cada 10-15 minutos) restrito às estações
   do estado do Rio de Janeiro;
2. Ou, alternativamente, orientação sobre o processo correto para obter esse
   acesso, caso não seja essa a via adequada para uso institucional.

Ficamos à disposição para fornecer mais detalhes sobre o projeto ou assinar
eventuais termos de uso que sejam necessários.

Desde já agradecemos a atenção.

Atenciosamente,
[SEU NOME]
[SEU CARGO / INSTITUIÇÃO]
[SEU E-MAIL / TELEFONE DE CONTATO]

---

**Antes de enviar:**
- Preencha os campos entre colchetes.
- Confirme se `alex.oliveira@inmet.gov.br` ainda é válido antes de usar como
  Cc direto (ou remova e envie só para o contato geral — o corpo já cita
  COPREM para ajudar no roteamento interno).
- Considere enviar a partir de um e-mail institucional (@defesacivil.rj.gov.br
  ou similar) em vez de um e-mail pessoal — pedidos de acesso a dados
  governamentais tendem a ser levados mais a sério com identificação
  institucional clara.
