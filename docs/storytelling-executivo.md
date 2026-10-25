<!-- Narrativa executiva do MD Bank AI. Base: [arquitetura.md](arquitetura.md) e [diagrama](img/arquitetura.drawio.png). Voltar: [README](../README.md) -->

# MD Bank AI: narrativa executiva

> Público-alvo: diretoria, heads de tecnologia, produto, negócios e inovação. Duração: ~15 min, 10 slides.
> Fonte técnica: `docs/arquitetura.md` (análise estática do código; os containers não foram executados).

## 0. Premissas e régua de evidência

O briefing deixou em branco o contexto de negócio, as métricas e o objetivo da apresentação. Adotei as premissas abaixo e, a pedido, **dados fictícios** para ilustrar o impacto (seção 0.1). **Todo número fictício leva a marca [fictício]. Substitua pelos dados reais do banco antes de apresentar como fato.**

| Item | Premissa adotada | Origem |
|---|---|---|
| Contexto | Banco digital. Jornada de entrada: abrir conta e solicitar cartão de crédito | arquitetura.md, "O que é" |
| Maturidade | **PoC** com dados fictícios (`db.json`) | arquitetura.md, "Maturidade" |
| Resultados | Nenhuma métrica real existe. **Cenário fictício** na seção 0.1 | ausência no repositório + sua instrução |
| Objetivo da apresentação | Aprovar um piloto controlado (preparação + piloto) | **premissa minha**, confirmar |
| Valores de investimento e metas | **[fictício]**, ilustrativos (seção 0.1) | criados para esta narrativa |

**Régua usada em todo o documento**

| Selo | Significado | O que existe hoje |
|---|---|---|
| **Implementado** | Existe no código da PoC e é descrito na documentação. Não foi medido em uso real | Conversa, roteamento, agentes, regras na ferramenta, rastreio ponta a ponta, mascaramento de CPF |
| **Estimativa** | Derivada de dados reais do banco. Exige baseline | Nenhuma |
| **Hipótese** | Ganho plausível, a validar no piloto | Custo, tempo, conversão, produtividade |
| **[fictício]** | Número inventado para ilustrar a narrativa. Não é medição nem estimativa | Toda a seção 0.1 e os valores numéricos dos slides e do business case |

Os pontos de atenção da documentação que a liderança precisa conhecer ficam no slide 8 e no apêndice. Eles não são escondidos.

### 0.1 Cenário fictício de referência (MD Bank, jornada "conta + cartão")

Usado nos slides 1, 3, 7, 9 e 10 e no Entregável E. Os números são coerentes entre si, mas **inventados**.

| Parâmetro | Hoje (baseline) [fictício] | Com agentes, cenário base [fictício] |
|---|---|---|
| Jornadas iniciadas por mês | 20.000 (240.000/ano) | igual |
| Taxa de conclusão (conta e cartão emitidos) | 55% | 60% (+5 p.p.) |
| Tempo mediano para concluir | 14 min, 6 a 7 telas | 5 min, conversa de ~3 trocas |
| Jornadas que precisam de atendente humano | 25% | 12% |
| Custo por contato humano | R$ 30 | R$ 30 |
| Custo digital fixo por jornada (infraestrutura) | R$ 1,50 | R$ 1,50 |
| Custo de LLM por conversa | não se aplica | R$ 0,60 |
| **Custo médio por jornada iniciada** | **R$ 9,00** (25% × 30 + 1,50) | **R$ 5,70** (12% × 30 + 1,50 + 0,60) |
| Satisfação (CSAT, escala 1 a 5) | 4,1 | meta: ≥ 4,2 |
| Margem incremental no 1º ano por jornada concluída | R$ 90 | R$ 90 |

Custos do programa [fictício]: **R$ 1,2 mi** de construção (preparação + piloto: engenharia R$ 700 mil, integração com sistemas R$ 300 mil, segurança, privacidade e jurídico R$ 200 mil) e **R$ 600 mil/ano** de operação (sustentação, avaliação de qualidade, observabilidade). O custo de LLM já está no custo por jornada, para não contar duas vezes.

---

## Entregável A: Tese executiva

Hoje, quem quer "um cartão de crédito" precisa saber que antes precisa de uma conta, onde está cada formulário e em que ordem preenchê-lo. O esforço de navegar entre processos fica com o cliente, e cada novo produto aumenta essa complexidade. A arquitetura agêntica inverte a lógica: o cliente diz o que quer, e uma equipe digital de especialistas, coordenada por um orquestrador, identifica o que falta, executa as etapas na ordem certa, dentro das regras do banco, e registra tudo de forma auditável. A PoC comprova o mecanismo em dois produtos (conta e cartão) com dados fictícios. O potencial está em menor esforço do cliente, menor custo por jornada concluída e lançamento mais rápido de novas jornadas, reaproveitando capacidades já construídas. **Nenhum ganho foi medido ainda.** Propomos um piloto controlado, com critérios de sucesso definidos antes de começar, para transformar hipóteses em números.

---

## Entregável B: Storytelling completo

