# Nova Banking Bot and API

> 📦 **Ce dépôt = BOT A (KYC).** Il fonctionne avec **Bot B (carte)** =
> dépôt `NovaBotCardSandBoxInter`, déployés côte à côte sous `/opt/nova/`.
>
> 🧭 **Nouveau sur le projet ? Commence par la doc de reprise :**
> - [`deploy/ARCHITECTURE.md`](deploy/ARCHITECTURE.md) — vue d'ensemble, modèle de données, flux
> - [`deploy/ONBOARDING.md`](deploy/ONBOARDING.md) — reprendre avec tes propres bots → pré-prod → prod
> - [`deploy/PROD_CHECKLIST.md`](deploy/PROD_CHECKLIST.md) · [`deploy/PARCOURS_ET_MESSAGES.md`](deploy/PARCOURS_ET_MESSAGES.md) · [`deploy/DEPLOY.md`](deploy/DEPLOY.md)

This repository contains the backend code for the Nova Banking Telegram Bot and the associated API.

## Features

- **Telegram Bot**: A powerful banking bot for handling users' banking needs
- **API Server**: Serves the Mini App and provides endpoints for bank operations
- **Mini App**: A web-based UI that can be launched from within Telegram

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure the application:
   - Copy `params.example.json` to `params.json` if it doesn't exist
   - Edit `params.json` to add your Telegram bot token, MongoDB connection string, etc.

3. Run the application:
   ```bash
   python run_app.py
   ```

## Configuration

All configuration is stored in `params.json`. The key sections are:

- **telegram**: Bot token and channel ID
- **google_sheets**: Spreadsheet ID and credentials path
- **api**: Port and allowed origins
- **paths**: Directories for the mini app and language files
- **mongodb**: Connection URI, database name, and collections
- **redis**: Host, port, and database number
- **webhook**: Configuration for running the bot with webhooks

## Running in Production

For production environments, you can use the webhook mode instead of polling:

1. Set `"enabled": true` in the webhook section of `params.json`
2. Configure a proper domain and SSL
3. Set the webhook URL, path, and secret token

## Running Components Separately

You can run just the API or just the bot using:

```bash
# Run only the API server
python run_app.py --api-only

# Run only the Telegram bot
python run_app.py --bot-only
```

## Mini App Development

The Mini App files are located in the `miniapp/` directory. When the API server runs, these files are served under the `/static/` path.

## Troubleshooting

- **Network errors**: If you encounter connection errors to Telegram, ensure you have proper internet connectivity and that your firewall allows outgoing connections.
- **Static files not loading**: Ensure the `miniapp` directory exists and contains all required files.
- **Bot not responding**: Check your bot token and ensure your webhook or polling setup is correct.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

cd /home/Nova && source venv/bin/activate && uvicorn app:app --host 0.0.0.0 --port 3001 --workers 4