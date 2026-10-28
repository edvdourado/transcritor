# Preparação da primeira publicação

Data da verificação local: **28/10/2026**. Destino pretendido: `edvdourado/transcritor`.

## Estado Git encontrado

- Branch `master`, ainda sem commit inicial; `git ls-files` vazio e `git rev-list --all --count` igual a zero.
- Nenhum remote configurado. Não foi consultado o estado do repositório remoto no GitHub.
- Sete referências internas em `refs/codex/turn-diffs/checkpoints/`, apontando para snapshots; não são branches de publicação.
- O banco de objetos inicial continha **96 blobs e 39 árvores**, sem objetos de commit. `git fsck --full --no-reflogs --unreachable` também revelou objetos locais fora das referências atuais. Eles foram incluídos na varredura.
- Todos os arquivos do projeto estavam não rastreados. Não houve stage, commit, renomeação de branch, alteração de remote, reescrita de histórico ou push nesta preparação.

## Auditoria de arquivos e objetos Git

Foi feita uma varredura estática de **21.912 arquivos locais** no levantamento inicial, incluindo arquivos ignorados, ambientes virtuais, dependências, builds, caches e temporários, além dos 96 blobs Git. Foram procurados marcadores de chaves privadas, tokens de provedores, atribuições de senha/segredo/token, credenciais em URLs, hashes de autenticação, ambientes reais e endereços IPv4. Nomes/extensões e tamanhos foram usados para localizar áudios, modelos, certificados e outros artefatos sensíveis. Os arquivos candidatos à publicação foram revisados separadamente; os exemplos finais foram novamente conferidos.

| Caminho/escopo | Resultado e tratamento |
|---|---|
| Fontes de `backend/`, `frontend/` e arquivos candidatos à publicação | Nenhuma credencial, token ou chave privada identificada; nenhuma transcrição real identificada nos candidatos |
| `.env.example`, `deploy/vps/.env.vps.example` | Exemplos sem segredos; nenhum `.env` real encontrado no levantamento |
| `README.md`, `deploy/vps/README.md`, `backend/app/config.py`, `frontend/vite.config.ts` e versões antigas em objetos Git | Endereços locais de configuração/desenvolvimento; nenhum IP privado de infraestrutura desnecessário identificado nos candidatos |
| `backend/tmp/`, `tmp/` | Áudios, capturas, resultados e resíduos de testes/desenvolvimento; tratados como privados e excluídos, sem presumir autorização para publicar |
| `.venv/`, `frontend/node_modules/`, `tmp/python/`, `tmp/uv-cache/`, `tmp/venv310/` | Ocorrências de nomes de senha/token, URLs de exemplo e IPs em bibliotecas/documentação de terceiros; fora da publicação |
| Certificados em `tmp/python/`, `tmp/uv-cache/`, `tmp/venv310/` | Bundles públicos de autoridades certificadoras em dependências; não são chaves privadas; excluídos com os ambientes/caches |
| `frontend/node_modules/` | Único arquivo acima de 10 MiB no levantamento inicial: executável de build da dependência; excluído |
| `frontend/package-lock.json` | URLs `resolved` apontam ao registro público npm; nenhuma URL de registro privado identificada |
| Objetos Git, inclusive inalcançáveis e checkpoints | Nenhum segredo identificado pela varredura; nenhuma remediação de histórico indicada pelos achados atuais |

O `.gitignore` cobre ambientes reais, venvs, dependências, builds, caches, logs, modelos, chaves, gravações e diretórios de transcrições. Não ignora genericamente todo TXT/JSON: fontes e lockfiles continuam revisáveis. Exceções restritas permitem mídias sintéticas/públicas intencionais em `backend/tests/fixtures/` e `frontend/src/__fixtures__/`; adicionar uma fixture exige revisar seu conteúdo. Os testes atuais geram seus próprios áudios, sem fixtures binárias no repositório.

**Limite da conclusão:** auditoria estática por padrões e inspeção dos candidatos, sem garantia matemática de ausência de segredo arbitrário ou dados pessoais. Conteúdo sem padrão reconhecível e semântica de áudio/imagens/binários não foram certificados. Por isso, mídias locais foram excluídas e nenhuma captura foi promovida ao README. Não foi uma auditoria de CVEs, pentest, revisão de contas GitHub ou inspeção da VPS. Resultados brutos ficaram em `tmp/`, ignorados; valores potencialmente sensíveis não são reproduzidos neste relatório.

### Caso um segredo seja encontrado depois

**`.gitignore` não limpa histórico nem deixa de rastrear arquivos já adicionados.** Antes de publicar, revogue/rotacione a credencial afetada e remova o dado de todas as versões/referências que seriam enviadas. Em um histórico com commits, faça backup privado e avalie `git-filter-repo`, depois repita a auditoria. Se já houve exposição remota, trate clones, forks e caches conforme o [guia oficial do GitHub](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository). Não use `push --mirror` para esta publicação: os checkpoints locais não fazem parte da branch pública.

## Mudanças preparadas