**Protagonista:** a cliente que quer um cartão de crédito. **Mecanismo:** a arquitetura. Ela nunca é o herói da história.

### SCQA

| | Conteúdo |
|---|---|
| **Situação** | Jornadas digitais bancárias são formulários e telas separados por produto. O cliente já aprendeu a conviver com isso. |
| **Complicação** | Uma intenção simples ("quero um cartão") atravessa mais de um domínio (conta, depois cartão). O cliente precisa descobrir a ordem, repetir dados e desistir se errar. Cada produto novo é mais uma tela e mais integração. |
| **Questão** | Como permitir que o cliente peça o resultado que deseja, sem conhecer o caminho, **sem abrir mão do controle que um banco exige**? |
| **Resposta** | Uma camada conversacional que entende a intenção, aciona agentes especialistas por padrões abertos e executa as ações através das regras do banco, com rastreabilidade completa. Começamos por um piloto pequeno e medido. |

### Arco narrativo

1. **Começo (o desafio):** a cliente chega com um objetivo e encontra um mapa de processos que ela tem de decifrar.
2. **Desenvolvimento (a oportunidade e a nova experiência):** o paradigma muda de "conheça o processo" para "diga o que quer". A mesma jornada, em uma conversa.
3. **Ponto de virada (como é possível):** não é "um chatbot mais esperto". É uma equipe de especialistas coordenada, que só age pelas ferramentas e regras do banco. É isso que diferencia de um chatbot comum e de uma automação fixa.
4. **Conclusão (a decisão):** o ganho é uma hipótese razoável, não um fato. Pedimos recursos para **provar ou refutar** a hipótese com risco limitado.

### As cinco perguntas

| Pergunta | Resposta em uma frase | Slides |
|---|---|---|
| Por que mudar? | A complexidade das jornadas recai sobre o cliente e cresce a cada produto | 1, 2 |
| O que muda? | O cliente expressa o objetivo e a equipe digital executa as etapas | 3, 4 |
| Como viabilizamos? | Orquestrador, agentes especialistas e acesso padronizado às regras do banco | 5, 6 |
| Qual o valor? | Esforço, custo e prazo menores. Hipóteses a validar | 7 |
| Qual a decisão? | Aprovar preparação e piloto controlado, com critérios de sucesso prévios | 8, 9, 10 |

---

## Entregável C: Roteiro de apresentação (10 slides, ~15 min)

### Slide 1. Ato 1: "Para pedir um cartão, a cliente precisa conhecer o nosso banco por dentro" *(1 min 30)*

- **Mensagem central:** a complexidade interna dos processos é transferida para o cliente.
- **Storytelling:** abertura. Apresenta a protagonista e o atrito, sem tecnologia.
- **Visual:** uma linha do tempo de uma jornada tradicional: tela de produtos → "tenho conta?" → formulário de conta → confirmação → formulário de cartão → escolha do tipo. Marcar os pontos de abandono possível com ícones de "?". Ao lado, um funil mensal **[fictício]**: 20.000 jornadas iniciadas → 11.000 concluídas (55%) → 9.000 abandonadas (45%); 5.000 (25%) precisam de atendente; tempo mediano 14 min. Rodapé: *"Dados ilustrativos. Substituir pelos números reais do banco."*
- **Roteiro:** "Imagine uma cliente que só quer um cartão. Para conseguir, ela precisa descobrir que o cartão depende de uma conta, que a conta tem seu próprio cadastro e que existe uma ordem a seguir. Ela não quer navegar pelo nosso banco, quer o resultado. Nos números ilustrativos deste cenário, de cada 20 mil jornadas iniciadas por mês, 9 mil não terminam, e uma em cada quatro precisa de um atendente. Cada produto que lançamos adiciona mais uma porta ao corredor."
- **Conclusão do slide:** *"O cliente quer um resultado; hoje entregamos um mapa."*

### Slide 2. Ato 2: "A oportunidade: o cliente diz o que quer, o banco descobre como fazer" *(1 min)*

- **Mensagem central:** mudança de paradigma, de navegar por processos para declarar uma intenção.
- **Storytelling:** se o problema é o mapa, a oportunidade é remover o mapa da frente do cliente.
- **Visual:** duas colunas. À esquerda, "Hoje: o cliente se adapta ao processo". À direita, "Possível: o processo se adapta ao cliente". Uma única frase de exemplo: *"Quero um cartão, meu CPF é …"*.
- **Roteiro:** "A mudança não é estética, é de responsabilidade. Hoje o cliente é o integrador entre nossas áreas. A proposta é que o banco assuma esse papel: o cliente informa a intenção, e o banco descobre quais etapas são necessárias."
- **Conclusão do slide:** *"Quem integra os processos deixa de ser o cliente e passa a ser o banco."*

### Slide 3. Ato 3: "A mesma jornada, em uma conversa" *(2 min)*

