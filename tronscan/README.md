# Tronscan API Client

A comprehensive Python client for interacting with the Tronscan API.

## Features

- Complete coverage of all Tronscan API endpoints
- Asynchronous and synchronous methods
- Automatic API key loading from config
- Robust error handling

## Installation

```bash
# If installing in your project
pip install -e .
```

## Usage

### Asynchronous Usage

```python
import asyncio
from tronscan import TronscanClient

async def main():
    # Initialize client
    client = TronscanClient()
    
    try:
        # Get account information
        account_info = await client.get_account("TZ4UXDV5ZhNW7fb2AMSbgfAEZ7hWsnYS2g")
        print(f"Account Balance: {account_info.get('balance', 0)}")
        
        # Get latest blocks
        latest_block = await client.get_latest_block()
        print(f"Latest Block: {latest_block.get('number', 0)}")
        
        # Search for a transaction, address, or token
        search_results = await client.search("TRX")
        print(f"Search Results: {search_results}")
    finally:
        # Always close the client
        await client.close()

# Run the async function
asyncio.run(main())
```

### Synchronous Usage

```python
from tronscan import TronscanClient

# Initialize client
client = TronscanClient()

# Get account information
account_info = client.get_account_sync("TZ4UXDV5ZhNW7fb2AMSbgfAEZ7hWsnYS2g")
print(f"Account Balance: {account_info.get('balance', 0)}")

# Get latest blocks
latest_block = client.get_latest_block_sync()
print(f"Latest Block: {latest_block.get('number', 0)}")

# Search for a transaction, address, or token
search_results = client.search_sync("TRX")
print(f"Search Results: {search_results}")
```

## Available Methods

### Account Endpoints

- `get_account_list` - Get list of accounts
- `get_account` - Get account information
- `get_account_tokens` - Get account's token list
- `get_account_votes` - Get the voted list for an account
- `get_account_resources` - Get account resources
- `get_account_stake2_resources` - Get stake 2.0 resources for an account
- `get_account_approval_list` - Get approval list for an account
- `get_account_auth_change_records` - Get authorization change records for an account
- `get_account_analysis` - Get daily analytics data for an account
- `get_participate_project` - Get projects an account has participated in
- `get_account_token_asset_overview` - Get account wallet token overview
- `get_multiple_chain_address` - Find if an address exists on other chains

### Transaction Endpoints

- `get_transactions` - Get account transactions
- `get_transaction_info` - Get detailed information about a transaction
- `get_transfers` - Get token transfers
- `get_nft_transfers` - Get NFT transfers
- `get_internal_transactions` - Get internal transactions

### Token Endpoints

- `get_token_list` - Get list of tokens
- `get_token_info` - Get token information
- `get_token_holders` - Get token holders
- `get_token_trc20` - Get TRC20 token information
- `get_nft_list` - Get NFT list
- `get_token_price_history` - Get token price history

### Contract Endpoints

- `get_contract` - Get smart contract information
- `get_contract_transactions` - Get transactions for a contract
- `get_contracts` - Get list of contracts
- `get_contract_events` - Get events for a contract
- `get_contract_code` - Get contract code
- `get_contract_security_info` - Get security information for a contract

### Block Endpoints

- `get_block_by_num` - Get block by number
- `get_latest_block` - Get latest block information
- `get_blocks` - Get list of blocks
- `get_block_tx_id` - Get transactions for a block by hash
- `get_block_transactions` - Get transactions for a block by number

### Witness (Super Representative) Endpoints

- `get_witnesses` - Get list of Super Representatives
- `get_witness_statistics` - Get statistics about witnesses
- `get_witness_details` - Get details about a specific witness
- `get_witness_votes` - Get votes for a witness

### Homepage & Search Endpoints

- `search` - Search for blocks, addresses, transactions, tokens or contracts
- `get_system_status` - Get TRON system status
- `get_top_accounts` - Get top accounts by balance
- `get_top_tokens` - Get top tokens by market cap

### Wallet Endpoints

- `get_wallet_trc20_balance` - Get TRC20 balance for a wallet
- `get_wallet_transactions` - Get transactions for a wallet
- `get_wallet_stats` - Get statistics for a wallet

### Statistics Endpoints

- `get_market_data` - Get market data
- `get_transaction_stats` - Get transaction statistics
- `get_single_chart_data` - Get data for a specific chart
- `get_defi_stats` - Get DeFi statistics

### Deep Analysis Endpoints

- `get_address_growth` - Get address growth over time
- `get_transaction_growth` - Get transaction growth over time
- `get_transaction_count_by_type` - Get transaction count by type
- `get_energy_consumption` - Get energy consumption over time

### Security Service Endpoints

- `get_address_security_info` - Get security information for an address
- `get_transaction_security_info` - Get security information for a transaction
- `get_contract_security_info` - Get security information for a contract

### Protocol Revenue Endpoints

- `get_protocol_fee_status` - Get current protocol fee status
- `get_protocol_fee_history` - Get protocol fee history
- `get_protocol_fee_distribution` - Get protocol fee distribution

### Synchronous Versions

- `get_account_sync` - Synchronous version of get_account
- `get_transactions_sync` - Synchronous version of get_transactions
- `get_token_info_sync` - Synchronous version of get_token_info
- `get_latest_block_sync` - Synchronous version of get_latest_block
- `search_sync` - Synchronous version of search

## Configuration

The client will automatically look for a Tronscan API key in:
1. The provided API key during initialization
2. `config.TRONSCAN_API_KEY` attribute
3. `params.json` file with a structure like:
   ```json
   {
     "tronscan": {
       "api_key": "your-api-key-here"
     }
   }
   ```

## Documentation

For more information about the Tronscan API, see the official documentation:
https://docs.tronscan.org/api-endpoints/ 