# Implantação — Oracle Cloud ARM64 / Ubuntu 22.04

Este guia descreve uma instalação reproduzível em uma **nova máquina**. A produção existente foi informada pelo mantenedor; não foi acessada nem modificada nesta preparação. Os caminhos abaixo são uma convenção pública, não uma cópia da configuração privada da VPS. Para migrar uma instalação existente, compare caminhos, permissões e unidades antes de executar qualquer comando.

Substitua `<USUARIO_ADMIN>`, `<IP_PUBLICO>`, `<DOMINIO>`, `<RELEASE>` e `<WHISPER_REF>` por valores da sua instalação. O domínio de exemplo `transcritor.example.com` deve ser substituído em todo o Nginx. Nenhuma senha deve entrar no Git ou na linha de comando.

## 1. Sistema e rede

Use Ubuntu 22.04 aarch64, Python 3.10 e acesso administrativo. No computador do administrador, conecte-se quando for implantar:

```sh
ssh <USUARIO_ADMIN>@<IP_PUBLICO>
```

Na máquina de destino:

```sh
uname -m
. /etc/os-release
printf '%s\n' "$PRETTY_NAME"
python3.10 --version
sudo apt-get update
sudo apt-get install -y python3.10-venv python3-pip ffmpeg git build-essential cmake nginx apache2-utils certbot
ffmpeg -version
ffprobe -version
```

Espere `aarch64`, Ubuntu 22.04 e Python 3.10.x. Instale Node.js 22.12+ (linha 22) ou 24.x a partir de uma distribuição oficial verificada para ARM64 **se o build for feito na VPS**. Alternativamente, faça o build com `npm ci && npm run build` em uma máquina de build e transfira apenas `frontend/dist/` para a release correspondente. Não copie `node_modules` ou venv de outro sistema.

Aponte DNS A (e AAAA somente se houver IPv6 funcional) ao IP público. No Security List/NSG da Oracle e no firewall do Ubuntu, permita TCP 80 e 443; restrinja SSH à origem administrativa. Não exponha 8765. Preserve a regra SSH antes de alterar firewall. Verifique os firewalls reais da imagem, inclusive UFW/iptables se usados.

## 2. Usuário e armazenamento

```sh
sudo useradd --system --user-group --home-dir /var/lib/transcritor --no-create-home --shell /usr/sbin/nologin transcritor
sudo install -d -m 0755 /opt/transcritor/releases
sudo install -d -m 0700 -o transcritor -g transcritor /var/lib/transcritor
sudo install -d -m 0700 -o transcritor -g transcritor /var/lib/transcritor/jobs
```

Execute a criação do usuário apenas se ele ainda não existir (`id transcritor`). Código e modelos podem ficar em um Block Volume persistente. Se mudar os caminhos, ajuste ambiente, Nginx e systemd juntos. Configure a montagem persistente por UUID no `/etc/fstab`, valide-a com `findmnt` e mantenha `RequiresMountsFor` coerente na unidade. A perda de um volume não deve iniciar uma segunda instalação no disco raiz.

Planeje disco para modelos, dependências e temporários: original, spool de upload e WAV podem coexistir. Um WAV de 30 minutos ocupa cerca de 57,6 MB decimais, além do original. Retenção não é quota de disco; monitore uso e espaço livre.

## 3. whisper.cpp e modelos

Compile no ARM64 a partir do projeto oficial. Escolha e registre um tag/commit testado em `<WHISPER_REF>`; não dependa implicitamente da branch principal para futuras reconstruções:

```sh
sudo git clone https://github.com/ggml-org/whisper.cpp.git /opt/whisper.cpp
sudo git -C /opt/whisper.cpp checkout --detach <WHISPER_REF>
sudo cmake -S /opt/whisper.cpp -B /opt/whisper.cpp/build -DGGML_CUDA=OFF -DGGML_NATIVE=OFF
sudo cmake --build /opt/whisper.cpp/build --config Release -j2
cd /opt/whisper.cpp
sudo bash models/download-ggml-model.sh small
sudo bash models/download-ggml-model.sh medium
build/bin/whisper-cli --help
git rev-parse HEAD
sha256sum models/ggml-small.bin models/ggml-medium.bin
sudo -u transcritor test -x build/bin/whisper-cli
sudo -u transcritor test -r models/ggml-small.bin
sudo -u transcritor test -r models/ggml-medium.bin
```

