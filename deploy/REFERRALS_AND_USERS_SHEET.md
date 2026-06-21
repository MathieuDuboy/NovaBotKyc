# Nova — Google Sheets : codes de parrainage + liste des users

Permet au client de **gérer les codes de parrainage** depuis un Google Sheet et d'avoir
une **liste de ses clients en lecture**. Les outils vivent dans le repo **Bot B**
(`interlace_bot/`).

> Source de vérité des frais = table MySQL `referralcodes` (lue par le calcul des frais).
> La feuille est la **surface de gestion** ; un script **synchronise** feuille → MySQL.

## 1. Configurer le Sheets (params.json Bot B → `google_sheets`)
```json
"google_sheets": {
  "spreadsheet_id": "<ID du Google Sheet>",
  "credentials_path": "config/credentials.json",   // service account
  "users_sheet": "users"
}
```
- Créer un **service account** Google Cloud (API Google Sheets activée), télécharger le
  JSON → `interlace_bot/config/credentials.json`.
- **Partager le Spreadsheet** avec l'email du service account (droit Éditeur).
- (Sans config → la feature est simplement désactivée, le bot tourne quand même.)

## 2. Onglet `ReferralCodes` (géré par le client)
Colonnes **A..E** :
| A — referal code | B — deposit fee (%) | C — foregin fee (%) | D — name | E — valid |
|---|---|---|---|---|
| FAM123 | 2.5 | 2.5 | Famille Dupont | 1 |

- **valid** : `1` ou **vide** = **actif** ; `0` (ou non/no/false) = désactivé.
- (Le script `generate_referral_sheet.py` peut pré-générer 10 000 codes.)

### Appliquer les codes (feuille → MySQL)
```bash
cd /opt/nova/interlace_bot
./venv/bin/python sync_referrals.py --dry-run   # vérifie ce qui serait importé
./venv/bin/python sync_referrals.py             # applique (upsert dans referralcodes)
```
Le client édite la feuille → relance la sync → les nouveaux frais/codes s'appliquent.
(Optionnel : mettre en **cron** toutes les X minutes pour que ce soit automatique.)

## 3. Onglet `users` (liste en lecture)
```bash
cd /opt/nova/interlace_bot
./venv/bin/python export_users.py
```
Écrit/rafraîchit l'onglet `users` : `USER_ID, Nom, Email, KYC, Nb cartes, Cartes,
Total déposé, Adresses, Créé le`. **Lecture seule** (le client consulte ; ré-exporter
pour rafraîchir). Idéal en **cron** (ex. toutes les 5 min) :
```
*/5 * * * * cd /opt/nova/interlace_bot && ./venv/bin/python export_users.py >> /var/log/nova_export_users.log 2>&1
```

## Notes
- Les codes sont stockés dans `referralcodes` (`referal code` UNIQUE) ; la sync fait un
  **upsert** (met à jour les frais/validité des codes existants, insère les nouveaux).
- Un client **sans code** ou avec un code **non valide** → frais **par défaut** (fallback).
- La liste users vient de la base **Bot B** (interlace_accounts + cards + topup_requests).
