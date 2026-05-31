# Sistema P2P com Balanceamento de Carga Dinâmico

> Trabalho acadêmico da disciplina de **Arquitetura de Sistemas Distribuídos**.
> Implementa uma rede peer-to-peer de *Masters* e *Workers* com heartbeat,
> distribuição de tarefas, descoberta dinâmica em rede e negociação de
> empréstimo de Workers entre Masters.

## Sobre o projeto

Este repositório contém a implementação de um sistema distribuído desenvolvido
de forma **incremental, em sprints**. Cada sprint adiciona uma camada de
funcionalidade sobre a anterior, partindo de uma comunicação básica até uma rede
autônoma capaz de se reorganizar sob carga.

O sistema é escrito em **Python puro** (apenas biblioteca padrão, com `asyncio`)
e comunica via **JSON sobre TCP/UDP**, com mensagens delimitadas por `\n`.

## Funcionalidades por sprint

| Sprint | Tema | O que faz |
|--------|------|-----------|
| **01** | Heartbeat | Worker verifica periodicamente se o Master está ativo (`HEARTBEAT` → `ALIVE`). |
| **02** | Comunicação de Tarefas | Master distribui tarefas (`QUERY`/`NO_TASK`); Worker processa e reporta status (`OK`/`NOK`); Master confirma (`ACK`). Suporte a Workers "emprestados" via `SERVER_UUID`. |
| **2.1** | Descoberta e Eleição | Worker inicia **sem IP/porta** do Master: descobre Masters por UDP (broadcast), elege um de forma determinística (menor nome) e migra para TCP. |
| **03** | Negociação Master-to-Master | Masters negociam entre si (P2P): um Master saturado pede ajuda a um vizinho, recebe Workers emprestados e os devolve quando a carga normaliza. |

## Estrutura do repositório

```
.
├── sprints/
│   ├── sprint01_heartbeat/      # Sprint 01 isolada
│   ├── sprint02_tarefas/        # Sprint 01 + 02
│   ├── sprint02_1_discovery/    # Sprint 01 + 02 + 2.1
│   └── sprint03_negociacao/     # Projeto COMPLETO (todas as sprints)
├── docs/
│   └── superpowers/
│       ├── specs/               # Documentos de design (o quê / por quê)
│       └── plans/               # Planos de implementação (como / em que ordem)
└── README.md
```

> **Cada pasta de sprint é cumulativa e auto-contida**: contém toda a lógica das
> sprints anteriores mais a sua. A pasta `sprint03_negociacao/` é o **produto
> final completo** — rodar ela é rodar o projeto inteiro.

## Como executar

Requisito: **Python 3.8+** (não precisa instalar dependências para rodar).

```bash
cd sprints/sprint03_negociacao

# 1) Rodar a suíte de testes (valida tudo, sem instalar nada)
python run_tests.py            # esperado: 54/54 testes passaram

# 2) Demonstração automática do ciclo completo de negociação
python scripts/run_negociacao_demo.py
```

Para executar manualmente em processos/máquinas separadas, consulte o
`README.md` dentro de cada pasta de sprint (payloads, comandos e checklist da
"Definição de Pronto").

## Metodologia: desenvolvimento assistido por IA

Este projeto foi desenvolvido com o apoio de um assistente de IA, seguindo um
**fluxo de trabalho estruturado** baseado em um conjunto de *skills*
(metodologias de trabalho). Essa decisão foi deliberada e faz parte do
aprendizado: em vez de pedir à IA para "gerar código solto", adotamos um
processo de engenharia disciplinado, no qual cada etapa é planejada, justificada
e testada antes da seguinte.

### Por que usar IA com um processo estruturado?

O objetivo não foi "deixar a IA fazer o trabalho", mas **usá-la como ferramenta
de engenharia sob supervisão humana**, com todas as decisões de arquitetura
tomadas e aprovadas por nós. Isso traz três benefícios pedagógicos:

1. **Decisões conscientes antes do código.** Cada escolha estrutural (ex.: usar
   broadcast ou multicast? AsyncIO ou Threads?) foi discutida, comparada e
   aprovada *antes* de qualquer implementação — e não descoberta por tentativa e
   erro no meio do código.
2. **Rastreabilidade.** Cada decisão virou um documento (spec), cada documento
   virou um plano de passos (plan), e cada passo virou código acompanhado de
   testes. É possível auditar o raciocínio do início ao fim.
3. **Qualidade verificável.** Todo o sistema é coberto por testes automatizados
   (54 ao final), garantindo que cada requisito do enunciado foi efetivamente
   cumprido.

### As *skills* utilizadas

O fluxo seguiu quatro skills encadeadas:

- **brainstorming** — explora abordagens e fecha as decisões de design **antes**
  de escrever código (com aprovação humana obrigatória em cada decisão).
- **writing-plans** — transforma o design aprovado em documentos: a **spec**
  (o quê / por quê) e o **plan** (como / em que ordem).
- **executing-plans** — implementa o plano passo a passo, rodando os testes a
  cada etapa.
- **using-superpowers** — coordena as três anteriores, garantindo que o processo
  ocorra na ordem correta.

### Specs e Plans

Para cada sprint foram gerados dois documentos, mantidos em `docs/superpowers/`:

- **Spec** (*specification*): descreve o **objetivo, as decisões de design e suas
  justificativas, os payloads e as regras**. Responde "o quê" e "por quê".
- **Plan** (*implementation plan*): descreve o **passo a passo de implementação**,
  com arquivos, código, testes e pontos de commit. Responde "como" e "em que
  ordem".

Essa separação espelha a prática profissional de **especificação de design**
seguida de **planejamento de implementação**, e permite que o projeto seja
compreendido tanto no nível conceitual quanto no operacional.

### Transparência

Todo o código foi revisado, compreendido e validado pelos autores. A IA atuou
como ferramenta de apoio à escrita e à organização do processo de engenharia —
as decisões técnicas, a verificação dos resultados e a responsabilidade pelo
trabalho são humanas.

## Conceitos de sistemas distribuídos exercitados

- Comunicação por troca de mensagens (JSON sobre TCP/UDP)
- Detecção de falhas via *heartbeat* e *timeouts*
- *Service Discovery* (descoberta dinâmica em rede via UDP)
- Consenso determinístico sem comunicação entre nós (eleição por regra fixa)
- Transição de protocolo (UDP → TCP)
- Balanceamento de carga dinâmico e negociação P2P entre peers
- Concorrência com `asyncio` (modelo single-thread, sem locks)
- Resiliência: reconexão, *backoff* exponencial e histerese

## Licença / uso acadêmico

Projeto desenvolvido para fins acadêmicos na disciplina de Arquitetura de
Sistemas Distribuídos.
