// Nova/Interlace Test UI JS
function log(msg, type = 'info') {
    const logDiv = document.getElementById('test-log');
    const entry = document.createElement('div');
    entry.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    entry.className = type;
    logDiv.appendChild(entry);
    logDiv.scrollTop = logDiv.scrollHeight;
}

function showResponse(divId, data, isError = false) {
    const div = document.getElementById(divId);
    div.textContent = JSON.stringify(data, null, 2);
    div.className = 'response ' + (isError ? 'error' : 'success');
}

async function postJSON(url, body) {
    const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
    let data;
    try {
        data = await resp.json();
    } catch (e) {
        data = { error: 'Invalid JSON response', status: resp.status };
    }
    return { status: resp.status, data };
}

// Deposit form handler
if (document.getElementById('deposit-form')) {
    document.getElementById('deposit-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const form = e.target;
        // Debug logging for all fields
        console.log("form.action", form.action);
        console.log("form.address", form.address);
        console.log("form.amount", form.amount);
        console.log("form.asset", form.asset);
        console.log("form.asset_type", form.asset_type);
        console.log("form.created_at", form.created_at);
        console.log("form.status", form.status);
        console.log("form.tx_id", form.tx_id);
        console.log("form.tx_link", form.tx_link);
        console.log("form.type", form.type);
        console.log("form.updated_at", form.updated_at);
        const payload = {
            version: "1",
            action: form.action.value || "create",
            object: {
                address: form.address.value,
                amount: form.amount.value,
                asset: form.asset.value,
                asset_type: form.asset_type.value,
                control: null,
                created_at: form.created_at.value,
                dchain_id: "trc20usdt",
                done_at: form.created_at.value,
                fee: "0.0",
                high_risk: null,
                status: form.status.value,
                tag: null,
                tx_id: form.tx_id.value,
                tx_link: form.tx_link.value,
                type: form.type.value,
                updated_at: form.updated_at.value,
                uuid: crypto.randomUUID()
            }
        };
        log('Simulating deposit: ' + JSON.stringify(payload));
        const res = await postJSON('/api/test/simulate_deposit', payload);
        showResponse('deposit-response', res.data, res.status !== 200);
    });
}

// CardTransaction form handler
if (document.getElementById('cardtransaction-form')) {
    document.getElementById('cardtransaction-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const form = e.target;
        const payload = {
            data: {
                id: form.id.value || crypto.randomUUID(),
                accountId: form.accountId.value || '',
                cardId: form.cardId.value || '',
                currency: form.currency.value || 'USD',
                amount: parseFloat(form.amount.value) || 0,
                fee: parseFloat(form.fee.value) || 0,
                type: form.type.value || 'Consumption',
                clientTransactionId: form.clientTransactionId.value || `tid_${crypto.randomUUID()}`,
                remark: form.remark.value || '',
                detail: form.detail.value || '',
                status: form.status.value || 'Pending',
                transactionTime: form.transactionTime.value || new Date().toISOString(),
                transactionCurrency: form.transactionCurrency.value || 'USD',
                transactionAmount: parseFloat(form.transactionAmount.value) || 0
            },
            createTime: Date.now(),
            sign: crypto.randomUUID().replace(/-/g, ''),
            businessStatus: form.businessStatus.value || 'Success',
            id: crypto.randomUUID(),
            businessType: "CardTransaction"
        };
        log('Simulating CardTransaction: ' + JSON.stringify(payload));
        const res = await postJSON('/api/callback', payload);
        showResponse('cardtransaction-response', res.data, res.status !== 200);
    });
}

// Custom event handler (only deposit and card_transaction)
document.getElementById('custom-send').addEventListener('click', async () => {
    let json;
    try {
        json = JSON.parse(document.getElementById('custom-json').value);
    } catch (e) {
        showResponse('custom-response', { error: 'Invalid JSON' }, true);
        return;
    }
    const type = document.getElementById('custom-type').value;
    let url = '';
    if (type === 'deposit') url = '/api/test/simulate_deposit';
    else if (type === 'card_transaction') url = '/api/callback';
    else {
        showResponse('custom-response', { error: 'Unknown event type' }, true);
        return;
    }
    log('Simulating custom event (' + type + '): ' + JSON.stringify(json));
    const res = await postJSON(url, json);
    showResponse('custom-response', res.data, res.status !== 200);
});

// AssetDeposit form handler
if (document.getElementById('assetdeposit-form')) {
    document.getElementById('assetdeposit-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const form = e.target;
        const payload = {
            data: {
                chain: form.chain.value,
                amount: form.amount.value,
                fee: form.fee.value,
                updateTime: form.updateTime.value,
                transactionHash: form.transactionHash.value,
                accountId: form.accountId.value,
                createTime: form.createTime.value,
                currency: form.currency.value,
                from: form.from.value,
                id: form.id.value,
                to: form.to.value,
                balanceId: form.balanceId.value,
                status: form.status.value
            },
            sign: form.sign.value,
            businessStatus: form.businessStatus.value,
            accountId: form.accountId.value,
            createTime: form.createTime.value,
            id: crypto.randomUUID(),
            businessType: "AssetsDeposit",
            remarks: form.remarks.value
        };
        log('Simulating AssetDeposit: ' + JSON.stringify(payload));
        const res = await postJSON('/api/callback', payload);
        showResponse('assetdeposit-response', res.data, res.status !== 200);
    });
} 