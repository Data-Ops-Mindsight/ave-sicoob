# AVE – Painel e Relatório Unificado (Sicoob Cocred) · v2

Streamlit + SQLite + reportlab, lendo da API Mindsight (rodada 14). Perfis: **RH** (tudo) e **BP** (escopo por pessoas/áreas/cargos definido pelo RH).

## Abas (app.py monta o menu; conteúdo em `views/`)
Tela inicial · Visão geral · Ficha individual · Visualização de pendências · Competências.

## Regras de funcionamento
- **Quem aparece:** só colaboradores com a tag **"Em experiência"** na rodada (`tag_em_experiencia` e `exigir_tag_experiencia` no `config.yaml`).
- **Atualização dos dados:** **não é automática.** Só ocorre quando o RH clica em "Atualizar respostas e notas" (Tela inicial), com intervalo mínimo de **5 minutos** entre atualizações (`espera_atualizacao_min`). Se a coleta falhar, uma nova tentativa é liberada em 1 minuto.
- **Competências:** agrupamento das 73 perguntas em 12 temas, em `competencias.yaml` (referência em `perguntas_rodada.csv`). A chave "Analisar por competências" (Ficha individual e Visão geral) alterna para análise pergunta a pergunta.

## Produção

### 1. Instalar e configurar
1. `pip install -r requirements.txt`
2. Configure os segredos (nunca versionar):
   - **Streamlit Cloud:** Advanced settings → Secrets, com o mesmo conteúdo. Lá não existem `.env` nem `creds.json`: use `GOOGLE_CREDENTIALS_JSON = '''{...}'''`.
3. `streamlit run app.py` (local). Os dados só são atualizados pelo botão "Atualizar respostas e notas" da Tela inicial (RH), com intervalo mínimo de 5 minutos.

### 2. Usuários (nos Secrets)
Os acessos oficiais ficam nos Secrets, em blocos `[[usuarios]]`. Eles são recriados no banco a cada inicialização, então não se perdem quando o servidor reinicia. Remover o bloco revoga o acesso.

1. Gere o hash da senha na sua máquina (a senha em texto nunca vai para os Secrets):
   ```bash
   python auth.py gerar-hash
   ```
2. Adicione um bloco por usuário. Os blocos `[[usuarios]]` vão **depois** de todas as chaves simples (`AVE_PEPPER`, `TOKEN_SPREADSHEET_ID` etc.):
   ```toml
   [[usuarios]]
   usuario = "maria.rh"
   nome = "Maria"
   perfil = "rh"                 # vê tudo
   hash_senha = "bcrypt$..."

   [[usuarios]]
   usuario = "joao.bp"
   nome = "João"
   perfil = "bp"                 # só vê o escopo definido abaixo
   hash_senha = "bcrypt$..."
   areas_permitidas = ["NEGOCIOS"]
   cargos_permitidos = []
   pessoas_permitidas = []
   pode_ver_texto = false        # justificativas, textos livres e GPC
   pode_exportar = true          # PDF
   expira_em = "2026-12-31"      # opcional
   ativo = true                  # false desativa sem apagar o bloco
   ```
3. O BP precisa de ao menos um critério (`areas_permitidas`, `cargos_permitidos` ou `pessoas_permitidas`); sem critério, não vê ninguém.
4. É necessário ao menos um usuário `rh` nos Secrets para o primeiro acesso.

### Cuidados
- Repositório **privado**; `.env`, `creds.json`, `secrets.toml` e `data/` ficam fora do Git.
- `AVE_PEPPER` fixo e igual em todo deploy; se mudar, os acessos de BP por pessoa se perdem.
- Em Settings → Sharing do Streamlit, libere só os e-mails necessários.
- Para revogar acesso, apague o bloco do usuário nos Secrets ou use `ativo = false`.