- **Mensagem central:** mostrar o antes e o depois no cenário real da PoC: "cartão sem conta".
- **Storytelling:** passa da ideia para algo concreto.
- **Visual:** comparação lado a lado.
  - **Antes:** 6 a 7 passos em telas distintas (ver slide 1).
  - **Depois:** conversa em 3 trocas: (1) "Quero um cartão, meu CPF é …"; (2) "Você ainda não tem conta. Posso abri-la agora? Preciso do seu nome"; (3) "Conta aberta e cartão emitido".
  - Indicadores ao lado **[fictício]**: tempo mediano de 14 min para 5 min; de 6 a 7 telas para ~3 trocas; atendente humano de 25% para 12% das jornadas.
  - Rodapé: *"Cenário implementado na PoC, com dados fictícios. Os tempos e taxas exibidos são ilustrativos e não foram medidos."*
- **Roteiro:** "Este é o caso que construímos. A cliente pede um cartão. O sistema percebe que ela não tem conta, explica isso, abre a conta e só então emite o cartão. A regra 'conta antes de cartão' continua valendo: ela é imposta no sistema do banco, não depende da boa vontade da IA. Se houver tempo, mostrar a demonstração ao vivo."
- **Conclusão do slide:** *"O cliente descreveu o objetivo; o banco executou o caminho."*

### Slide 4. Ato 3: "Por que isso não é um chatbot nem uma automação fixa" *(1 min 30)*

- **Mensagem central:** diferenciais reais da abordagem agêntica.
- **Storytelling:** a plateia já viu chatbots que decepcionaram. É preciso desfazer o paralelo.
- **Visual:** tabela com três colunas.

| | Chatbot de perguntas e respostas | Automação / fluxo fixo | Arquitetura agêntica |
|---|---|---|---|
| Entende pedido livre | Parcial | Não (menu ou formulário) | Sim |
| Executa ações nos sistemas | Normalmente não | Sim, caminho único | Sim, por ferramentas controladas |
| Lida com pedido que cruza produtos | Encaminha | Quebra ou exige nova regra | Seleciona 1 a N especialistas |
| Novo produto | Reescrever respostas | Novo fluxo e nova integração | Novo especialista com capacidades reutilizáveis |
| Risco típico | Resposta errada | Rigidez | Decisão errada. Exige limites e rastreio (slide 8) |

- **Roteiro:** "Um chatbot responde, uma automação repete, um agente decide qual caminho seguir, mas só pode agir pelas ferramentas que damos a ele. Essa autonomia traz um risco que os outros dois não têm. Por isso, o próximo bloco mostra a arquitetura e o seguinte, os controles."
- **Conclusão do slide:** *"Não é um chatbot que fala melhor, é um sistema que executa com limites."*

### Slide 5. Ato 4: "Uma agência digital em que cada especialista conhece o seu balcão" *(2 min)*

- **Mensagem central:** como a arquitetura viabiliza a experiência, explicada por uma analogia.
- **Storytelling:** a pergunta natural depois do slide 4 é "como funciona por dentro?".
- **Visual:** versão simplificada de [arquitetura.drawio.png](img/arquitetura.drawio.png) em quatro camadas, sem portas nem siglas em destaque.
  1. **Cliente** em uma interface de conversa.
  2. **Recepção inteligente** (orquestrador): entende o pedido e decide quais especialistas chamar.
  3. **Mesas especializadas** (agentes): abertura de conta e cartão de crédito.
  4. **Sistema do banco** (regras e dados), acessado por um "guichê padrão".
  - Faixa lateral: **torre de controle** (observabilidade) registrando cada etapa, com CPF mascarado.
- **Analogia:** uma agência. A recepção ouve o cliente e o encaminha à mesa certa, que pode ser mais de uma. Cada mesa é especialista e só atende pelo guichê padrão do banco, onde as regras são aplicadas. Uma torre de controle registra todo o atendimento.
- **Roteiro:** "A recepção entende o pedido em linguagem natural e decide quem chamar. Cada especialista cuida de um assunto. Nenhum deles inventa dados: consultam e gravam pelo guichê padrão do banco, e é nele que a regra 'conta antes de cartão' é garantida. Cada passo fica registrado com um identificador único, e dados sensíveis, como o CPF, são mascarados nos registros."
- **Conclusão do slide:** *"A inteligência decide o caminho, as regras do banco decidem o que é permitido."*

### Slide 6. Ato 4: "Cada peça habilita uma capacidade de negócio" *(1 min 30)*

- **Mensagem central:** componentes técnicos como capacidades. Detalhe completo no Entregável D.
- **Storytelling:** aprofunda o slide anterior para quem pergunta "e o que é cada coisa?".
- **Visual:** 5 cartões, cada um com ícone, capacidade e benefício:
  1. Conversa → "o cliente se expressa livremente".
  2. Roteamento → "o pedido chega ao especialista certo, ou a vários".
  3. Especialistas → "cada domínio evolui de forma independente".
  4. Guichê padrão → "regras e dados do banco acessados de forma única e reutilizável".
  5. Torre de controle → "cada decisão é rastreável".
