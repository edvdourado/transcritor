# Teste real da v1.1 na Oracle, sem deploy

Este roteiro é para execução manual pelo administrador. Nenhum comando SSH foi executado na preparação. Apenas a estrutura **local** foi inspecionada; caminhos, recursos e versão do Whisper da VPS ainda precisam ser confirmados pelos comandos abaixo. Os exemplos antigos em `DEPLOY.md` usam `/opt`; não os copie sobre a instalação existente em `/data/transcritor/app`.

Fluxo exclusivo do teste:

```text
Navegador Windows → Vite 127.0.0.1:5174
                 → túnel Windows 127.0.0.1:18766
                 → SSH → VPS 127.0.0.1:8766 → fontes v1.1 isoladas

Produção: Nginx → 127.0.0.1:8765 → /data/transcritor/app (permanece em execução)
```

Não há instalação de dependências/modelos, `pip install -e`, cópia de `.env`, build remoto, alteração de Nginx/firewall, `daemon-reload` ou reinício de produção. O interpretador/venv existente é reutilizado **somente para suas dependências**. `-I -B`, precedência explícita de `backend/`, verificação de cada módulo `app.*` e do contrato `segments` impedem que a instalação editável de produção forneça o código da aplicação. Se qualquer verificação falhar, o teste não abre a porta.

O teste usa uma unidade systemd **transitória própria**, não habilitada no boot, com um worker, sem reload, CPU limitada a metade de um núcleo, uma thread Whisper, memória limitada e escrita restrita ao seu runtime. Isso reduz interferência, mas não garante latência ou disponibilidade absoluta de processos que compartilham a mesma VPS. Não prossiga sem folga de RAM/disco; teste um áudio curto e um modelo por vez. Se a produção degradar, encerre imediatamente **somente a unidade de teste**. Se não houver recursos para Medium com a reserva indicada, adie esse teste; não retire os limites para fazê-lo passar.

## 1. PowerShell: criar e transferir o snapshot atual

Use o alias SSH existente ou substitua `ubuntu@HOST_ORACLE`. Se sua chave/porta estiverem no SSH config, o mesmo alias atende `ssh` e `scp`. Não use `git archive HEAD`: a v1.1 ainda está sem commit, e esse comando enviaria uma revisão antiga.

```powershell
Set-Location C:\Projetos\transcritor
$Vps = 'ubuntu@HOST_ORACLE'
$Run = 'v11-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + ([guid]::NewGuid().ToString('N').Substring(0,8))
$Archive = "transcritor-$Run.tar.gz"
$Package = Join-Path (Get-Location) "tmp\$Archive"
& .\.venv\Scripts\python.exe deploy/vps/package.py --output $Package
if ($LASTEXITCODE -ne 0) { throw 'Empacotamento falhou' }
tar -tzf $Package
if ($LASTEXITCODE -ne 0) { throw 'Pacote ilegível' }
Get-Content "$Package.sha256"
Write-Host "GUARDE O ID: $Run"
# Somente staging novo no HOME do usuário SSH; não substitui arquivos existentes.
ssh $Vps "umask 077; mkdir -p ~/transcritor-review && mkdir ~/transcritor-review/$Run"
if ($LASTEXITCODE -ne 0) { throw 'Staging já existe ou está indisponível' }
scp $Package "$Package.sha256" "${Vps}:transcritor-review/$Run/"
if ($LASTEXITCODE -ne 0) { throw 'Transferência falhou' }
ssh $Vps
```

O empacotador inclui os bytes atuais, manifesto SHA-256 e o inicializador `deploy/vps/review.py`. Exclui venv, `.git`, `.env` real, modelos, gravações, temporários e builds. Não faça push.

## 2. SSH/Bash: inspecionar a instalação real, somente leitura

Execute no shell remoto aberto acima. Preserve esta sessão para as próximas etapas. Substitua o ID pelo impresso no PowerShell.

