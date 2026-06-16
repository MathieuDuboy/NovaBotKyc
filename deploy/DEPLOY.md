# Déploiement VPS — Nova Bot A (KYC) + Bot B (carte Interlace)

> Cible : VPS unique **107.189.16.79**, environnement **sandbox**, **sans domaine**.
> URL stable + mini app en HTTPS via **nip.io** (DNS gratuit, zéro inscription).

## URLs finales (stables)
- **Bot A (KYC + mini app)** : `https://kyc.107.189.16.79.nip.io`
  - mini app : `https://kyc.107.189.16.79.nip.io/kyc`
  - webhook Interlace : `https://kyc.107.189.16.79.nip.io/api/callback`
- **Bot B (carte)** : `https://card.107.189.16.79.nip.io`

`nip.io` : `kyc.107.189.16.79.nip.io` résout automatiquement vers `107.189.16.79`.
Aucun compte requis. (Si Let's Encrypt est rate-limité sur nip.io, voir §9 → DuckDNS.)

---

## 1. Préparer le VPS (en root)
```bash
ssh root@107.189.16.79
apt update && apt -y upgrade
# Docker + compose
curl -fsSL https://get.docker.com | sh
# Outils
apt -y install python3-venv python3-pip git nginx certbot python3-certbot-nginx ufw
# Firewall : SSH + HTTP + HTTPS uniquement (les DB restent en 127.0.0.1)
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
```

## 2. Récupérer le code
```bash
mkdir -p /opt/nova && cd /opt/nova
git clone https://github.com/MathieuDuboy/NovaBotKyc.git kyc_bot
git clone https://github.com/MathieuDuboy/NovaBotCardSandBoxInter.git interlace_bot
```
> `config/params.json` est **gitignoré** → à créer/copier à la main (secrets). Pars de
> `config/params.example.json` si présent, sinon copie ton `params.json` local par `scp`.

## 3. venv + dépendances (par bot)
```bash
cd /opt/nova/kyc_bot && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
cd /opt/nova/interlace_bot && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
# Pillow nécessaire si tu génères des images de test côté serveur :
/opt/nova/kyc_bot/venv/bin/pip install Pillow
```

## 4. Config (params.json) — on RESTE EN SANDBOX
**Bot A** `/opt/nova/kyc_bot/config/params.json` :
- `api.miniapp_url` → `https://kyc.107.189.16.79.nip.io`  ← **seule modif obligatoire**
- ⚠️ **NE PAS toucher `interlace.mode`** : doit rester **`dev`** = API **sandbox**
  (api-sandbox.interlace.money + creds sandbox). On reste 100% en sandbox.
- `telegram.env` : **laisser tel quel** (n'affecte QUE le `bot_id`, PAS Interlace).
- (optionnel) `BOT_B_USERNAME` si tu changes de Bot B.

**Bot B** `/opt/nova/interlace_bot/config/params.json` :
- rien d'obligatoire : `BOT_A_URL` vaut `http://127.0.0.1:3003` par défaut (même VPS)
- vérifier le token Telegram + les creds Interlace (compte `758535dc…`)

## 5. Infra Docker + seed (par bot)
```bash
cd /opt/nova/kyc_bot && docker compose -f config/docker-compose.sandbox.yml up -d
./venv/bin/python config/seed_sandbox.py
cd /opt/nova/interlace_bot && docker compose -f config/docker-compose.sandbox.yml up -d
./venv/bin/python config/seed_sandbox.py
```
> Ports DB isolés et bindés sur 127.0.0.1 : nova_kyc (3308/27019/6382), nova_il (3307/27018/6381). Aucun conflit, rien d'exposé.

## 6. systemd (démarrage auto + restart)
```bash
cp /opt/nova/kyc_bot/deploy/nova-kyc.service /etc/systemd/system/   # ou interlace_bot/deploy/...
cp /opt/nova/kyc_bot/deploy/nova-card.service /etc/systemd/system/
# (les fichiers .service sont dans ce dossier deploy/ ; ajuste WorkingDirectory si besoin)
systemctl daemon-reload
systemctl enable --now nova-kyc nova-card
systemctl status nova-kyc nova-card --no-pager
```

## 7. nginx + HTTPS (Let's Encrypt)
```bash
cp /opt/nova/kyc_bot/deploy/nginx-nova-bots.conf /etc/nginx/sites-available/nova-bots
ln -sf /etc/nginx/sites-available/nova-bots /etc/nginx/sites-enabled/nova-bots
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
# Certificats (génère aussi les blocs 443 + redirection) :
certbot --nginx -d kyc.107.189.16.79.nip.io -d card.107.189.16.79.nip.io \
  --non-interactive --agree-tos -m ton.email@exemple.com --redirect
```
Vérifier : `curl -I https://kyc.107.189.16.79.nip.io/health` → `200`.

## 8. Brancher Telegram + Interlace (URLs stables)
- **BotFather** (Bot A) : `/setmenubutton` → URL `https://kyc.107.189.16.79.nip.io` (ouvre la mini app KYC).
- **Interlace dashboard** (Development > Integration Settings) : webhook →
  `https://kyc.107.189.16.79.nip.io/api/callback`  → la **voie webhook automatique** marche enfin (KYC PASSED → carte créée sans intervention).
- Les 2 bots **pollent** Telegram (sortant) ; pas besoin d'exposer Bot B pour le menu carte. (Si tu ajoutes les webhooks carte/3DS OTP plus tard → `https://card.107.189.16.79.nip.io/...`.)

## 9. Si Let's Encrypt refuse nip.io (rate limit)
Alternative gratuite avec sous-domaine dédié : **DuckDNS**.
1. Crée un sous-domaine sur duckdns.org (ex. `novakyc`, `novacard`) → IP 107.189.16.79.
2. Remplace les `*.nip.io` par `novakyc.duckdns.org` / `novacard.duckdns.org` dans
   `nginx-nova-bots.conf` + le `certbot -d ...` + `api.miniapp_url` + BotFather + Interlace.

## 10. Exploitation
```bash
journalctl -u nova-kyc -f         # logs Bot A
journalctl -u nova-card -f        # logs Bot B
systemctl restart nova-kyc        # redémarrer après une MAJ de code
cd /opt/nova/kyc_bot && git pull && systemctl restart nova-kyc   # déployer une MAJ
```

## Sécurité (rappels)
- `config/params.json` / `credentials.json` : secrets, **jamais commit** (déjà gitignorés).
- DB/Redis bindés 127.0.0.1 (jamais exposés) ; firewall = 22/80/443 seulement.
- App uvicorn bindée 127.0.0.1 (seul nginx y accède).
- Renouvellement TLS : certbot installe un timer auto (`systemctl list-timers | grep certbot`).
