# claude-cowork-multilogin

Uma ferramenta de linha de comando segura para alternar entre várias contas no
Claude Cowork sem perder contexto local, memória ou indexação de arquivos.

*[English version](README.md)*

## O problema

Você troca de conta no app do Claude, abre a aba Code e a lista de conversas
está vazia. Os grupos da barra lateral sumiram. As rotinas agendadas pararam de
disparar.

**Nada foi apagado.** As conversas continuam no seu disco, intactas. O que
acontece é que o *catálogo* em volta delas é escopado por conta e organização,
então entrar com outro login mostra um catálogo vazio.

São três camadas, e só a primeira é segura:

| Camada | Onde fica | Escopada por conta? |
|---|---|---|
| Conversas (as transcrições em si) | `~/.claude/projects/<pasta>/<uuid>.jsonl` | Não, nunca se perdem |
| Fichas dos chats: título, pasta, modelo, exclusões, tarefas agendadas | `claude-code-sessions/<conta>/<org>/` | **Sim** |
| Grupos da barra lateral, a que grupo cada chat pertence, ordem dentro do grupo | `claude_desktop_config.json` → `preferences.epitaxyPrefs["dframe-group-scopes"]` | **Sim** |

Esta ferramenta copia as camadas 2 e 3 para a conta nova. A camada 1 não precisa
de nada.

> Uma armadilha que vale conhecer: a mesma estrutura de grupos também aparece no
> `localStorage` do Electron (`Local Storage/leveldb`), que é o que um `grep`
> encontra primeiro. Aquela cópia é apenas espelho. Escrever nela parece
> funcionar, sobrevive a uma releitura e é descartada em silêncio na próxima
> inicialização do app. O arquivo de configuração é a fonte da verdade.

## Requisitos

macOS e Python 3.9 ou mais novo (o `/usr/bin/python3` do sistema basta). Sem
biblioteca de terceiros, sem instalação.

## Como usar

A ordem importa. **A etapa 1 tem que rodar antes da troca**, porque é o único
momento em que ainda dá para identificar a conta que você está deixando.

```bash
git clone https://github.com/ergti/claude-cowork-multilogin.git
cd claude-cowork-multilogin

python3 migrate.py record       # 1. ainda logado na conta ANTIGA
                                # 2. agora troque de conta no app
                                # 3. encerre o Claude por completo (Cmd+Q)
python3 migrate.py apply        # 4. traga tudo para a conta nova
                                # 5. reabra o Claude
```

Prefere clicar? Use `1-BEFORE-SWITCHING.command` e `2-AFTER-SWITCHING.command`
no Finder, nessa ordem.

Dois comandos extras:

```bash
python3 migrate.py status          # que contas existem nesta máquina
python3 migrate.py apply --dry-run # mostra o que faria, sem gravar nada
```

### Se você já trocou e esqueceu a etapa 1

Nada foi perdido: os dados da conta antiga continuam no disco. Rode
`python3 migrate.py status` para listar as contas que ele enxerga, escolha a que
tem as suas conversas e escreva o arquivo de estado à mão:

```bash
mkdir -p ~/.claude-cowork-multilogin
cat > ~/.claude-cowork-multilogin/previous-account.json <<'JSON'
{
  "accountUuid": "COLE-AQUI-O-UUID-DA-CONTA-ANTIGA",
  "organizationUuid": "COLE-AQUI-O-UUID-DA-ORG-ANTIGA"
}
JSON
```

Depois encerre o app e rode o `apply`.

## O que ela não faz

- **Nunca apaga nada da conta de origem.** Voltar a logar nela sempre devolve o
  estado original, o que torna o rollback trivial.
- **Nunca sobrescreve ficha que já exista** no destino.
- **Não mexe nos grupos do destino** se ele já tiver os seus.
- **Recusa rodar com o Claude aberto.** O app segura o banco de dados e
  descartaria a edição. Essa verificação *falha fechado*: se não conseguir
  determinar se o app está rodando, ela recusa.
- **Não ressuscita conversas que você apagou de propósito.** Os marcadores de
  exclusão vão junto, então o que estava apagado continua apagado.
- **Não toca nas suas conversas.** A camada 1 nunca é aberta para escrita.

Antes de alterar qualquer coisa, grava um backup verificado em
`~/.claude-cowork-multilogin/backups/` e imprime o comando exato para desfazer.

## Testes

```bash
python3 tests/test_migrate.py
```

12 testes, só biblioteca padrão, inteiramente sobre dados sintéticos num
diretório temporário: nunca leem nem escrevem numa instalação real do Claude.

Seis deles são controles negativos, um por proteção. Cada um foi validado
revertendo a proteção que cobre e conferindo que exatamente aquele teste falha,
porque teste que nunca viu o defeito não prova nada.

## Escopo e franqueza sobre cobertura

Escrita para macOS e verificada nele, pelo caminho real de execução: lançada do
jeito que o Finder lança, com `PATH` curto e o Python do sistema. A estrutura de
que ela depende é a dos dados locais do Claude em agosto de 2026; uma versão
futura do app pode mudar os lugares, e aí o `status` é a primeira coisa a rodar.

Fichas cuja transcrição já esteja ausente (por exemplo, um chat cuja pasta
estava num volume desmontado) continuam ausentes. Isso é condição anterior, não
algo causado pela migração.

## Licença

MIT. Veja [LICENSE](LICENSE).