```bash
set -euo pipefail
RUN='v11-SUBSTITUA-PELO-ID-GERADO'
[[ "$RUN" =~ ^v11-[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$ ]]
STAGING="$HOME/transcritor-review/$RUN"
ROOT="/data/transcritor/tests/$RUN"
UNIT="transcritor-review-$RUN.service"
ARCHIVE="transcritor-$RUN.tar.gz"
cd "$STAGING"
sha256sum -c "$ARCHIVE.sha256"

uname -m
systemd --version | head -n 1
sudo systemctl show transcritor.service \
  -p ActiveState -p SubState -p MainPID -p NRestarts -p User -p Group \
  -p WorkingDirectory -p ExecStart -p EnvironmentFiles
PROD_PID=$(systemctl show transcritor.service -p MainPID --value)
PROD_RESTARTS=$(systemctl show transcritor.service -p NRestarts --value)
test "$PROD_PID" -gt 0
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8765/api/v1/health
printf '\n'
sudo ss -ltnp '( sport = :8765 or sport = :8766 )'
test -z "$(ss -H -ltn 'sport = :8766')"
free -m
df -h /data/transcritor
```

Confirme ARM64 (`aarch64`), produção ativa e 8766 livre. Anote o **caminho do Python no ExecStart**, preservando `.venv/bin/python`; resolver `/proc/PID/exe` com `readlink -f` perde a identidade do venv e pode selecionar um Python sem dependências. O caminho abaixo é uma hipótese a confirmar, não um caminho descoberto remotamente.

```bash
PROD_PYTHON='/data/transcritor/app/.venv/bin/python' # ajuste ao ExecStart real
test -x "$PROD_PYTHON"
# Mostrar apenas configurações de ferramentas/modelos, nunca o ambiente completo.
sudo "$PROD_PYTHON" -I -B - "$PROD_PID" <<'PY'
import sys
from pathlib import Path
from dotenv import dotenv_values
env = dict(item.split('=', 1) for item in Path(f'/proc/{sys.argv[1]}/environ').read_bytes().decode().split('\0') if '=' in item)
fallback = dotenv_values('/data/transcritor/app/.env')
for key in ('WHISPER_CLI_PATH', 'WHISPER_MODEL_SMALL', 'WHISPER_MODEL_MEDIUM',
            'FFMPEG_PATH', 'FFPROBE_PATH', 'WHISPER_LANGUAGE'):
    print(f'{key}={env.get(key, fallback.get(key)) or "[não encontrado; conferir EnvironmentFiles]"}')
PY
```

O ambiente do processo tem precedência sobre o `.env` da raiz, como no backend. Se a instalação usar outro arquivo/organização, confira localmente os `EnvironmentFiles` mostrados, selecionando apenas essas chaves. Não execute `source` no ambiente de produção e não copie esse arquivo. Identifique o ref do Whisper com `git -C DIRETORIO_REAL_DO_WHISPER rev-parse HEAD`, se for um checkout; não atualize nem recompile.

## 3. SSH/Bash: preparar a cópia e conferir importações

Preencha os três caminhos Whisper com os valores reais descobertos; FFmpeg/FFprobe também devem ser caminhos absolutos. Escolha um usuário **já existente**, não root, com leitura do venv, CLI e modelos. Em geral é o usuário do serviço. Se `User` estiver vazio ou for root, informe outro usuário existente apropriado; não altere contas ou permissões de produção para este teste.