- **Roteiro:** "O ponto importante para a gestão é a **reutilização**. A capacidade 'abrir conta' vive em um lugar, é acessada por um padrão e serve a qualquer canal ou agente futuro. Quando lançarmos o próximo produto, criamos um especialista novo em vez de reconstruir tudo."
- **Conclusão do slide:** *"Constrói-se a capacidade uma vez e reaproveita-se em cada jornada."*
- **Cuidado ao responder:** hoje, adicionar um agente exige alterar três pontos do supervisor, porque a descoberta dinâmica (BFA) foi construída, mas não é usada (arquitetura.md, ponto 1). A promessa de "novo especialista sem retrabalho" é um **objetivo da fase de preparação**, não um fato.

### Slide 7. Ato 5: "O valor esperado: seis hipóteses que o piloto vai provar ou refutar" *(1 min 30)*

- **Mensagem central:** impacto potencial, com honestidade sobre o que é prova, estimativa e hipótese.
- **Storytelling:** o valor é a razão do investimento, mas a credibilidade vem de não exagerá-lo.
- **Visual:** tabela com selo.

| Oportunidade | Como a arquitetura contribui | Ilustração [fictício] | Selo |
|---|---|---|---|
| Menor esforço do cliente | Uma conversa em vez de várias telas | 6 a 7 telas → ~3 trocas | Implementado (não medido) |
| Menor tempo de resolução | Etapas encadeadas sem retorno do cliente | 14 min → 5 min | Hipótese |
| Menor custo por jornada | Menos atendimento humano em jornadas simples | R$ 9,00 → R$ 5,70 (economia de R$ 792 mil/ano) | Hipótese |
| Mais capacidade de atendimento | Atendimento simultâneo sem fila | Atendente em 25% → 12% das jornadas | Hipótese |
| Mais conversão de intenções em produtos | Menos abandono por atrito | 55% → 60% (+12.000 jornadas concluídas/ano, R$ 1,08 mi de margem) | Hipótese |
| Lançamento mais rápido de novas jornadas | Capacidades reutilizáveis | 2ª jornada com esforço menor que a 1ª (meta a definir) | Hipótese, depende da fase de preparação |

- **Fechamento do slide [fictício]:** ganho anual no cenário base de **R$ 1,87 mi** contra R$ 1,2 mi de construção e R$ 0,6 mi/ano de operação. Faixa entre cenários conservador e otimista: R$ 0,9 mi a R$ 2,8 mi/ano (detalhe no Entregável E). Rodapé: *"Números ilustrativos. Não são medição."*
- **Roteiro:** "Quero ser transparente: o que temos hoje é um mecanismo funcionando com dados fictícios, e os números que mostro são ilustrativos, construídos para dar ordem de grandeza. No cenário base, a economia de custo e a conversão adicional somam cerca de R$ 1,9 milhão por ano. No cenário conservador, isso cai para menos de R$ 1 milhão e o investimento não se paga em três anos. Temos seis hipóteses e um método para medi-las. Esta apresentação pede recursos para obter essas respostas, não para assumi-las."
- **Conclusão do slide:** *"Não pedimos que acreditem no ganho, pedimos o direito de medi-lo."*

### Slide 8. Ato 6: "Autonomia supervisionada, não execução sem controle" *(2 min)*

- **Mensagem central:** os riscos são conhecidos, tratáveis e mapeados com franqueza.
- **Storytelling:** responde à objeção que a plateia já está formulando desde o slide 4.
- **Visual:** duas colunas.
  - **Já na PoC (Implementado):** regras de negócio na ferramenta, não só na instrução da IA; rastreio ponta a ponta com identificador por mensagem; CPF mascarado em registros; controle do volume de conteúdo registrado.
  - **A construir antes do piloto (lacunas conhecidas):** isolamento de memória entre clientes; autenticação entre serviços e restrição de acesso; CPF protegido em repouso; confirmação do cliente (e, quando cabível, aprovação humana) antes de ações que gravam; ordem de execução única e previsível; persistência e resiliência; encaminhamento a atendente humano.
- **Roteiro:** "Distingo autonomia supervisionada de execução sem controle. Na primeira, a IA só age por ferramentas autorizadas, com regras impostas pelo sistema, com rastro e com confirmação nas ações que movimentam o cliente. Na segunda, a IA faz o que acha melhor. Estamos propondo a primeira. A PoC já tem parte desses controles e a documentação lista abertamente o que falta, como o isolamento de sessão entre clientes, que é inaceitável para produção bancária. Por isso o piloto só começa depois da fase de preparação."
- **Conclusão do slide:** *"Autonomia é concedida por etapa, com limite e rastro, e nunca por padrão."*

### Slide 9. Ato 7: "Começar pequeno, crescer com evidência" *(1 min)*

- **Mensagem central:** caminho incremental com decisão de continuidade a cada etapa.
- **Storytelling:** reduz o risco percebido da decisão que vem a seguir.
- **Visual:** quatro degraus com "portão de decisão" entre eles.
  1. **Preparação (hardening):** fechar as lacunas do slide 8, conectar a dados via APIs reais do banco, definir baseline.
  2. **Piloto controlado:** um conjunto limitado de usuários (por exemplo, colaboradores, depois pequena fração de clientes) em uma única jornada: conta e cartão.
  3. **Validação:** comparar com o grupo de controle com base nos critérios pré-definidos. **Decisão de seguir ou parar.**
  4. **Expansão:** novas jornadas, adicionando especialistas e reutilizando capacidades.
