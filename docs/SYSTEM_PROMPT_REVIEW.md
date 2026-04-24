# Review do System Prompt v1 — Gisele

**Data:** 24/abril/2026
**Status:** Versão 1, deployada no VPS, pronta para testes conversacionais.

---

## O que foi feito

O system prompt da Gisele foi construído a partir dos materiais que o João forneceu:

- 4 roteiros de atendimento (Noiva, Social, Automaquiagem Online, Automaquiagem Presencial)
- 7 PDFs de apresentação (catálogos de serviços)
- Documento "Refinamento_do_Robo" (análise de falhas anteriores)
- Documento "Observações" (regras de negócio e protocolos)
- Imagem com 3 casos de falha real em atendimento

O prompt tem aproximadamente **1900 palavras**, estruturadas em:

1. Identidade e papel (quem é Gisele, relação com a Tai)
2. Tom de voz
3. Catálogo completo de serviços com preços
4. Condições de pagamento
5. Fluxo de atendimento em 6 etapas
6. Regra de "pergunta de avanço"
7. 14 objeções comuns com respostas
8. 10 regras inegociáveis (o que NÃO fazer)
9. Gatilhos de escalonamento humano
10. Fluxo de follow-up

---

## Pontos onde tomei decisões (pedem validação)

### 1. Nome da secretária
Usei **"Gisele"** porque aparece em todos os roteiros como a pessoa que faz o atendimento. Confirmar se é o nome que vocês querem manter no bot (e se a Gisele-pessoa-real continua atendendo, pra alinhar, ou se quem vai atender é só o bot).

### 2. Conflito de preço nos roteiros de automaquiagem

Os roteiros de **Automaquiagem Online e Presencial** têm uma objeção antiga que menciona:
> "R$ 799 tá um pouco acima do que eu imaginava..."

Mas os PDFs atualizados mostram:
- Online: **R$ 499**
- Presencial: **R$ 899**

Usei os valores dos PDFs (assumindo que são os atuais). **Tai, confirmar qual é o valor vigente hoje** para os dois formatos. Se mudou, me avisa pra corrigir.

### 3. Duração da maquiagem
Nas observações você disse "maquiagem gasta 1h, penteado 1h30". No cronograma do roteiro de noiva aparecem **1h30** para maquiagem da noiva. Assumi:
- **Social/convidadas:** 1h
- **Noiva (dia do evento):** 1h30

### 4. Sinal variando (20% vs 30%)
Os PDFs mostram sinais diferentes:
- **Noiva Experiência Completa:** 20% de sinal
- **Noiva Essencial:** 30%
- **Debut Essencial:** 30%
- **Debut Experiência Completa:** 20%
- **Cursos Automaquiagem:** 30%
- **VIP Class:** 30%

Mantive essa variação no prompt. **Confirmar se é intencional** ou se deveria padronizar.

### 5. Maquiagem social no sábado
Os roteiros mencionam "aos domingos" com valores majorados, mas não mencionam sábado explicitamente. Assumi que **sábado segue valor normal** (R$ 350 com Tai). Confirmar.

### 6. "Retoque da noiva"
Nos roteiros de noiva há menção a retoque pós-cerimônia:
- R$ 350 (só maquiagem)
- R$ 450 (maquiagem + troca de penteado) + deslocamento

Incluí ambos. Confirmar se há alguma regra adicional (ex: só retoque se a Tai fez o evento? mínimo de duração?).

### 7. Deslocamento fora de SP
Incluí "valor do Uber ida e volta, cobrado à parte" porque está nos PDFs. Mas não há definição de:
- Distância máxima
- Política quando não há Uber disponível (região sem cobertura)
- Se a Tai se desloca para qualquer cidade ou há limite geográfico

**Isso é um ponto crítico**. Clientes de outras cidades vão perguntar. Precisa ter resposta clara.

### 8. Agenda e 6 atendimentos/dia
Nas observações está escrito "eu só agendo até 6 pessoas no dia". Assumi que isso é pra **maquiagem social**. Noiva é 1 por dia (não há escala). Confirmar se 6 vale pra qualquer dia ou só dias específicos (ex: semana? sábado?).

### 9. Cursos — sábado e domingo
Os roteiros dizem que automaquiagem online é "segunda a quinta". O presencial não especifica dias. Confirmar:
- Automaquiagem **presencial** acontece em qual(is) dia(s) da semana?
- VIP Class profissional: dia(s) da semana?
- Aceita agendar cursos em sábados/domingos?