```bash
RUN_USER=$(systemctl show transcritor.service -p User --value)
test -n "$RUN_USER" && test "$RUN_USER" != root
RUN_GROUP=$(id -gn "$RUN_USER")
CLI='/CAMINHO_REAL/whisper-cli'
SMALL='/CAMINHO_REAL/ggml-small.bin'
MEDIUM='/CAMINHO_REAL/ggml-medium.bin'
FFMPEG='/usr/bin/ffmpeg'   # ajuste se o valor real for diferente
FFPROBE='/usr/bin/ffprobe'

# Nova pasta irmã da produção. Um ID existente interrompe a preparação.
sudo test -d /data/transcritor/tests || sudo install -d -m 0711 /data/transcritor/tests
sudo -u "$RUN_USER" test -x /data/transcritor/tests
sudo mkdir "$ROOT"
sudo chown "root:$RUN_GROUP" "$ROOT"
sudo chmod 0750 "$ROOT"
sudo install -d -m 0750 -o root -g "$RUN_GROUP" "$ROOT/app"
sudo tar -xzf "$STAGING/$ARCHIVE" -C "$ROOT/app" --no-same-owner --no-same-permissions
sudo sh -c 'cd "$1" && sha256sum -c MANIFEST.sha256' sh "$ROOT/app"
sudo chgrp -R "$RUN_GROUP" "$ROOT/app"
sudo find "$ROOT/app" -type d -exec chmod 0750 {} +
sudo find "$ROOT/app" -type f -exec chmod 0640 {} +
sudo install -d -m 0700 -o "$RUN_USER" -g "$RUN_GROUP" "$ROOT/run" "$ROOT/run/tmp"

TEST_ENV=(
  'PATH=/usr/bin:/bin' 'LANG=C.UTF-8' "HOME=$ROOT/run"
  'TRANSCRITOR_ENGINE=whisper' 'TRANSCRITOR_HOST=127.0.0.1' 'TRANSCRITOR_PORT=8766'
  "TRANSCRITOR_TEMP_DIR=$ROOT/run/tmp"
  "WHISPER_CLI_PATH=$CLI" "WHISPER_MODEL_SMALL=$SMALL" "WHISPER_MODEL_MEDIUM=$MEDIUM"
  'WHISPER_THREADS=1' 'WHISPER_LANGUAGE=pt' 'WHISPER_TIMEOUT_SECONDS=7200'
  "FFMPEG_PATH=$FFMPEG" "FFPROBE_PATH=$FFPROBE"
  'FFPROBE_TIMEOUT_SECONDS=15' 'FFMPEG_TIMEOUT_SECONDS=120' 'UPLOAD_TIMEOUT_SECONDS=120'
  'MAX_UPLOAD_SIZE_MB=50' 'MAX_AUDIO_DURATION_SECONDS=300' 'FILE_RETENTION_SECONDS=3600'
)
# Não instala nada e não abre listener. Aborta se dependência/arquivo estiver ausente.
sudo -u "$RUN_USER" env -i "${TEST_ENV[@]}" \
  "$PROD_PYTHON" -I -B "$ROOT/app/deploy/vps/review.py" --check
```

Todas as linhas `IMPORT app...` devem apontar para **`$ROOT/app/backend/app/`**. A linha `REVIEW` deve mostrar **`$ROOT/run/tmp`**. O script rejeita `.env` dentro do snapshot, código de produção, configuração diferente de Whisper/8766 e contrato sem `segments`. O teste compartilha apenas bibliotecas instaladas e os arquivos dos modelos. Não execute `pip` nesse venv. Uma dependência incompatível interrompe o roteiro; prepare um venv separado em outra etapa, em vez de modificar o existente.

## 4. SSH/Bash: iniciar somente o serviço transitório de teste

O exemplo reserva pelo menos 3 GiB de RAM disponível além dos 3 GiB que o teste pode consumir. É um critério conservador, não uma medição da carga máxima futura da produção. Com limite insuficiente, o teste pode terminar por OOM; isso deve ser registrado como teste inconclusivo. Não aumente limites sem reavaliar a margem real.