- **Roteiro:** "Cada degrau tem um portão. Se o piloto não provar valor, paramos tendo gasto uma fração do que custaria uma construção completa. Se provar, expandimos por jornada, e não de uma vez."
- **Conclusão do slide:** *"Cada etapa compra a evidência que justifica a próxima."*
- **Prazos e dimensão [fictício]:**
  - Preparação: 3 meses.
  - Piloto: 3 meses, com 10% das jornadas (~2.000/mês, ~6.000 no total) em conversa e o restante como grupo de controle.
  - Validação: 1 mês, com decisão de seguir ou parar.
  - Expansão: por jornada, após o go.
  - Dimensionamento estatístico do piloto a confirmar com ciência de dados.
- **Nota:** valores e prazos são ilustrativos. Validar com engenharia e finanças antes de apresentar como compromisso.

### Slide 10. Ato 8: "A decisão que pedimos hoje" *(1 min)*

- **Mensagem central:** ação objetiva, recursos, critérios de sucesso e próximo marco.
- **Storytelling:** fecha o arco: da cliente que decifra um mapa à decisão de construir um banco que o decifra por ela.
- **Visual:** quatro blocos.
  1. **Decisão:** aprovar preparação e piloto controlado de uma jornada (conta e cartão). *Premissa: confirmar.*
  2. **Recursos [fictício]:** **R$ 1,2 mi** para preparação e piloto (engenharia R$ 700 mil, integração com sistemas R$ 300 mil, segurança, privacidade e jurídico R$ 200 mil), ~7 meses. Em caso de go, operação de R$ 0,6 mi/ano.
  3. **Critérios de sucesso, definidos antes [fictício]:**

     | Indicador | Baseline | Meta para seguir |
     |---|---|---|
     | Tempo mediano da jornada | 14 min | ≤ 6 min |
     | Taxa de conclusão | 55% | ≥ 58% |
     | Jornadas com atendente | 25% | ≤ 15% |
     | Custo por jornada iniciada | R$ 9,00 | ≤ R$ 6,50 |
     | CSAT (1 a 5) | 4,1 | ≥ 4,2 |
     | Ação financeira incorreta | n/a | **0** (um caso basta para parar e revisar) |

  4. **Próximo marco:** revisão de go/no-go no fim do mês 7, com dados do piloto versus controle.
- **Roteiro:** "Peço três coisas: autorização de R$ 1,2 milhão para a preparação e o piloto, patrocinadores de risco, segurança e jurídico desde o início, e um compromisso: ao final do piloto, olhamos os números juntos e decidimos continuar ou parar. As metas que vocês veem são ilustrativas e serão recalibradas com o baseline real antes do início."
- **Conclusão do slide:** *"Hoje decidimos medir, não decidimos escalar."*

---

## Entregável D: Tradução arquitetural

| Componente (diagrama) | Capacidade de negócio | Problema que ajuda a resolver | Exemplo prático (PoC) | Benefício esperado | Selo |
|---|---|---|---|---|---|
| **Frontend conversacional** (Streamlit :9090, React :3000) | O cliente expressa a intenção em conversa | Jornadas fragmentadas em telas | "Quero um cartão, meu CPF é …" | Menor esforço e abandono. Mesma lógica servindo vários canais | Implementado |
| **Orquestrador / supervisor** (FastAPI + LangGraph) | Coordena as etapas para resolver o pedido | O cliente tem de saber a ordem dos processos | Reconhece que "cartão" exige "conta" e aciona os dois especialistas | Resolução de ponta a ponta sem retorno ao cliente | Implementado. Ver ressalva da ordem de execução no slide 8 |
| **Roteador de intenção** (LLM) | Entende o pedido e escolhe 1 a N especialistas | Pedidos que cruzam domínios | Devolve `abrir_conta` e `cartao_credito` para o mesmo pedido | Cobertura de pedidos compostos | Implementado. Em erro, recai silenciosamente em `abrir_conta`, a corrigir |
| **LLM** (claude-haiku-5-5) | Compreender linguagem natural e decidir qual ferramenta usar | Formulários rígidos | Interpreta CPF e nome dentro de uma frase livre | Experiência natural. Custo por uso, a medir | Implementado |
| **Agentes especialistas** (`abrir_conta`, `cartao_credito`) | Capacidade digital que executa uma atividade específica | Acoplar o canal a cada sistema | O agente de cartão consulta a conta antes de emitir | Evolução independente por domínio | Implementado |
| **A2A** (agente a agente) | Comunicação e colaboração padronizadas entre agentes | Integrações sob medida a cada novo agente | O orquestrador descobre o "cartão de apresentação" do agente e envia o pedido | Menos retrabalho ao adicionar agentes | Implementado. A descoberta dinâmica (BFA) ainda não é usada |
| **MCP / recursos** (FastMCP) | Disponibiliza ferramentas, dados e regras aos agentes de forma padronizada | Cada agente reimplementando regras | `solicitar_cartao` valida se a conta existe, grava e responde | **Regra única e confiável**. Reuso por qualquer agente | Implementado |
| **APIs de domínio / sistemas legados** | Integração com as operações reais do banco | IA desconectada dos sistemas | Hoje `db.json` fictício | A mesma ferramenta pode apontar para a API real | **A construir**: não há integração real na PoC |
| **BFA** (registro e busca de agentes e ferramentas) | Catálogo pesquisável de capacidades | Descobrir e governar o que existe | Indexa AgentCards e ferramentas | Escalar o número de agentes com governança | Construído, **hoje órfão** (ninguém o consome) |
| **Observabilidade** (logs JSON + Langfuse) | Acompanha execução, qualidade, desempenho e custos | Caixa-preta | Um identificador por mensagem percorre frontend, orquestrador, agentes, LLM e ferramentas | Auditoria, diagnóstico e base do cálculo de ROI | Implementado. Há lacuna em ramos cancelados |
| **Governança e segurança** | Limites de autonomia, autorização, privacidade, intervenção humana | Risco de ações indevidas | CPF mascarado nos registros. Regra na ferramenta | Confiança para operar em produção | **Parcial**. Autenticação, isolamento de sessão, confirmação e humano no ciclo estão por construir |