- `README.md`: apresentação em português, funcionalidades reais, execução local, testes/build, formatos, limites, arquitetura, privacidade e licença a definir; removidos relatos antigos de etapas.
- `.gitignore`: exclusão de dados privados e artefatos, preservando exemplos e fixtures intencionais.
- `.env.example` e `deploy/vps/.env.vps.example`: exemplos sanitizados, coerentes com o backend e os caminhos públicos do guia.
- `docs/DEPLOY.md`: nova instalação Oracle ARM64/Ubuntu 22.04, modelos, FFmpeg, FastAPI, frontend, Nginx, HTTPS, HTTP Basic, systemd, reboot, renovação, atualização e rollback.
- `deploy/vps/transcritor.service` e `deploy/vps/nginx.conf.example`: exemplos públicos com usuário de serviço, loopback, diretório privado e proxy autenticado.
- `deploy/vps/README.md`: instruções atuais do empacotador e links para a implantação; removido roteiro antigo que descrevia uma etapa ainda não implantada.
- `deploy/vps/package.py`: lista de fontes permitidas ampliada somente para incluir a documentação e exemplos novos. O teste existente verifica inclusão, exclusão, hashes e reprodução do pacote.
- `docs/PUBLICACAO.md`: este registro.

Código de produto e dependências não foram alterados. Nenhuma licença foi escolhida, imagem publicada ou configuração privada da VPS copiada.

## Verificações executadas

Ambiente local: Windows, Python **3.12.14** e **3.10.19**, Node.js **24.16.0**, npm **10.9.9**. Dependências já instaladas; não foi feita instalação limpa de rede. FFmpeg e FFprobe estavam disponíveis.

| Verificação | Resultado real |
|---|---|
| Backend em Python 3.12.14 — `python -m pytest backend -q -rs` com engine mock | **121 passed**, 14,25 s; nenhum skip |
| Backend em Python 3.10.19 — mesmo comando | **121 passed**, 12,34 s; nenhum skip |
| Integração FFmpeg/FFprobe incluída na suíte | Executada nos dois Pythons, inclusive entradas sintéticas OGG/MP3/M4A/WAV |
| Frontend — `npm test` | **64 passed**, um arquivo de testes, 48,05 s |
| Produção — `npm run build` | Aprovado: TypeScript e Vite 7.3.7, 38 módulos, build Vite em 9,20 s |
| Dependências Python — `python -m pip check` | `No broken requirements found` no venv Python 3.12 |
| Empacotador — `python deploy/vps/test_package.py -v` | Um teste passou; um skip por falta de privilégio para criar symlink no Windows |
| Auditoria final dos candidatos | 44 arquivos, nenhuma ocorrência nos padrões de segredo; exemplos conferidos com as variáveis reais do backend |
| Documentação e exclusões | Links Markdown válidos; 21 verificações de exclusão/preservação do `.gitignore` aprovadas |
| Sintaxe dos exemplos | 22 blocos Bash e seis PowerShell analisados, substituindo placeholders; sem executar comandos de implantação |
| Pacote real de fontes | 44 arquivos revisados mais manifesto; lista de inclusão e hashes verificados |

As duas suítes backend emitiram um `StarletteDeprecationWarning` sobre o uso de httpx no TestClient. Não houve falha; não foi trocada dependência apenas para suprimir o aviso.

As primeiras tentativas de backend no sandbox ficaram bloqueadas até na criação de um event loop asyncio do Windows; foram interrompidas e repetidas com permissão de execução local fora dessa restrição. O Bash do Git também precisou dessa permissão para análise de sintaxe. O empacotador falhou inicialmente por acesso negado ao diretório temporário do sandbox; repetido com `TMP`/`TEMP` em `tmp/publication-test-temp`, passou com o skip descrito. Nenhuma dessas repetições acessou a VPS.

Não foram executados nesta sessão: inferência com modelos Small/Medium reais, teste em Linux ARM64, validação nativa `nginx -t`/`systemd-analyze verify`, emissão/renovação de certificado ou reboot. A produção funcional é contexto informado pelo mantenedor, não um teste novo desta sessão. O guia exige essas verificações no destino e o registro do ref do whisper.cpp/checksums dos modelos para reprodução exata.

## Comandos recomendados para a primeira publicação

**Somente para executar depois da revisão e da decisão de publicar.** Nenhum comando de publicação abaixo foi executado. Na raiz, PowerShell:

```powershell
git status --short --branch
git remote -v
git ls-files --others --exclude-standard
# Lista explícita dos diretórios/arquivos revisados; não usar git add -f.
git add -- .gitignore .env.example README.md backend frontend deploy docs
git diff --cached --check
git diff --cached --stat
git diff --cached --name-only
# Revise o conteúdo localmente antes de confirmar; não compartilhe saída com segredos.
git diff --cached
# Se houver arquivo indevido no stage: git rm --cached -- <CAMINHO>
git branch -m main
git commit -m "Prepare Transcritor for initial public release"
```

Escolha a licença antes da publicação se quiser conceder permissões de reutilização; este preparo mantém a decisão em aberto. Configure o remote somente quando o repositório pretendido existir e a revisão estiver concluída:

```powershell
git remote add origin https://github.com/edvdourado/transcritor.git
# Leitura do remoto: confirme se já tem branches/tags antes do primeiro envio.
git ls-remote origin
```

Se o remoto já tiver conteúdo, busque-o e reconcilie os históricos antes de prosseguir; não faça force push nem sobrescreva commits existentes. Se o remoto estiver vazio, após autorização de publicação:

```powershell
git push -u origin main
```

Envie apenas a branch pública revisada; evite `--mirror`/`--all`. Repita a auditoria de arquivos staged se houver alterações entre esta preparação e o commit.