```bash
MEMORY_MIB=3072
RESERVE_MIB=3072
AVAILABLE_MIB=$(awk '/^MemAvailable:/ {print int($2/1024)}' /proc/meminfo)
test "$AVAILABLE_MIB" -ge "$((MEMORY_MIB + RESERVE_MIB))"
test "$(df -Pm /data/transcritor | awk 'NR==2 {print $4}')" -ge 1024
test "$(stat -fc %T /sys/fs/cgroup)" = cgroup2fs
grep -qw memory /sys/fs/cgroup/cgroup.controllers
grep -qw cpu /sys/fs/cgroup/cgroup.controllers
test -z "$(ss -H -ltn 'sport = :8766')"
test "$(systemctl show transcritor.service -p MainPID --value)" = "$PROD_PID"
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8765/api/v1/health

# Se uma verificação posterior falhar nesta sessão, pare apenas o teste.
trap 'sudo systemctl stop "$UNIT" || true' ERR
sudo systemd-run --unit="$UNIT" --service-type=exec \
  --uid="$RUN_USER" --gid="$RUN_GROUP" --working-directory="$ROOT/app/backend" \
  --property=CPUQuota=50% --property=Nice=10 --property=IOWeight=10 \
  --property="MemoryMax=${MEMORY_MIB}M" --property=MemorySwapMax=0 \
  --property=OOMPolicy=stop --property=OOMScoreAdjust=500 \
  --property=ProtectSystem=strict --property=PrivateTmp=yes --property=NoNewPrivileges=yes \
  --property="ReadWritePaths=$ROOT/run" --property=UMask=0077 \
  --property=KillMode=control-group --property=TimeoutStopSec=30s --property=RuntimeMaxSec=2h \
  "${TEST_ENV[@]/#/--setenv=}" \
  "$PROD_PYTHON" -I -B "$ROOT/app/deploy/vps/review.py"

# A criação da unidade não comprova que a API já está pronta: aguarde saúde real.
READY=0
for i in {1..20}; do
  if curl --fail --silent --max-time 2 http://127.0.0.1:8766/api/v1/health; then READY=1; break; fi
  sleep 1
done
if test "$READY" != 1; then sudo systemctl stop "$UNIT"; exit 1; fi
curl --fail --silent --show-error http://127.0.0.1:8766/api/v1/capabilities
sudo journalctl -u "$UNIT" -n 40 --no-pager
sudo ss -ltnp '( sport = :8765 or sport = :8766 )'
sudo systemctl show "$UNIT" -p MainPID -p MemoryMax -p MemorySwapMax -p CPUQuotaPerSecUSec -p ControlGroup
CGROUP=$(systemctl show "$UNIT" -p ControlGroup --value)
sudo cat "/sys/fs/cgroup$CGROUP/memory.max" "/sys/fs/cgroup$CGROUP/memory.swap.max" "/sys/fs/cgroup$CGROUP/cpu.max"
test "$(systemctl show transcritor.service -p MainPID --value)" = "$PROD_PID"
test "$(systemctl show transcritor.service -p NRestarts --value)" = "$PROD_RESTARTS"
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8765/api/v1/health
```

Espere `engine=whisper`, imports no snapshot e listener **somente `127.0.0.1:8766`**. Nos arquivos de cgroup, espere `3221225472` (3 GiB), `0` (swap) e quota equivalente a 50% de um núcleo (por exemplo `50000 100000`). Se os limites/listener não corresponderem, pare `$UNIT` antes de enviar áudio. O teto aplica-se também aos subprocessos FFmpeg e Whisper. A API usa sua própria fila em memória e um diretório de sessão abaixo de `run/tmp`; não enxerga os trabalhos da produção.

Em outro terminal SSH, acompanhe durante o teste (Ctrl+C encerra apenas o monitor):

```bash
watch -n 3 'curl --fail --silent --max-time 2 http://127.0.0.1:8765/api/v1/health; echo; systemctl show transcritor.service -p MainPID -p NRestarts -p ActiveState; free -m'
```

Mantenha também a página pública de produção aberta e confirme que continua respondendo. Não envie o áudio de teste por essa página. O health isolado não prova disponibilidade do Nginx nem qualidade da inferência.

## 5. PowerShell: abrir o túnel e o Vite exclusivo

Em outro terminal Windows, deixe o túnel em primeiro plano:

```powershell
$Vps = 'ubuntu@HOST_ORACLE' # mesmo host/alias da transferência
ssh -N -T -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L 127.0.0.1:18766:127.0.0.1:8766 $Vps
```