---

## Entregável E: Business case

### 1. Indicadores de sucesso

| Dimensão | Indicador | Como medir |
|---|---|---|
| Eficiência | Tempo mediano para concluir abertura de conta e cartão | Timestamps do rastreio (Langfuse) versus baseline do fluxo atual |
| Custo | Custo por jornada concluída = IA + infraestrutura + atendimento humano de fallback | Tokens e chamadas por traço + custo operacional |
| Conversão | % de intenções "quero cartão" que viram cartão emitido | Funil de conversa versus funil atual |
| Qualidade | Taxa de ação incorreta ou incompleta | Auditoria amostral dos traços. **Meta de erro financeiro: nula** |
| Autonomia | Taxa de conclusão sem humano e taxa de encaminhamento | Eventos de escalonamento |
| Experiência | Satisfação ou esforço do cliente (CSAT/CES) | Pesquisa pós-jornada |
| Reuso | Tempo e esforço para adicionar uma nova jornada | Horas de engenharia do 2º agente versus o 1º |

### 2. Hipóteses de ganho (nenhuma validada)

1. A conversa reduz o tempo e o abandono em jornadas que cruzam produtos.
2. Jornadas simples concluídas sem humano reduzem o custo por atendimento.
3. Atendimento simultâneo aumenta a capacidade sem proporcional aumento de equipe.
4. Capacidades reutilizáveis reduzem o custo marginal de cada jornada nova.

### 3. Custos relevantes

- **Variáveis:** chamadas ao LLM (por conversa e por tool calling), infraestrutura.
- **Fixos de construção:** engenharia, integração com APIs e legados, segurança, privacidade (LGPD), jurídico.
- **Operação:** observabilidade, avaliação contínua de qualidade, atendimento humano de fallback, revisão de prompts e regras.
- **Risco de custo:** consumo de tokens imprevisível se não houver limites por conversa. Definir tetos.

### 4. Riscos

| Risco | Mitigação |
|---|---|
| Decisão errada da IA em ação financeira | Regra na ferramenta, confirmação do cliente, auditoria amostral, meta de erro nula |
| Vazamento ou mistura de dados entre clientes | Isolamento de sessão por cliente, autenticação entre serviços, CPF protegido (lacunas atuais) |
| Dependência de um fornecedor de LLM | Camada de abstração de modelo. Avaliar alternativas. Ferramentas e regras ficam fora do modelo |
| Ganho menor que o esperado | Portão de decisão no piloto. Cenários de sensibilidade |
| Regulatório e auditoria | Rastro ponta a ponta, DPO e jurídico desde a preparação |

### 5. Método recomendado para medir o ROI

1. **Baseline (antes de ligar o piloto):** medir o fluxo atual (tempo, custo por jornada, conversão, satisfação) por período representativo.
2. **Piloto com controle:** grupo atendido pela conversa versus grupo no fluxo atual, ou A/B por jornada. Sem controle não há atribuição causal.
3. **Critérios pré-registrados:** metas e limites de segurança definidos e assinados **antes** do piloto.
4. **Fórmula:**
   - `Ganho anual = (custo/jornada atual − custo/jornada com agentes) × volume + (Δ conversão × volume × margem por produto) + horas liberadas × custo/hora`
   - `Custo total = construção + integração + segurança/compliance + operação anual + LLM e infraestrutura`
   - `ROI = (Ganho anual − Custo total) / Custo total`, com payback = `Custo total / Ganho mensal`.
