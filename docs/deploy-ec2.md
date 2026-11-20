# Deploy su AWS EC2 con Docker Compose

Il servizio `journal-live` gira 24/7 su una piccola istanza EC2: legge dati di
mercato pubblici via ccxt, apre trade virtuali e li chiude su TP/SL. Non usa API
key e non esegue ordini reali.

## 1. Istanza

- **AMI:** Amazon Linux 2023
- **Tipo:** `t3.micro` o `t4g.micro` (l'immagine è multi-architettura)
- **Regione:** una regione europea, es. `eu-south-1` (Milano) o `eu-central-1`.
  Binance rifiuta le richieste dagli IP statunitensi.
- **Security group:** in ingresso solo la porta 22 dal tuo IP. La porta 8766 non va aperta.

## 2. Docker

```bash
sudo dnf install -y docker git
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user        # poi esci e rientra in SSH

# plugin compose
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -sSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
docker compose version
```

## 3. Avvio

```bash
git clone https://github.com/stefanosepe/trading-engine.git
cd trading-engine
docker compose up -d --build
docker compose ps                        # STATUS deve diventare "healthy"
docker compose logs -f journal-live
```

Parametri opzionali in un file `.env` accanto al compose:

```
SYMBOL=ETH/USDT
TIMEFRAME=4h
SL_PCT=0.03
TP_PCT=0.06
```

## 4. Consultare lo stato

La porta è legata a `127.0.0.1` dell'istanza, quindi si raggiunge con un tunnel SSH:

```bash
ssh -i chiave.pem -L 8766:localhost:8766 ec2-user@<IP-ISTANZA>
# in un altro terminale, sul tuo computer:
curl http://localhost:8766/status
```

## 5. Aggiornare

```bash
git pull
docker compose up -d --build
```

Il container riparte da solo dopo un crash o un riavvio dell'istanza
(`restart: unless-stopped`). I log ruotano a 3 file da 10 MB.

> Lo stato del journal è in memoria: un riavvio del container azzera le statistiche.