Os downloads são grandes e não pertencem ao Git do Transcritor. Use modelos **multilíngues** (`small`/`medium`, sem `.en`) para português. O backend chama o CLI com `-m`, `-f`, `-l`, `-t`, `-ng`, `-oj` e `-of`, exige JSON com `transcription` e usa CPU. Verifique esses argumentos no ref escolhido. Não há tag do whisper.cpp nem checksums dos modelos de produção registrados nesta cópia: registre-os na sua instalação para reproduzir exatamente o ambiente. O hash calculado localmente registra o arquivo recebido; compare também com a fonte confiável quando houver hash publicado.

## 4. Preparar uma release

Use um diretório novo por versão. Depois que o repositório público existir:

```sh
sudo git clone https://github.com/edvdourado/transcritor.git /opt/transcritor/releases/<RELEASE>
sudo git -C /opt/transcritor/releases/<RELEASE> checkout --detach <COMMIT_OU_TAG_TRANSCRITOR>
cd /opt/transcritor/releases/<RELEASE>
sudo python3.10 -m venv .venv
sudo .venv/bin/python -m pip install --require-hashes --only-binary=:all: -r deploy/vps/requirements-py310-arm64.txt
sudo .venv/bin/python -m pip install --no-build-isolation --no-deps -e ./backend
.venv/bin/python -m pip check
```

O arquivo fixado inclui ferramentas de build e testes para CPython 3.10/Linux ARM64. Não use este lock no Windows. Uma versão/hash indisponível deve interromper a instalação; não retire a verificação silenciosamente. Em outras plataformas, a instalação de desenvolvimento pelo `pyproject.toml` resolve versões por intervalos e não garante o mesmo ambiente. O npm usa `frontend/package-lock.json`.

Mantenha fontes, venv e modelos sob administração (sem permissão de escrita do usuário do serviço). Para preparar o frontend na própria VPS, use uma cópia de build pertencente ao administrador, sem `sudo npm`, e copie o `dist/` resultante para `frontend/dist/` da release. Exemplo na máquina de build, na raiz da mesma versão:

```sh
cd frontend
npm ci
npm test
npm run build
```

Para transferir o build a partir do computador do administrador (na raiz da mesma versão):

```sh
tar -czf /tmp/transcritor-frontend-<RELEASE>.tar.gz -C frontend dist
scp /tmp/transcritor-frontend-<RELEASE>.tar.gz <USUARIO_ADMIN>@<IP_PUBLICO>:/tmp/
```

Na VPS nova, depois de conferir a origem/conteúdo do arquivo:

```sh
tar -tzf /tmp/transcritor-frontend-<RELEASE>.tar.gz
sudo tar -xzf /tmp/transcritor-frontend-<RELEASE>.tar.gz -C /opt/transcritor/releases/<RELEASE>/frontend --no-same-owner
sudo find /opt/transcritor/releases/<RELEASE>/frontend/dist -type d -exec chmod 0755 {} +
sudo find /opt/transcritor/releases/<RELEASE>/frontend/dist -type f -exec chmod 0644 {} +
sudo -u www-data test -r /opt/transcritor/releases/<RELEASE>/frontend/dist/index.html
```

O Nginx (`www-data` no Ubuntu) precisa atravessar os diretórios da release e ler somente os arquivos públicos de `frontend/dist/`. Os comandos acima limitam o ajuste de permissões ao build. O código deve ser legível pelo serviço, mas não gravável por ele. Nunca sirva a raiz do repositório, `.env`, venv, modelos ou `/var/lib/transcritor` pelo Nginx.

Antes de ativar, teste a nova release sem tocar na instância em execução:

```sh
cd /opt/transcritor/releases/<RELEASE>
sudo -u transcritor env TRANSCRITOR_ENGINE=mock .venv/bin/python -m pytest backend -q -rs -p no:cacheprovider
.venv/bin/python deploy/vps/test_package.py -v
```

Os testes usam áudio sintético e CLI simulado. Exija também a integração real FFmpeg/FFprobe sem skip. Execute testes de Small e Medium reais com um áudio público/autorizado no teste funcional da instalação; não coloque esse resultado no Git. Não inicie outra API na mesma porta/diretório de temporários.

## 5. Ambiente e systemd

Na release preparada:

```sh
sudo install -m 0640 -o root -g transcritor deploy/vps/.env.vps.example /etc/transcritor.env
sudo install -m 0644 deploy/vps/transcritor.service /etc/systemd/system/transcritor.service
sudo ln -s /opt/transcritor/releases/<RELEASE> /opt/transcritor/current
sudo systemd-analyze verify /etc/systemd/system/transcritor.service
sudo systemctl daemon-reload
sudo systemctl enable --now transcritor.service
sudo systemctl status transcritor.service --no-pager
curl --fail http://127.0.0.1:8765/api/v1/health
curl --fail http://127.0.0.1:8765/api/v1/capabilities
ss -ltn | grep ':8765'
```

Espere `status=ok`, `engine=whisper` e listener somente em `127.0.0.1:8765`. Health/capabilities não comprovam que o modelo carrega. Ajuste `/etc/transcritor.env` para seus caminhos reais. Não o inclua no repositório. A unidade lê esse arquivo e fixa host/porta no `ExecStart`; se mudar o listener, altere a unidade e o proxy também. Nenhum `.env` é necessário dentro da release.

`StateDirectory`, `UMask`, usuário dedicado e `ReadWritePaths` mantêm as gravações em `/var/lib/transcritor`. O processo só pode escrever ali e no `/tmp` privado. Use **um worker e uma instância**: fila/UUIDs não são compartilhados entre processos.

`enable` mantém o serviço habilitado após reinicialização; `Restart=on-failure` recupera falhas do processo. Trabalhos em memória **não sobrevivem** ao restart. Logs:

```sh
sudo journalctl -u transcritor.service -n 100 --no-pager
sudo journalctl -u transcritor.service -f
```

Trate logs como privados: não publique saída bruta, caminhos ou dados de usuários. Faça uma reinicialização planejada da nova instalação quando apropriado e confirme serviço, montagem dos volumes e HTTPS após o retorno.

## 6. HTTP Basic, Nginx e primeiro certificado

Crie o arquivo de autenticação interativamente, fora do repositório:

```sh
sudo htpasswd -cB /etc/nginx/transcritor.htpasswd <USUARIO_WEB>
sudo chown root:www-data /etc/nginx/transcritor.htpasswd
sudo chmod 0640 /etc/nginx/transcritor.htpasswd
sudo install -d -m 0755 /var/www/letsencrypt/.well-known/acme-challenge
```

Use `-c` apenas na primeira criação; para adicionar/alterar usuários, omita `-c` para preservar os demais. Não forneça a senha como argumento. O hash também é sensível. HTTP Basic só deve transportar credenciais via HTTPS.