5. **Cenários:** conservador, base e otimista. Mostrar o ponto de equilíbrio em volume.
6. **Revisão periódica:** os mesmos indicadores continuam sendo medidos após a expansão.

### 6. Simulação com dados fictícios (aplica a fórmula acima ao cenário da seção 0.1)

Premissas comuns [fictício]: 240.000 jornadas/ano, margem incremental de R$ 90 por jornada concluída adicional, investimento de R$ 1,2 mi e operação de R$ 0,6 mi/ano.

| | Conservador | **Base** | Otimista |
|---|---|---|---|
| Custo por jornada (hoje R$ 9,00) | R$ 7,00 | **R$ 5,70** | R$ 4,50 |
| Economia de custo/ano | R$ 480 mil | **R$ 792 mil** | R$ 1.080 mil |
| Ganho de conversão | +2 p.p. | **+5 p.p.** | +8 p.p. |
| Jornadas concluídas adicionais/ano | 4.800 | **12.000** | 19.200 |
| Margem adicional/ano | R$ 432 mil | **R$ 1.080 mil** | R$ 1.728 mil |
| **Ganho bruto/ano** | **R$ 912 mil** | **R$ 1.872 mil** | **R$ 2.808 mil** |
| Ganho líquido/ano (− R$ 600 mil de operação) | R$ 312 mil | **R$ 1.272 mil** | R$ 2.208 mil |
| Payback do investimento (a partir do go) | ~46 meses | **~11 meses** | ~7 meses |
| ROI em 3 anos* | **−9%** | **+87%** | +181% |

\* ROI em 3 anos = (3 × ganho bruto − (1,2 mi + 3 × 0,6 mi)) ÷ (1,2 mi + 3 × 0,6 mi). Sem ramp-up, sem desconto a valor presente e sem custos de expansão.

Leituras que a diretoria deve fazer:
- **O resultado depende mais da conversão do que da economia de custo.** No cenário base, a conversão responde por ~58% do ganho (R$ 1,08 mi de R$ 1,87 mi), e é justamente a hipótese mais incerta. O piloto precisa medi-la primeiro.
- **O conservador não se paga em 3 anos.** Isso é informação útil: o caso só se sustenta se o piloto mostrar pelo menos o cenário base. Esse é o critério de go/no-go.
- **Ponto de equilíbrio no base:** ~128 mil jornadas/ano (53% do volume assumido) para ROI zero em 3 anos, mantendo o ganho de R$ 7,80 por jornada e a operação fixa. Abaixo disso, o investimento não se justifica.
- **Sensibilidade a incluir na versão real:** custo de LLM por conversa (aqui R$ 0,60), taxa de apoio humano e margem por cartão.

---

## Entregável F: Elevator pitch (60 s)

"Hoje, para pedir um cartão, o cliente precisa saber que antes precisa de uma conta e navegar por telas diferentes. Propomos inverter isso: o cliente diz o que quer, e uma equipe digital de especialistas, coordenada por uma recepção inteligente, executa as etapas na ordem certa. Diferente de um chatbot, ela age nos sistemas do banco e só pelas ferramentas e regras que definimos, com cada passo rastreável. Já temos um protótipo funcionando com dados fictícios para conta e cartão. No cenário ilustrativo, a jornada cai de 14 para 5 minutos e o ganho anual fica perto de R$ 1,9 milhão contra R$ 1,2 milhão de investimento. Esses números são hipóteses, e é por isso que pedimos um piloto controlado de sete meses, com metas definidas antes, para provar ou refutar menor custo, menor tempo e mais conversão. Se der certo, cada novo produto reaproveita o que já foi construído. Se não der, paramos cedo e barato."

---

## Entregável G: Perguntas difíceis da liderança

**1. "Já temos chatbot e automações. Por que isso é diferente?"**
Chatbot responde, automação repete um caminho fixo. Aqui o orquestrador escolhe quais especialistas acionar para um pedido livre, inclusive pedidos que cruzam produtos, e executa ações pelas ferramentas do banco. O custo é um novo risco, a decisão errada, tratado com regras na ferramenta, confirmação e rastro.

**2. "Quanto custa e quando retorna?"**
No cenário ilustrativo [fictício]: R$ 1,2 mi para preparar e pilotar e R$ 0,6 mi/ano para operar. O payback é de ~11 meses no cenário base, de ~7 no otimista e **não ocorre em 3 anos no conservador** (ROI de −9%). Ainda não existe número real, porque ele depende do baseline e do volume da jornada. O pedido de hoje é o menor investimento capaz de produzir esse número, e o método do Entregável E mostra como substituí-lo.

**3. "E se a IA errar ou inventar um dado?"**
Três camadas: as regras críticas ficam na ferramenta (a regra "conta antes de cartão" não depende do que a IA "entende"); ações que gravam exigirão confirmação, a construir antes do piloto; e cada passo é rastreável para auditoria. Meta de erro financeiro: nula. Se não for atingida, o piloto para.