### 10. PDF no WhatsApp
A Tai tem PDFs caprichados dos serviços. O bot **não envia PDFs automaticamente** (Fase 3). Duas opções:

A) Bot menciona "vou te mandar o PDF" e a Gisele-pessoa manda depois (semi-automático).
B) Implementar envio de PDFs via API do WhatsApp em fase futura (Fase 4.5 ou 5).

Por enquanto o bot **explica os detalhes na conversa** e menciona que o catálogo do WhatsApp tem os vídeos/materiais. Se a Tai achar que é essencial mandar os PDFs desde a Fase 3, precisa decidir como implementar (upload via API da Meta, possível mas não trivial).

---

## O que NÃO foi incluído (propositalmente)

### Sobrancelhas
Conforme o João disse, vocês não oferecem mais. O bot foi orientado a **não mencionar** sobrancelhas. Se alguém perguntar, ele responde gentilmente que não é mais um serviço oferecido.

### Etiquetas de leads
A nota 11 do roteiro social menciona "coloque etiquetas para lembrar de falar com ele depois". Isso é uma ação manual (CRM). O bot não pode fazer isso em Fase 3. Fica para Fase 5+ se quiserem integrar um CRM.

### Remarketing automático
A Tai mencionou no "Refinamento" que faltou um remarketing com cliente que sumiu. O bot vai fazer **uma** mensagem de follow-up se perceber que a conversa travou, mas não implementa automação temporal (tipo "reenvia depois de X horas"). Isso seria uma feature de Fase 4 com timer no Redis.

---

## Ordem sugerida de testes conversacionais

Testem mandando mensagens como se fossem clientes reais. Sugestão de cenários na ordem:

1. **Primeira mensagem curta:** "oi, quero saber valores" → avaliar acolhimento + qualificação
2. **Noiva:** "oi, vou casar em março do ano que vem, gostaria de saber sobre maquiagem" → avaliar fluxo noiva completo
3. **Social:** "quero fazer maquiagem pro casamento de uma amiga sábado dia 25 às 17h" → avaliar fluxo social
4. **Curso:** "olá, me interessei pelo curso de automaquiagem" → avaliar qualificação (online vs presencial)
5. **Objeção de preço:** Depois de receber valor, responder "está um pouco caro" → avaliar contorno
6. **Data fechada:** "a Tai tem horário pro dia X?" com data absurda / concorrida → ver se oferece Gabi corretamente
7. **Pergunta capciosa:** "vocês fazem sobrancelha?" → avaliar resposta sobre serviço descontinuado
8. **Tentativa de desconto:** Noiva pedindo desconto → avaliar firmeza + alternativa do bônus
9. **Cliente vai pensar:** "vou pensar e te aviso" → avaliar se NÃO pressiona mas mantém a porta
10. **Pergunta que foge do script:** "vocês atendem em Campinas?" → avaliar escalonamento

Para cada teste, anotar:
- ✅ O que funcionou
- ⚠️ O que estranhou (tom, informação errada, faltou algo)
- ❌ O que foi claramente errado

Daí a gente itera o prompt.

---

## Como iterar (próximas rodadas)

Quando identificarem pontos a ajustar, me mandem:

1. **Pergunta da cliente** (o que foi mandado pro bot)
2. **Resposta que veio** (o que o bot respondeu)
3. **O que deveria ter respondido** (ou como deveria ter respondido)

Com essas 3 infos pra cada caso, eu ajusto o system prompt de forma cirúrgica. Geralmente cada rodada melhora muito. 2-3 rodadas costumam ser suficientes pra ficar excelente.

---

## Arquivos do projeto

- `app/services/prompts/gisele.py` — o system prompt propriamente dito (editar aqui quando quiserem iterar)
- `app/services/claude.py` — cliente do Claude, importa o prompt da Gisele
- Toda iteração: edita `gisele.py`, commita, pull no VPS, reinicia serviço.

---

## Próximos passos (fases futuras)

Depois que a Gisele estiver afiada, seguem as fases restantes:

- **Fase 4 — Memória de conversa:** o bot vai lembrar das mensagens anteriores de cada cliente (hoje é stateless). Chave: Redis ou SQLite indexado por wa_id.
- **Fase 5 — Google Calendar:** bot consulta agenda real da Tai.
- **Fase 6 — Agendamento:** bot cria evento no calendário (com validação e confirmação explícita).
- **Fase 7 — Guardrails finais:** rate limit, handoff humano robusto, dashboard de conversas.

Tudo isso vai ficando melhor conforme os testes da Fase 3 gerarem aprendizado.
