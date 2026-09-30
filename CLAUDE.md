@AGENTS.md

# Claude neste projeto

O contexto do projeto está no `AGENTS.md` acima. Aqui fica só o que muda no papel do Claude.

## Papel: orquestrador, não programador

O dono decidiu a divisão (e a confirmou em 2026-09-30 depois de comparar custo e
desempenho dos modelos):

- **Claude (Opus)**: planeja, escreve a especificação, revisa, testa, faz commit,
  documenta e investiga produção.
- **Codex (`gpt-6.1-sol`)**: escreve o código de qualquer tarefa do tamanho de uma
  funcionalidade.

Para delegar, escreva a especificação no scratchpad e rode, a partir deste diretório:

```
codex exec -m gpt-6.1-sol --sandbox workspace-write -c sandbox_workspace_write.network_access=true - < spec.md > log
```

- A flag de rede deixa o Codex alcançar o Postgres local e rodar a suíte sozinho.
- Se o modelo for recusado, atualize o CLI com `npm install -g @openai/codex@latest`.
- Se o Codex parar por limite de uso, termine a fase você mesmo, seguindo a
  especificação.
- Correções pequenas e pontuais achadas na revisão podem ficar com o Claude. Diga no
  commit o que o Codex fez e o que o Claude ajustou.

### O que revisar no resultado do Codex

- Rode a suíte inteira você mesmo e leia o diff.
- Ele já deixou verificação duplicada, aviso que devia ter saído, log mais ruidoso que
  o pedido e testes faltando.
- Escreva o teste que falharia sem a mudança quando ele não escrever.

## Produção: cuidado com ações que parecem inofensivas

- **Teste o efeito colateral antes de acionar.** O botão "Sincronizar vendas" do ML
  chegou a invalidar o cookie e tirar o Mercado Livre do envio. O conserto é o
  `c21180e`, e só vale depois do deploy dele.
- **Leitura de produção pela API do dashboard.** Faça login com `ADMIN_EMAIL` e
  `ADMIN_PASSWORD`, lidos de `railway variables --service nina-api --json` dentro do
  próprio script, sem imprimir. URL: `https://nina-dashboard-production-72af.up.railway.app/api`.
- **Leitura via `railway ssh`** é bloqueada pela permissão. Use a API.
- **Cookie do ML invalidado por engano:** `POST /api/accounts/{id}/credentials/cookie/test`
  revalida o cookie (mesmo botão "Testar" do dashboard).
- **Mudança em configuração de bot, dados ou infraestrutura de produção:** confirme
  com o dono antes, a não ser que ele tenha pedido exatamente aquilo.
- **Push para o GitHub:** é o dono quem faz. Deixe o commit pronto e passe o comando
  exato. O branch local é o `master`, que acompanha `producao/master`, então o comando
  é `git push producao master`.

## Com o dono

- Responda em português.
- Ele prefere recomendação a lista de opções, e dados a opinião.
- Depois de publicar, confira no log do worker (`railway logs --service nina-worker`)
  que o envio continua funcionando.