**4. "E segurança, LGPD e regulador?"**
Já existe mascaramento de CPF em registros e controle do conteúdo logado. A documentação lista as lacunas para produção: CPF em texto plano na base fictícia, ausência de autenticação entre serviços e isolamento de sessão. Elas são pré-requisito do piloto. Jurídico e DPO entram desde a preparação.

**5. "Ficamos reféns de um fornecedor de IA?"**
O risco existe. Regras e dados ficam fora do modelo (ferramentas e sistemas do banco), o que reduz o custo de troca. Recomenda-se uma camada de abstração e avaliação comparativa de modelos durante o piloto. Os protocolos usados (A2A, MCP, AG-UI) são abertos.

**6. "Isso escala para a nossa base de clientes?"**
**Não está provado.** A PoC usa memória em processo e um arquivo JSON, sem lock de concorrência. Escalar exige persistência real, filas e testes de carga. Está na fase de preparação, e a escala só é discutida depois do piloto.

**7. "O custo de IA não vai explodir?"**
É um custo variável por conversa. Mitigamos com um modelo de porte pequeno (a PoC usa o claude-haiku-5-5), tetos por conversa e medição de custo por jornada concluída. No cenário ilustrativo [fictício], o LLM custa R$ 0,60 por conversa, cerca de 10% do custo por jornada (R$ 5,70), e o ganho vem de reduzir o atendimento humano. Um dos critérios de sucesso é custo por jornada ≤ R$ 6,50 contra R$ 9,00 hoje, e se não for atingido, o piloto não avança.

**8. "Isso substitui pessoas?"**
A proposta é assumir jornadas simples e repetitivas e encaminhar os casos complexos, com contexto, a atendentes humanos. O efeito sobre equipes só pode ser avaliado com dados do piloto. Não prometemos automação total.

**9. "Como integra com nossos sistemas legados?"**
A camada de ferramentas (MCP) foi desenhada para isso: cada capacidade é exposta de forma padronizada e pode apontar para uma API real. Na PoC essa integração é fictícia. A prova de integração com o primeiro sistema real é entregável da preparação.

**10. "Por que agora, e o que o protótipo prova de fato?"**
Prova que o mecanismo funciona: entender a intenção, selecionar especialistas, executar com regras e rastrear, em dois produtos. Não prova ganho de negócio, segurança de produção nem escala. Agora, porque medir custa pouco e o aprendizado se acumula enquanto o mercado avança. Se o piloto não provar valor, perdemos pouco.

---

## Revisão de qualidade

| Pergunta | Avaliação |
|---|---|
| Uma liderança não técnica compreenderia o valor? | Sim. Siglas (A2A, MCP, AG-UI) aparecem só no apêndice e no Entregável D. Os slides usam "recepção", "especialistas", "guichê padrão" |
| A diferença entre chatbot e agêntica ficou clara? | Sim, no slide 4, com o custo declarado (decisão errada) |
| Existe problema de negócio concreto? | Sim (atrito de jornadas que cruzam produtos). Os números do slide 1 são **fictícios**: trocar pelo funil real |
| A arquitetura é habilitadora? | Sim: aparece só no slide 5, depois da experiência |
| Os resultados são mensuráveis? | Sim, via Entregável E. As metas numéricas são **fictícias** e devem ser recalibradas com o baseline real |
| Os riscos foram tratados com transparência? | Sim. O slide 8 mostra o que existe e o que falta |
| Conduz a uma decisão objetiva? | Sim, desde que a premissa "aprovar preparação e piloto" seja confirmada |

---

## Apêndice: lacunas a fechar antes de apresentar

**Dados que só você pode fornecer**

1. Nome oficial: a documentação alterna entre "MD Bank" e "EM Bank". Padronizar.
2. Dados reais do baseline (volume e funil de abertura de conta e cartão, custo por atendimento, abandono, CSAT, margem por cartão). Hoje os slides 1, 3, 7 e 10 usam o cenário fictício da seção 0.1.
3. Valores reais de investimento, equipe e prazos, no lugar de R$ 1,2 mi, R$ 0,6 mi/ano e 7 meses. Depois de trocar, recalcule a simulação do Entregável E.
4. Patrocinador executivo e área de risco, segurança e jurídico que participarão.

**Pontos técnicos a verificar no código (aparecem como lacuna na documentação)**

5. **Memória compartilhada entre usuários** (arquitetura.md, ponto 2): a seção de observabilidade informa que `session_id`/`thread_id` fixos foram substituídos por `conversation_id` **no rastreio**. Confirme se o `thread_id` da memória dos agentes e do roteador também passou a ser por conversa. Se não, não afirme "isolamento" no slide 8.
6. **Orquestração divergente** (ponto 3): `/chat` executa agentes em paralelo e `/` em sequência. No cenário do slide 3 (cartão sem conta), o paralelo pode gerar corrida. **Demonstre ao vivo pelo canal React (sequencial)**, ou unifique antes.
7. **Confirmação antes de gravar:** não há evidência na documentação de passo de confirmação antes de abrir conta ou emitir cartão. Trate como requisito do piloto.
8. A análise é estática. **Execute o cenário do slide 3** antes de apresentá-lo como funcionando.
