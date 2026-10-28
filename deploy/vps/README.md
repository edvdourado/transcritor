# Empacotamento opcional de fontes

A implantação completa está em [docs/DEPLOY.md](../../docs/DEPLOY.md). Este diretório contém exemplos públicos sanitizados, sem configurações copiadas da VPS:

- [transcritor.service](transcritor.service): backend em loopback, um worker, usuário de serviço e temporários privados.
- [nginx.conf.example](nginx.conf.example): frontend compilado, proxy `/api/`, HTTPS e HTTP Basic.
- [.env.vps.example](.env.vps.example): variáveis reais da aplicação para os caminhos do guia.
- [requirements-py310-arm64.txt](requirements-py310-arm64.txt): versões e hashes de wheels para CPython 3.10/Linux ARM64; não usar no Windows. Não é um lock universal nem substitui auditoria de vulnerabilidades.

O empacotador existente cria um arquivo determinístico, com lista explícita de fontes permitidas e manifesto SHA-256. Não acessa SSH, não consulta a VPS e não instala nada. Na raiz, PowerShell:

```powershell
.\.venv\Scripts\python.exe deploy/vps/test_package.py -v
.\.venv\Scripts\python.exe deploy/vps/package.py --output tmp/transcritor-source.tar.gz
tar -tzf tmp/transcritor-source.tar.gz
Get-Content tmp/transcritor-source.tar.gz.sha256
```

Escolha outro nome se o artefato já existir; não há sobrescrita. No Linux, use `.venv/bin/python`. O pacote não inclui `.git`, ambientes reais, dependências, builds, modelos ou dados de execução. Arquivos adicionais fora da lista de fontes também não são incluídos automaticamente. Revise conteúdo e manifesto antes de transferir.

Os membros têm modo 0600: ao extrair para uso por Nginx e um usuário de serviço, ajuste explicitamente a propriedade/permissões das fontes e do build conforme o guia. Nunca dê acesso público a temporários ou configurações reais.