Primeiro configure **somente HTTP**, para o desafio ACME, sem pedir login em HTTP. Crie `/etc/nginx/sites-available/transcritor` com este conteúdo, substituindo `<DOMINIO>`:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name <DOMINIO>;
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
        try_files $uri =404;
    }
    location / { return 301 https://$host$request_uri; }
}
```

Habilite o site, valide conflitos com sites existentes e emita o certificado:

```sh
sudo ln -s /etc/nginx/sites-available/transcritor /etc/nginx/sites-enabled/transcritor
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/letsencrypt -d <DOMINIO>
```

Certbot pedirá e-mail/aceite dos termos interativamente. Não configure o listener SSL antes de existirem `fullchain.pem` e `privkey.pem`. Se a validação falhar, confira DNS, IPv6 e porta 80 na Oracle e no Ubuntu.

Agora substitua o site pelo [exemplo final](../deploy/vps/nginx.conf.example), trocando `transcritor.example.com` pelo seu domínio em **todos** os pontos:

```sh
sudo install -m 0644 deploy/vps/nginx.conf.example /etc/nginx/sites-available/transcritor
sudoedit /etc/nginx/sites-available/transcritor
sudo nginx -t
sudo systemctl reload nginx
```

O exemplo preserva `/api/v1/...` no proxy, aplica Basic no servidor HTTPS inteiro, aceita até 51 MiB no envelope HTTP e deixa o backend conferir 50 MiB de arquivo. `proxy_request_buffering off` evita o spool integral antecipado no Nginx, mas não substitui limites/quota e controle de acesso. O POST termina após upload/validação; o trabalho longo é acompanhado por consultas, sem aumentar o timeout do proxy para duas horas.

Valide a proteção das duas superfícies (esperado 401 sem login) e então informe senha no prompt do curl:

```sh
curl -I https://<DOMINIO>/
curl -I https://<DOMINIO>/api/v1/health
curl --fail --user <USUARIO_WEB> https://<DOMINIO>/api/v1/health
curl --fail --user <USUARIO_WEB> https://<DOMINIO>/api/v1/capabilities
```

Abra o site, envie áudio autorizado com Small e depois Medium, confira texto, player, tempos, copiar/TXT e cancelamento/limpeza. Não salve credenciais em comandos, URLs ou capturas públicas. Valide 404 após excluir um UUID. Teste a porta 8765 de fora da VPS: ela não deve estar acessível.

## 7. Renovação de HTTPS

O método webroot mantém o desafio público em `/.well-known/acme-challenge/`; a aplicação segue protegida. Habilite o timer do pacote Ubuntu e instale um deploy hook para recarregar o certificado no Nginx após renovação bem-sucedida:

```sh
sudo install -d -m 0755 /etc/letsencrypt/renewal-hooks/deploy
sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh > /dev/null <<'SH'
#!/bin/sh
set -eu
/usr/sbin/nginx -t
/bin/systemctl reload nginx
SH
sudo chmod 0755 /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
sudo systemctl enable --now certbot.timer
sudo systemctl list-timers --all certbot.timer
sudo certbot renew --dry-run
```

Confirme o timer disponível no método de instalação escolhido e não crie agendadores duplicados. O dry-run testa a renovação; teste também o script de reload separadamente. Mantenha porta 80 e DNS funcionais. Certificados, chaves, backups do Certbot e `.htpasswd` ficam fora do Git.

## 8. Atualização e rollback

Prepare uma nova `/opt/transcritor/releases/<NOVA_RELEASE>` seguindo a seção 4: commit/tag explícito, venv próprio, dependências fixadas, testes, build e permissões. Registre a release atual e faça backup privado de `/etc/transcritor.env`, unidade e Nginx se forem alterados. Não inclua áudios em backups sem uma política de retenção/consentimento.

Avise os usuários e aguarde a fila terminar ou exporte o necessário antes de reiniciar: não há migração de trabalhos ativos. Em uma instalação com `current` já sendo um link simbólico válido:

```sh
readlink -f /opt/transcritor/current
sudo systemctl stop transcritor.service
sudo ln -s /opt/transcritor/releases/<NOVA_RELEASE> /opt/transcritor/current.next
sudo mv -Tf /opt/transcritor/current.next /opt/transcritor/current
sudo systemctl start transcritor.service
curl --fail http://127.0.0.1:8765/api/v1/health
curl --fail http://127.0.0.1:8765/api/v1/capabilities
sudo nginx -t
sudo systemctl reload nginx
```

`current.next` deve estar ausente antes da operação; não substitua um diretório real por esses comandos. A troca do link atualiza backend e frontend juntos. Revise ambiente/unidade separadamente caso a nova versão exija mudanças; então use `daemon-reload` antes de iniciar. Faça o teste funcional autenticado com os dois modelos e confira logs/temporários. Preserve pelo menos a release anterior e seus artefatos.

Para rollback, pare o serviço, faça a mesma troca de link apontando para `<RELEASE_ANTERIOR>`, restaure ambiente/unidade/Nginx se mudaram, valide configurações e inicie novamente. Refaça health/capabilities e teste funcional. Não há banco para migrar, mas os trabalhos e edições não são recuperados. Não atualize o whisper.cpp/modelos junto com a aplicação sem registrar os refs/hashes e manter uma cópia anterior para retorno.

## Referências oficiais

- [whisper.cpp: compilação e modelos](https://github.com/ggml-org/whisper.cpp).
- [Nginx: HTTP Basic](https://nginx.org/en/docs/http/ngx_http_auth_basic_module.html) e [proxy HTTP](https://nginx.org/en/docs/http/ngx_http_proxy_module.html).
- [Certbot: renovação e hooks](https://eff-certbot.readthedocs.io/en/stable/using.html#renewing-certificates).
- [systemd: ambiente e diretórios do serviço](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html); no Ubuntu 22.04, consulte também `man systemd.exec` da versão instalada.

Os comandos e exemplos foram preparados a partir do código local. A instalação Linux, `nginx -t`, `systemd-analyze verify`, emissão/renovação de certificado e reinicialização devem ser validados na máquina de destino; não foram executados na produção nesta sessão.