Não use `-g`, `-R`, `0.0.0.0` ou regras de firewall. Porta local ocupada causa falha; não finalize um processo desconhecido. Feche o túnel anterior ou investigue o conflito. Se o servidor SSH negar encaminhamento, interrompa e consulte o administrador; o roteiro não altera `sshd_config`.

Em outro PowerShell, na árvore local **que gerou o pacote**, sem editar fontes durante a validação:

```powershell
Invoke-RestMethod http://127.0.0.1:18766/api/v1/health
Invoke-RestMethod http://127.0.0.1:18766/api/v1/capabilities # engine deve ser whisper
Set-Location C:\Projetos\transcritor\frontend
npm.cmd run dev -- --config vite.review.config.ts
```

Use **esse comando**, não `npm run dev` sozinho: a configuração usual continua apontando para 8765. A configuração de revisão fixa `127.0.0.1:5174`, exige porta livre e encaminha todo `/api` (upload, polling, áudio e exclusão) somente para `127.0.0.1:18766`. Não usa variáveis `VITE_*`, CORS, nem Nginx. Se o túnel cair, as chamadas falham; não há fallback para produção.

Em mais um PowerShell, confirme o caminho completo e abra o navegador:

```powershell
$Api = 'http://127.0.0.1:5174/api/v1'
Invoke-RestMethod "$Api/health"
Invoke-RestMethod "$Api/capabilities"
Start-Process 'http://127.0.0.1:5174'
```

## 6. Validar um áudio real, primeiro Small, depois Medium

Use fala autorizada em português de 20–60 segundos, com pausas e palavras reconhecíveis perto de marcas de tempo conhecidas (`WHISPER_LANGUAGE=pt` no roteiro). Não adicione áudio/transcrição ao Git. Aplique o roteiro sequencialmente aos dois modelos; não carregue Medium enquanto Small ou outro teste ainda estiver processando.

1. Em `127.0.0.1:5174`, confirme **Whisper real**, selecione **Small**, envie o arquivo e aguarde conclusão. No DevTools/Network, registre o `id` da resposta de `POST /api/v1/jobs`. Não use um ID de produção.
2. No PowerShell abaixo, consulte o trabalho **pelo Vite**. Confirme estado, engine, duração e tempos em segundos. Os trechos devem cobrir a fala em momentos plausíveis, sem fator 10/100/1.000; o backend já normaliza os offsets do CLI. O JSON bruto do Whisper é temporário e removido pelo adaptador; não será preservado por este teste.
3. Ative **Revisão sincronizada**. Reproduza desde o início; confirme que o destaque acompanha a fala e que silêncio entre intervalos não retém destaque. Avance/volte pelo player. Clique em três trechos distantes, conferindo salto para `start` e início da reprodução.
4. Navegue com Tab, setas, Home/End e ative com Enter/Espaço. Confira foco visível, sem deslocar a página inteira. Repita com janela estreita/abas móveis.
5. Teste **0,75×, 1×, 1,25×, 1,5× e 2×** no painel Áudio. Compare avanço do relógio com tempo real; os timestamps originais permanecem iguais e os cliques continuam levando ao mesmo momento.
6. Desative a revisão, edite uma frase e inclua uma quebra de linha. Reative: os segmentos continuam originais. Copie e exporte TXT **com o modo sincronizado ativo** e confira que ambos contêm o texto editado. Volte ao textarea e confirme preservação. O TXT não é enviado ao servidor.
7. Antes de sair, guarde o resultado localmente se necessário. Clique **Nova transcrição**, confirme descarte apenas depois de copiar/exportar, repita com **Medium** e confira modo inicialmente desligado, velocidade 1× e ausência de destaque/áudio do trabalho anterior.

Consulta e verificações executáveis, para cada ID obtido pela interface:

```powershell
$Vps = 'ubuntu@HOST_ORACLE' # defina também neste terminal
$Api = 'http://127.0.0.1:5174/api/v1'
$JobId = ([guid](Read-Host 'ID do trabalho de teste no DevTools')).ToString()
$Job = Invoke-RestMethod "$Api/jobs/$JobId"
if ($Job.engine -ne 'whisper' -or $Job.state -ne 'completed' -or $Job.segments.Count -lt 1) { throw 'Sem resultado Whisper sincronizável; conferir estado/erro/logs' }
foreach ($Segment in $Job.segments) {
    $Start = [double]$Segment.start
    $End = [double]$Segment.end
    if ([string]::IsNullOrWhiteSpace($Segment.text) -or [double]::IsNaN($Start) -or [double]::IsInfinity($Start) -or [double]::IsNaN($End) -or [double]::IsInfinity($End) -or $Start -lt 0 -or $End -le $Start) { throw 'Segmento inválido' }
}
$Job | Select-Object id, model, state, engine, audio_duration_seconds, processing_seconds
$Job.segments | Select-Object -First 8 start, end, text | Format-Table -Wrap
if (($Job.segments | Measure-Object end -Maximum).Maximum -gt $Job.audio_duration_seconds + 1) { Write-Warning 'Fim além da duração: conferir os tempos do modelo ouvindo o áudio' }
$Playback = Invoke-WebRequest -UseBasicParsing "$Api/jobs/$JobId/audio" -Headers @{ Range = 'bytes=0-31' }
if ($Playback.StatusCode -ne 206 -or $Playback.Headers['Content-Type'] -notlike 'audio/wav*') { throw 'Reprodução/range inesperado' }
# Prova adicional: esse ID deve existir somente na API de teste (404 na produção).
ssh $Vps "curl --silent --output /dev/null --write-out '%{http_code}' --max-time 5 http://127.0.0.1:8765/api/v1/jobs/$JobId"
# Esperado: 404. Não apague nem cancele trabalhos na API de produção.
```

Registre localmente: ID do snapshot/hash, ref do Whisper, modelo, duração do áudio, número de segmentos, três pares `start`/momento ouvido, velocidades e resultado de TXT/clipboard, PID/NRestarts da produção antes/depois. Não interprete diferenças de transcrição entre Small e Medium como falha de sincronização. Erro de memória/timeout ou timestamps ausentes deve ser registrado com o modelo e logs privados; não substitua por mock para declarar aprovação.

## 7. Encerrar e verificar a produção

Primeiro copie/exporte as edições. Na sessão SSH original:

```bash
sudo systemctl stop "$UNIT" # somente transcritor-review-v11-....service
! systemctl is-active --quiet "$UNIT"
test -z "$(ss -H -ltn 'sport = :8766')"
sudo find "$ROOT/run/tmp" -mindepth 1 -maxdepth 2 -print
systemctl is-active transcritor.service
test "$(systemctl show transcritor.service -p MainPID --value)" = "$PROD_PID"
test "$(systemctl show transcritor.service -p NRestarts --value)" = "$PROD_RESTARTS"
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8765/api/v1/health
```

O encerramento normal limpa os áudios da sessão. Se o processo tiver sido morto abruptamente/OOM, arquivos podem permanecer **somente no runtime do teste**; confira a listagem antes de qualquer limpeza manual. Não há `rm -rf` neste roteiro. O snapshot e staging permanecem para auditoria privada. A unidade é transitória, não habilitada, e não usa arquivos em `/etc/systemd/system`.

No Windows, pressione **Ctrl+C** no Vite e no túnel e feche o navegador de teste. Confirme que a página pública continua disponível. Se perdeu a sessão SSH, recupere `RUN` pelo ID guardado, defina `ROOT=/data/transcritor/tests/ID` e `UNIT=transcritor-review-ID.service`; use apenas o comando `systemctl stop` dessa unidade. O limite de duas horas também encerra o teste, não a produção.

Referências dos recursos utilizados: [unidades transitórias e ambiente no systemd 249](https://www.freedesktop.org/software/systemd/man/249/systemd-run.html) e [limites de CPU/memória no systemd 249](https://www.freedesktop.org/software/systemd/man/249/systemd.resource-control.html). Os limites efetivos são conferidos nos arquivos do cgroup da própria VPS antes da inferência.
