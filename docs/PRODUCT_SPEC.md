# Especificação de produto

## Problema

A operação funciona, mas só é administrável por dentro do servidor. Criar um bot,
trocar um grupo, mudar um limite ou renovar um cookie exige editar código ou
variável de ambiente e redeployar. E não há como saber se a operação dá lucro:
existe registro do que foi enviado, nenhum do que retornou.

## Objetivo

Um dashboard que seja o centro de controle: configurar sem SSH, e medir o retorno
real de cada bot, grupo, conta e campanha.

**Critério de sucesso.** Ao final, nenhuma destas ações exige tocar no servidor:
criar bot · trocar telefone · trocar grupo · adicionar conta · mudar nicho ·
ajustar limite · renovar cookie · lançar despesa · consultar métrica.

## As perguntas que o dashboard responde

O painel não é um mural de números. Cada tela existe para responder uma pergunta:

| Pergunta | Onde |
|---|---|
| Quanto invisto e quanto retorno? | Overview: investimento, comissão, lucro, ROI |
| Onde estou perdendo dinheiro? | Breakdowns ordenados por lucro, negativos em destaque |
| Quais contas performam? | Comparativo por conta |
| Quais campanhas performam? | Por campanha, com ROAS e custo por entrada |
| Quais grupos performam? | Por grupo: envios, cliques, conversão, receita |
| Quais bots funcionam? | Por bot + saúde (último ciclo, erros) |
| Quais fontes geram receita? | Por plataforma |
| Qual o custo real de cada venda? | Custo por venda e por comprador |
| O que exige minha atenção agora? | Faixa de alertas no topo |

## Métricas

Faturamento · vendas · pedidos · comissões · investimento total · gastos por
categoria · investimento em tráfego · ROI · ROAS · lucro · custo por venda ·
custo por comprador · custo por entrada em grupo · entradas em grupo ·
conversões · desempenho por período, plataforma, conta, bot, grupo e campanha.

Fórmulas em [DATABASE.md](DATABASE.md#fórmulas-das-métricas) — implementadas uma
vez em `core/metrics.py`, nunca reimplementadas no frontend.

**Honestidade do dado.** Denominador zero exibe "sem dados", não `0`. Período sem
venda importada exibe aviso, não `R$ 0,00` — um zero falso é pior que um vazio
declarado. Comissão pendente e confirmada aparecem separadas.

## Filtros

Período · plataforma · conta · bot · nicho · grupo · campanha · telefone.
Globais, combináveis, persistidos na URL (link compartilhável e recarregável).
Período com presets (hoje, 7d, 30d, mês, mês anterior) e comparação automática
com o período anterior de mesmo tamanho.

## Funcionalidades

### Plataformas e contas
Múltiplas contas por plataforma, sem limite. Adicionar, editar, ativar, pausar,
remover. Plataforma nova = linha em `platforms` + cliente em `core/platforms/`,
sem reconstruir nada. Excluir conta em uso por bot é bloqueado (409) com a lista
de quem a usa.

### Credenciais
Por conta: status (válida, expirando, expirada, inválida), última renovação,
último uso, validade, último erro. Renovar = colar o valor novo e testar, direto
no dashboard. Sessão expirada detectada automaticamente pelo 401/403 da
plataforma vira alerta. **O valor nunca é exibido** — nem mascarado, nem parcial.

### Bots
Criar, editar, duplicar, ativar, pausar, desativar. Nome, nicho, telefone,
grupos, plataformas, contas, status, parâmetros, automações, template de
mensagem. Um telefone pode servir vários bots; o consumo consolidado do número
fica visível para que o teto anti-ban não seja estourado sem querer.

### Grupos
Descoberta automática via evolution-api, mais cadastro manual. Associação a bots.
Sinaliza grupo "somente admins" onde o bot não é admin — hoje isso engole
mensagem em silêncio.

### Despesas
Descrição, valor, data, categoria, plataforma, campanha, bot, nicho, observações.
Manual agora; import de Meta Ads e CSV depois, sem duplicar o que foi lançado à
mão.

### Alertas
Bot offline · autenticação expirada · conta desconectada · campanha com custo
anormal · erro recorrente · falha na publicação · grupo inacessível · queda de
conversão · automação parada · dados desatualizados.

Cada alerta é acionável e deduplicado: cookie expirado gera **um** alerta que se
atualiza, não um por ciclo. Resolve sozinho quando a causa some. Log técnico
existe, em área separada — não domina o painel.

### Auditoria
Quem alterou, o quê, valor anterior, valor novo, quando. Cobre config, telefone,
grupo, token, conta e ativação de bot. Valores sensíveis aparecem como `***`.

## Não-objetivos

Fora de escopo, registrado para não virar escopo por inércia: app mobile nativo
(o web é responsivo), multiusuário com times (estrutura pronta, UI não), editor
visual de automação, IA de recomendação, marketplace de templates.

## Prioridade

1. **Configurável sem servidor** — o critério principal. Fases 1–6.
2. **Medir retorno** — fases 7–9, 13.
3. **Saber quando algo quebra** — fase 10.
4. **Conforto de uso** — o resto.

Se houver corte de escopo, corta-se de baixo para cima.
