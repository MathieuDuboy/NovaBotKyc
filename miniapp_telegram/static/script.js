// === GESTION DES PAGES ===
let previousPage = 'home';
let apiConfig = null;
let currentCardNumber = '';

// Initialize Telegram WebApp
let tg = window.Telegram.WebApp;
tg.expand();

// Global variables
let userId = null;
let userData = null;
let cardData = null;
let transactions = [];

// Secure fetch wrapper: adds the required header for Telegram miniapp security
const TELEGRAM_MINIAPP_TOKEN = window.TELEGRAM_MINIAPP_TOKEN || ''; // Token injected dynamically by the server

function secureFetch(url, options = {}) {
  const initData = (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData) ? window.Telegram.WebApp.initData : '';
  options.headers = {
    ...((options && options.headers) || {}),
    'X-Telegram-Miniapp-Token': TELEGRAM_MINIAPP_TOKEN,
    'X-Telegram-InitData': initData
  };
  return fetch(url, options);
}

// Helper function to get a valid Date from a transaction object
function getTransactionDate(tx) {
    var raw = tx.transaction_time || tx.timestamp;
    if (!raw) return new Date();
    if (typeof raw === 'string') {
        raw = raw.trim();
        // Remove colon in timezone offset if present (e.g., +00:00 -> +0000)
        raw = raw.replace(/([+-]\d{2}):(\d{2})$/, '$1$2');
    }
    // Try to parse the raw string using Date.parse
    var parsed = Date.parse(raw);
    if (!isNaN(parsed)) {
        return new Date(parsed);
    }
    var num = Number(raw);
    if (!isNaN(num)) {
        if (String(num).length === 10) {
            return new Date(num * 1000);
        }
        return new Date(num);
    }
    return new Date(raw);
}

// Bootstrap alert helper
function showAlert(message, type = 'info') {
    // type can be 'success', 'danger', 'warning', 'info'
    const alertPlaceholder = document.getElementById('liveAlertPlaceholder');
    if (!alertPlaceholder) return;
    alertPlaceholder.innerHTML = `
        <div class="alert alert-${type} alert-dismissible fade show" role="alert">
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
    `;
    // Optionally auto-dismiss after 3 seconds
    setTimeout(() => {
        alertPlaceholder.innerHTML = '';
    }, 3000);
}

function changeLanguage(language) {
    console.log("Changing language to: " + language);
    // Use static path for translations
    const translationsUrl = '/static/translations.json';
    $.getJSON(translationsUrl, function (data) {
        let translations = data[language];

        // Update page texts with translations
        $('#title').text(translations.title);
        $('#user-id').text(translations.user_id);
        $('#top-up-button').text(translations.top_up);
        $('#block-button').text(translations.block_card);
        $('#order-card-button').text(translations.order_card);
        $('#no-transactions-message').text(translations.no_transactions);
        $('#settings-header').text(translations.settings);
        $('#settings-header-bis').text(translations.settings);
        $('#contact-support-header').text(translations.contact_support);

        // Update card-related messages
        $('#user_card_none .card-message').text(translations.start_message);
        $('#user_card_creating .card-message').text(translations.card_creating);
        $('#user_card_creating p.text-center').text(translations.card_creating_message);

        // Store current language for later use
        window.currentLanguage = language;
    }).fail(function (jqXHR, textStatus, errorThrown) {
        console.error("Failed to load translations:", textStatus, errorThrown);
    });
}

// Par défaut, charger la langue anglaise
changeLanguage('en');

// State variable for CVV reveal
const eyeIconHTML = '<i class="fas fa-eye"></i>';

$(document).ready(function () {
    const userInfoDiv = $("#user-info");

    // Add minimal positioning fallback for card last digits
    // This is a fallback in case CSS doesn't work properly
    function applyCardDigitsStyling() {
        $('.card-last-digits').each(function () {
            $(this).css({
                'position': 'absolute',
                'bottom': '20px',
                'left': '25px',
                'z-index': '999'
            });
        });
    }

    // Apply initially with a delay to ensure DOM is ready
    setTimeout(applyCardDigitsStyling, 500);

    // Watch for DOM changes and reapply styling when needed
    const observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
            if (mutation.addedNodes.length > 0) {
                // If nodes were added, check if our card is present and apply styling
                applyCardDigitsStyling();
            }
        });
    });

    // Start observing with configuration
    observer.observe(document.body, { childList: true, subtree: true });

    // Fetch environment setting and user ID from config.json
    function getEnvVariables() {
        const configUrl = '/config.json';
        return fetch(configUrl)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(config => {
                const env = {};
                env['ENV'] = config.ENV;
                env['USER_ID'] = config.USER_ID;
                env['api_base'] = config.api_base;
                env['version'] = config.version;
                apiConfig = config.API;
                return env;
            });
    }

    getEnvVariables().then(env => {
        const environment = env.ENV;
        userId = env.USER_ID;
        console.log(`Running in ${environment} mode with user ID: ${userId}`);

        // Always update the user-info field with the user ID
        userInfoDiv.text(userId);

        // Enable deposit button when userId is set
        $('#deposit-button').prop('disabled', false).removeClass('disabled');

        if (environment === 'dev') {
            // Simulate Telegram WebApp environment for development
            window.Telegram = { WebApp: { ready: () => { }, initDataUnsafe: { user: { id: userId } } } };
            console.log('Running in development mode');

            // In dev mode, get data immediately
            loadUserData();
        } else {
            // Production mode
            if (window.Telegram && window.Telegram.WebApp) {
                console.log('Telegram WebApp API available');
                window.Telegram.WebApp.ready();
                const user = window.Telegram.WebApp.initDataUnsafe ? window.Telegram.WebApp.initDataUnsafe.user : null;
                if (user && user.id) {
                    console.log('User information:', user);
                    userId = user.id;
                    userInfoDiv.text(userId);
                    // Enable deposit button when userId is set in production
                    $('#deposit-button').prop('disabled', false).removeClass('disabled');
                    loadUserData();
                } else {
                    console.log('User information not available');
                    userInfoDiv.text('Unknown');
                    showError('User ID not found. Please reload the app inside Telegram.');
                }
            } else {
                console.log('Telegram WebApp API not available.');
            }
        }
    }).catch(error => {
        console.error("Error loading configuration:", error);
        showError("Failed to load configuration. Please refresh the page.");
    });

    $("#settingsSection input[type='radio']").on('change', function () {
        var selectedValue = $(this).val();
        console.log("Selected radio value: " + selectedValue);
        changeLanguage(selectedValue);
    });

    // Updated event binding for the flip button
    $('.credit-card').on('click', '.flip-button', function (e) {
        e.stopPropagation();
        var creditCard = $(this).closest('.credit-card');

        // Check if card is in creating state
        if (creditCard.hasClass('card-creating')) {
            console.log('Card is in issuance state, flipping disabled');
            return;
        }

        // Check if flipping away from the back
        if (creditCard.hasClass('is-flipped')) {
            // Reset CVV display before flipping
            $('.cvv-container .cvv-display').html(eyeIconHTML);
            console.log('Flipping away from back. Reset CVV.');
        }

        creditCard.toggleClass('is-flipped');
        if (creditCard.hasClass('is-flipped')) {
            updateCardDetails();
        }
        console.log('Flip button clicked, credit-card is now flipped:', creditCard.hasClass('is-flipped'));
    });

    // Add handler for transaction details back button
    $(document).on('click', '#transaction-details-back', function () {
        $('#transaction-details').addClass('d-none');
        $('#transactions-view').removeClass('d-none');
    });
});

function showPage(pageId) {
    $(`#${previousPage}`).addClass('d-none');
    $(`#${pageId}`).removeClass('d-none');
    previousPage = pageId;

    // Show back button only when not on home page
    $('#backButton').toggleClass('d-none', pageId === 'home');
}

function goBack() {
    showPage('home');
}

// Helper function to group transactions by date
function groupTransactionsByDate(transactions) {
    const grouped = {};

    transactions.forEach(tx => {
        const date = new Date(tx.transaction_time || tx.timestamp);
        const dateStr = date.toISOString().split('T')[0]; // YYYY-MM-DD

        if (!grouped[dateStr]) {
            grouped[dateStr] = [];
        }
        grouped[dateStr].push(tx);
    });

    return grouped;
}

// Format date header for transaction groups
function formatDateHeader(dateStr) {
    const date = new Date(dateStr);
    return date.toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    });
}

// Function to display transaction details
function showTransactionDetails(transaction) {
    const modal = document.getElementById('transactionModal');
    const modalTitle = document.getElementById('transactionModalTitle');
    const modalBody = document.getElementById('transactionModalBody');

    if (!modal || !modalTitle || !modalBody) {
        console.error('Modal elements not found');
        return;
    }

    // Set title with status badge below
    const statusClass = getStatusBadgeClass(transaction.status);
    modalTitle.innerHTML = `
        <div class="d-flex flex-column align-items-center">
            <div class="mb-2">Transaction Details</div>
        </div>
        <span class="badge ${statusClass}">${transaction.status}</span>
    `;

    // Initialize html variable
    let html = '<div class="transaction-details">';

    if (transaction.type === 'deposit') {
        html += `
            <div class="mb-3">
                <div class="d-flex justify-content-between align-items-center">
                    <div class="text-break" style="max-width: 70%;">
                        <strong>Deposit Amount</strong>
                    </div>
                    <div class="text-end">
                        <strong>$${transaction.amount.toFixed(2)}</strong>
                    </div>
                </div>
            </div>
            <div class="mb-3">
                <div class="d-flex justify-content-between align-items-center">
                    <div class="text-break" style="max-width: 70%;">
                        <strong>Final Amount</strong>
                    </div>
                    <div class="text-end">
                        <strong>$${transaction.final_amount.toFixed(2)}</strong>
                    </div>
                </div>
            </div>
            <div class="mb-3">
                <div class="d-flex justify-content-between align-items-center">
                    <div class="text-break" style="max-width: 70%;">
                        <strong>Total Fee</strong>
                    </div>
                    <div class="text-end">
                        <strong>$${(transaction.amount - transaction.final_amount).toFixed(2)}</strong>
                    </div>
                </div>
            </div>`;

        if (transaction.virtual_card_fee && transaction.virtual_card_fee > 0) {
            html += `
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <div class="text-break" style="max-width: 70%;">
                        <strong>Virtual Card Fee Creation</strong>
                    </div>
                    <div class="text-end">
                        <strong>$${transaction.virtual_card_fee.toFixed(2)}</strong>
                    </div>
                </div>`;
        }

        // Add deposit-specific details
        html += `
            <div class="mb-3">
                <div class="text-break">
                    <strong>dChain ID:</strong> ${transaction.dchain_id || 'N/A'}
                </div>
            </div>
            <div class="mb-3">
                <div class="text-break">
                    <strong>TX Link:</strong> 
                    <a href="${transaction.tx_link}" target="_blank" class="text-break">
                        ${transaction.tx_link || 'N/A'}
                    </a>
                </div>
            </div>`;
    } else {
        // For card transactions, show all fees and totals
        // Show total amounts
        let totalUSD = transaction.amount + transaction.fee;
        if (transaction.consumption_fee && transaction.consumption_fee.usd) {
            totalUSD += transaction.consumption_fee.usd;
        }
        if (transaction.nova_fee_usd) {
            totalUSD += transaction.nova_fee_usd;
        }

        let totalForeign = transaction.transaction_amount;
        // if (transaction.consumption_fee && transaction.consumption_fee.foreign) {
        //     totalForeign += transaction.consumption_fee.foreign;
        // }
        // if (transaction.nova_fee_foreign) {
        //     totalForeign += transaction.nova_fee_foreign;
        // }

        html += `
            <div class="mb-3">
                <div class="d-flex justify-content-between align-items-center">
                    <div class="text-break" style="max-width: 70%;">
                        <strong>Transaction Amount</strong>
                    </div>
                    <div class="text-end">
                        <strong>$${totalUSD.toFixed(2)}</strong>
                    </div>
                </div>
            </div>`;

        if (transaction.transaction_amount) {
            html += `
                <div class="mb-3">
                    <div class="d-flex justify-content-between align-items-center">
                        <div class="text-break" style="max-width: 70%;">
                            <strong>Transaction Amount (${transaction.transaction_currency})</strong>
                        </div>
                        <div class="text-end">
                            <strong>${totalForeign.toFixed(2)} ${transaction.transaction_currency}</strong>
                        </div>
                    </div>
                </div>`;
        }

        // Add transaction details for non-deposit transactions
        html += `
            <div class="mb-3">
                <div class="text-break">
                    <strong>Detail:</strong> ${transaction.detail || 'N/A'}
                </div>
            </div>`;
    }

    // Add common transaction details
    html += `
        <div class="mb-3">
            <div class="text-break">
                <strong>Transaction ID:</strong> ${transaction.tid || 'N/A'}
            </div>
        </div>
        <div class="mb-3">
            <div class="text-break">
                <strong>Date & Time:</strong> ${getTransactionDate(transaction).toLocaleString()}
            </div>
        </div>`;

    // Close the transaction-details div
    html += '</div>';

    modalBody.innerHTML = html;

    // Initialize and show the Bootstrap modal
    const modalInstance = new bootstrap.Modal(modal);
    modalInstance.show();
}

// Back button handler for transaction details
$(document).on('click', '#transaction-back-btn', function () {
    $('#details').addClass('d-none');
    $('#home').removeClass('d-none');
});

// === INITIALISATION TELEGRAM ===

// Load user data from the API
async function loadUserData() {
    console.log('Starting loadUserData...');

    // Hide all card views and enrollment view, then show loader
    document.querySelectorAll('.card-view, #user_card_none').forEach(view => {
        console.log('Hiding view:', view.id);
        view.classList.add('d-none');
    });
    document.getElementById('user_card_loader').classList.remove('d-none');

    try {
        console.log('Fetching user data for userId:', userId);
        const response = await secureFetch(`/api/gets/asdfdd2343fsafsfapW/${userId}`);
        const data = await response.json();
        console.log('Received data:', data);

        if (data.success) {
            userData = data.user;
            cardData = data.card;
            transactions = data.transactions || [];

            console.log('Loaded card data:', cardData);
            console.log('Loaded transactions data:', transactions);

            updateUserInfo();
            updateCardDisplay();

            // Ensure transaction loader is hidden before displaying transactions
            const transactionLoader = document.getElementById('transaction_loader');
            if (transactionLoader) {
                transactionLoader.classList.add('d-none');
            }

            displayTransactions(transactions);

            // Directly initialize the back card number
            if (cardData && cardData.cardNumber) {
                const cardNumberElem = $('.card-info.back .card-number');
                if (cardNumberElem.length) {
                    const rawNumber = cardData.cardNumber.replace(/\s+/g, '');
                    const formattedNumber = rawNumber.replace(/(\d{4})/g, '$1 ').trim();
                    cardNumberElem.html(`
                        <span style="margin-right: 10px;">${formattedNumber}</span>
                        <button class="copy-button" style="background: none; border: none; color: white; cursor: pointer; padding: 5px;">
                            <i class="fas fa-copy"></i>
                        </button>
                    `);

                    // Add click handler for copy button
                    cardNumberElem.find('.copy-button').off('click').on('click', function (e) {
                        e.preventDefault();
                        e.stopPropagation();
                        navigator.clipboard.writeText(rawNumber).then(() => {
                            $(this).find('i')
                                .removeClass('fa-copy')
                                .addClass('fa-check');
                            setTimeout(() => {
                                $(this).find('i')
                                    .removeClass('fa-check')
                                    .addClass('fa-copy');
                            }, 1000);
                        }).catch(err => {
                            console.error('Copy failed:', err);
                        });
                    });
                }
            }
        } else {
            console.error('Failed to load user data:', data);
            showError('Failed to load user data');
        }
    } catch (error) {
        console.error('Error loading user data:', error);
        showError('Error loading user data');
    } finally {
        // Ensure loaders are hidden
        const userCardLoader = document.getElementById('user_card_loader');
        const transactionLoader = document.getElementById('transaction_loader');
        if (userCardLoader) userCardLoader.classList.add('d-none');
        if (transactionLoader) transactionLoader.classList.add('d-none');
    }
}

// Update user information display
function updateUserInfo() {
    if (userData) {
        document.getElementById('user-info').textContent = userData.userId || 'Unknown';
        // Set referral code if available
        const referral = userData.referralCode || userData.referral_code || '';
        document.getElementById('referral-code').textContent = referral;
    }
}

// Update card display based on card status
function updateCardDisplay() {
    console.log('Updating card display with data:', cardData);

    const cardLoader = document.getElementById('user_card_loader');
    const cardFind = document.getElementById('user_card_find');
    const cardNone = document.getElementById('user_card_none');
    const cardCreating = document.getElementById('user_card_creating');
    const blockButton = document.getElementById('block-card-button');
    const unblockButton = document.getElementById('unblock-card-button');
    const depositButton = document.getElementById('deposit-button');

    // Debug log for elements
    console.log('Card elements:', {
        cardLoader: !!cardLoader,
        cardFind: !!cardFind,
        cardNone: !!cardNone,
        cardCreating: !!cardCreating,
        blockButton: !!blockButton,
        unblockButton: !!unblockButton,
        depositButton: !!depositButton
    });

    // Hide all card views first
    if (cardLoader) cardLoader.classList.add('d-none');
    if (cardFind) cardFind.classList.add('d-none');
    if (cardNone) cardNone.classList.add('d-none');
    if (cardCreating) cardCreating.classList.add('d-none');

    if (!cardData) {
        console.log('No card data available');
        if (cardNone) cardNone.classList.remove('d-none');
        return;
    }

    console.log('Card status:', cardData.cardStatus);

    // Show card for both active and frozen states
    if (cardData.cardStatus === 'active' || cardData.cardStatus === 'frozen' || cardData.cardStatus === 'blocked') {
        console.log('Showing card view for status:', cardData.cardStatus);

        // Make sure cardFind is visible
        if (cardFind) {
            cardFind.classList.remove('d-none');
            cardFind.style.display = 'block';
            cardFind.style.visibility = 'visible';
            cardFind.style.opacity = '1';
        }

        // Update button states based on card status
        if (cardData.cardStatus === 'frozen' || cardData.cardStatus === 'blocked') {
            console.log('Should show only UNBLOCK button');
            // Hide block button and show unblock button
            if (blockButton) {
                blockButton.classList.add('d-none');
            }
            if (unblockButton) {
                unblockButton.classList.remove('d-none');
                // Ensure the icon is visible
                const unblockIcon = unblockButton.querySelector('i');
                if (unblockIcon) {
                    unblockIcon.className = 'fas fa-unlock';
                    unblockIcon.style.fontSize = '1.2rem';
                }
            }
            // Disable deposit button
            if (depositButton) {
                depositButton.disabled = true;
                depositButton.classList.add('disabled');
            }
        } else if (cardData.cardStatus === 'active') {
            console.log('Should show only BLOCK button');
            // Hide unblock button and show block button
            if (unblockButton) {
                unblockButton.classList.add('d-none');
            }
            if (blockButton) {
                blockButton.classList.remove('d-none');
                // Ensure the icon is visible and properly set
                const blockIcon = blockButton.querySelector('i');
                if (blockIcon) {
                    blockIcon.className = 'fas fa-lock';
                    blockIcon.style.fontSize = '1.2rem';
                    blockIcon.style.minWidth = '1.2rem';
                    blockIcon.style.display = 'inline-block';
                    console.log('Block icon updated:', blockIcon.className, blockIcon.style.cssText);
                }
            }
            // Enable deposit button
            if (depositButton) {
                depositButton.disabled = false;
                depositButton.classList.remove('disabled');
            }
        } else {
            console.log('Unknown card status, hiding both block/unblock');
            if (blockButton) blockButton.classList.add('d-none');
            if (unblockButton) unblockButton.classList.add('d-none');
        }

        // Force a reflow to ensure styles are applied
        if (blockButton) {
            blockButton.offsetHeight;
        }
        if (unblockButton) {
            unblockButton.offsetHeight;
        }
        // Show valid/unvalid image
        const validImg = document.getElementById('valid-img');
        const unvalidImg = document.getElementById('unvalid-img');
        if (validImg && unvalidImg) {
            if (cardData.cardStatus === 'active') {
                validImg.classList.remove('d-none');
                unvalidImg.classList.add('d-none');
            } else {
                validImg.classList.add('d-none');
                unvalidImg.classList.remove('d-none');
            }
        }
        // Always update card details regardless of status
        updateCardDetails();
    } else if (cardData.cardStatus === 'creating') {
        console.log('Card is being created');
        if (cardCreating) cardCreating.classList.remove('d-none');
    } else {
        console.log('No valid card status, showing none view');
        if (cardNone) cardNone.classList.remove('d-none');
    }

    // After toggling button visibility, log their classList and computed display style
    if (blockButton) {
        console.log('blockButton classList:', Array.from(blockButton.classList));
        console.log('blockButton computed display:', window.getComputedStyle(blockButton).display);
    }
    if (unblockButton) {
        console.log('unblockButton classList:', Array.from(unblockButton.classList));
        console.log('unblockButton computed display:', window.getComputedStyle(unblockButton).display);
    }
}

// Update card details in the UI
function updateCardDetails() {
    if (!cardData) {
        console.log('No card data available');
        return;
    }

    console.log('Updating card details with:', {
        cardNumber: cardData.cardNumber,
        cardStatus: cardData.cardStatus
    });

    // Update card number with asterisks (front)
    const cardNumber = cardData.cardNumber || '';
    const lastDigits = document.querySelector('.card-last-digits');
    if (lastDigits) {
        lastDigits.textContent = '*' + cardNumber.slice(-4);
        console.log('Updated front card number:', lastDigits.textContent);
    }

    // Update CVV display
    const cvvDisplay = document.querySelector('.cvv-display');
    if (cvvDisplay) {
        // Initialize with eye icon
        cvvDisplay.innerHTML = eyeIconHTML;

        // Remove all existing event listeners
        const newCvvDisplay = cvvDisplay.cloneNode(true);
        cvvDisplay.parentNode.replaceChild(newCvvDisplay, cvvDisplay);

        // Add new click handler
        newCvvDisplay.addEventListener('click', function (e) {
            e.stopPropagation(); // Prevent card flip

            // Toggle between eye icon and CVV
            if (this.innerHTML.includes('fa-eye')) {
                console.log('CVV value:', cardData.cvv); // Debug log
                this.textContent = cardData.cvv || '';
            } else {
                this.innerHTML = eyeIconHTML;
            }
        });
    }

    // Update other card details with null checks
    const balanceElem = document.querySelector('.balance');
    if (balanceElem) balanceElem.textContent = cardData.balance || '0.00';

    const expiryElem = document.querySelector('.expiry-value');
    if (expiryElem) expiryElem.textContent = cardData.validDate || '';

    // Update card status indicators
    const validImg = document.getElementById('valid-img');
    const unvalidImg = document.getElementById('unvalid-img');
    if (validImg && unvalidImg) {
        if (cardData.cardStatus === 'active') {
            validImg.classList.remove('d-none');
            unvalidImg.classList.add('d-none');
        } else {
            validImg.classList.add('d-none');
            unvalidImg.classList.remove('d-none');
        }
    }

    // --- Update back of the card ---
    if (cardData.cardNumber) {
        console.log('Updating back of card with number:', cardData.cardNumber);
        const cardNumberElem = $('.card-info.back .card-number');
        if (cardNumberElem.length) {
            // Remove all spaces first, then format
            const rawNumber = cardData.cardNumber.replace(/\s+/g, '');
            const formattedNumber = rawNumber.replace(/(\d{4})/g, '$1 ').trim();
            console.log('Formatted card number for back:', formattedNumber);

            cardNumberElem.html(`
                <span style="margin-right: 10px;">${formattedNumber}</span>
                <button class="copy-button" style="background: none; border: none; color: white; cursor: pointer; padding: 5px;">
                    <i class="fas fa-copy"></i>
                </button>
            `);

            // Add click handler specifically to the button
            cardNumberElem.find('.copy-button').off('click').on('click', function (e) {
                e.preventDefault();
                e.stopPropagation();

                // Copy text without spaces
                navigator.clipboard.writeText(rawNumber).then(() => {
                    $(this).find('i')
                        .removeClass('fa-copy')
                        .addClass('fa-check');
                    setTimeout(() => {
                        $(this).find('i')
                            .removeClass('fa-check')
                            .addClass('fa-copy');
                    }, 1000);
                }).catch(err => {
                    console.error('Copy failed:', err);
                });
            });
        } else {
            console.log('Could not find .card-info.back .card-number element');
        }
    } else {
        console.log('No card number available in cardData');
    }

    // Set expiry date (back)
    if (expiryElem) {
        expiryElem.textContent = cardData.validDate || 'MM/YY';
    }

    // Set CVV (back)
    const cvvDisplayBack = document.querySelector('.cvv-display');
    if (cvvDisplayBack) {
        // Initialize with eye icon
        cvvDisplayBack.innerHTML = eyeIconHTML;

        // Remove all existing event listeners
        const newCvvDisplay = cvvDisplayBack.cloneNode(true);
        cvvDisplayBack.parentNode.replaceChild(newCvvDisplay, cvvDisplayBack);

        // Add new click handler
        newCvvDisplay.addEventListener('click', function (e) {
            e.stopPropagation(); // Prevent card flip

            // Toggle between eye icon and CVV
            if (this.innerHTML.includes('fa-eye')) {
                this.textContent = cardData.cvv || '';
            } else {
                this.innerHTML = eyeIconHTML;
            }
        });
    }
}

// Display transactions in the list
function displayTransactions(transactions) {
    console.log('Starting displayTransactions with:', transactions);

    window.transactionsCache = transactions;
    const transactionList = document.getElementById('transaction_find');
    const transactionLoader = document.getElementById('transaction_loader');
    const transactionNone = document.getElementById('transaction_none');

    if (!transactionList || !transactionLoader || !transactionNone) {
        console.error('Transaction elements not found:', {
            transactionList: !!transactionList,
            transactionLoader: !!transactionLoader,
            transactionNone: !!transactionNone
        });
        return;
    }

    // Hide loader
    transactionLoader.classList.add('d-none');
    console.log('Transaction loader hidden');

    // Clear existing transactions
    transactionList.innerHTML = '';

    if (!transactions || transactions.length === 0) {
        console.log('No transactions to display');
        transactionList.classList.add('d-none');
        transactionNone.classList.remove('d-none');
        return;
    }

    // Show transaction list and hide empty state
    transactionList.classList.remove('d-none');
    transactionNone.classList.add('d-none');
    console.log('Transaction list displayed');

    // Display transactions
    transactions.forEach((tx, index) => {
        console.log(`Processing transaction ${index}:`, tx);

        const transactionElement = document.createElement('li');
        transactionElement.className = 'list-group-item transaction-row';

        // Ensure we have a valid transaction ID
        const transactionId = tx.id || tx.tid;
        if (!transactionId) {
            console.error('Transaction missing ID:', tx);
            return;
        }

        transactionElement.setAttribute('data-transaction-id', transactionId);

        // Add a data attribute to identify deposit transactions
        if (tx.type === 'deposit') {
            transactionElement.setAttribute('data-transaction-type', 'deposit');
        }

        // Calculate total amount including all fees
        let totalAmount, totalCurrency;
        if (tx.type === 'deposit') {
            totalAmount = tx.amount;
            totalCurrency = tx.asset.toUpperCase();
        } else {
            // For card transactions, include all fees
            if (tx.transaction_amount && tx.transaction_currency) {
                // Foreign currency transaction
                totalAmount = tx.transaction_amount;
                // Add consumption fee in foreign currency
                // if (transaction.consumption_fee && transaction.consumption_fee.foreign) {
                //     totalAmount += transaction.consumption_fee.foreign;
                // }
                // // Add nova fee in foreign currency
                // if (transaction.nova_fee_foreign) {
                //     totalAmount += transaction.nova_fee_foreign;
                // }
                totalCurrency = tx.transaction_currency;
            } else {
                // USD transaction
                totalAmount = tx.amount;
                // Add consumption fee in USD
                if (tx.consumption_fee && tx.consumption_fee.usd) {
                    totalAmount += tx.consumption_fee.usd;
                }
                // Add nova fee in USD
                if (tx.nova_fee_usd) {
                    totalAmount += tx.nova_fee_usd;
                }
                totalCurrency = tx.currency;
            }
        }

        transactionElement.innerHTML = `
            <div class="d-flex justify-content-between align-items-center">
                <div>
                    <h6 class="mb-0">${tx.detail || (tx.type.charAt(0).toUpperCase() + tx.type.slice(1))}</h6>
                    <small class="text-muted">${getTransactionDate(tx).toLocaleString()}</small>
                </div>
                <div class="text-end">
                    <span class="badge ${getStatusBadgeClass(tx.status)}">${tx.type === 'deposit' && tx.status ? tx.status.charAt(0).toUpperCase() + tx.status.slice(1) : tx.status}</span>
                    <div class="transaction-amount">${totalAmount.toFixed(2)} ${totalCurrency}</div>
                </div>
            </div>
        `;
        transactionList.appendChild(transactionElement);
    });

    console.log('Finished displaying transactions');
}

// Add delegated click handler for transaction rows
$(document).on('click', '.transaction-row', function () {
    const transactionId = $(this).data('transaction-id');
    const transactionType = $(this).data('transaction-type');
    console.log('Clicked transaction:', { transactionId, transactionType });

    if (!transactionId) {
        console.error('No transaction ID found');
        return;
    }

    // Try to find the transaction in the cache using different ID fields
    const transaction = window.transactionsCache.find(tx => {
        // Check if the transaction ID matches any of the ID fields
        const txIds = [
            tx.id,
            tx.tid,
            tx.tx_id,
            tx._id
        ].map(id => String(id)); // Convert all IDs to strings for comparison

        // If the clicked ID is numeric, also check if it matches the numeric part of any hash
        if (!isNaN(transactionId)) {
            return txIds.some(id =>
                id === String(transactionId) ||
                id.endsWith(String(transactionId))
            );
        }

        // For non-numeric IDs, do exact match
        return txIds.includes(String(transactionId));
    });

    console.log('Found transaction:', transaction);

    if (transaction) {
        // Ensure transaction.type is set correctly for deposits
        if (transactionType === 'deposit') {
            transaction.type = 'deposit';
        }
        console.log('Showing transaction details for:', transaction);
        showTransactionDetails(transaction);
    } else {
        console.error('Transaction not found in cache. Available transactions:', window.transactionsCache);
    }
});

// Back button handler for details page
$(document).on('click', '#details .btn', function () {
    $('#details').addClass('d-none');
    $('#home').removeClass('d-none');
});

// Helper function to get badge class based on status
function getStatusBadgeClass(status) {
    switch (status) {

        case 'Processing':
            return 'bg-info';
        case 'Pending':
            return 'bg-info';
        case 'Completed':
            return 'bg-success';
        case 'Done':
            return 'bg-success';
        case 'Failed':
            return 'bg-danger';
        case 'Cancelled':
            return 'bg-danger';
        default:
            return 'bg-secondary';
    }
}

// === GESTION DES ERREURS ===
const errorDiv = $('<div></div>')
    .css({
        padding: "10px",
        background: "#ff4d4d",
        color: "white",
        "border-radius": "5px",
        "margin-top": "10px",
        display: "none"
    })
    .appendTo('body');

async function getData(userId) {
    try {
        console.log('Starting getData for user:', userId);

        // Hide all card views and enrollment view, then show loader
        document.querySelectorAll('.card-view, #user_card_none').forEach(view => {
            console.log('Hiding view:', view.id);
            view.classList.add('d-none');
        });
        document.getElementById('user_card_loader').classList.remove('d-none');

        // Hide all transaction views and show loader
        document.getElementById('transaction_find').classList.add('d-none');
        document.getElementById('transaction_none').classList.add('d-none');
        document.getElementById('transaction_seeall').classList.add('d-none');
        document.getElementById('transaction_loader').classList.remove('d-none');

        const response = await secureFetch(`/api/gets/asdfdd2343fsafsfapW/${userId}`);
        if (!response.ok) {
            throw new Error('Failed to fetch user data');
        }

        const data = await response.json();
        console.log('Received data:', data);

        // Hide loaders
        document.getElementById('user_card_loader').classList.add('d-none');
        document.getElementById('transaction_loader').classList.add('d-none');

        // Check if we have valid card data
        if (!data.card || !data.card.cardStatus) {
            console.log('No valid card data found');
            document.getElementById('user_card_none').classList.remove('d-none');
            return;
        }

        // Scenario 1: No user data - Need to enroll
        if (!data.user) {
            console.log('Scenario 1: No user data - Need to enroll');
            document.getElementById('user_card_none').classList.remove('d-none');
            return;
        }

        // Scenario 2: User exists but card is in ISSUANCE state
        if (data.card.cardStatus === 'ISSUANCE') {
            console.log('Scenario 2: Card in ISSUANCE state');
            document.getElementById('user_card_creating').classList.remove('d-none');
            // Disable flip button and hide card number
            document.querySelector('.flip-button').style.display = 'none';
            document.querySelector('.card-last-digits').style.display = 'none';
            return;
        }

        // Scenario 3: Active card
        if (data.card.cardStatus.toLowerCase() === 'active') {
            console.log('Scenario 3: Active card');
            const cardView = document.getElementById('user_card_find');
            console.log('Showing active card view');
            cardView.classList.remove('d-none');

            // Update validity image based on card status
            const validityImage = document.querySelector('.valid');
            if (validityImage) {
                validityImage.src = data.card.cardStatus.toLowerCase() === 'active' ?
                    '/static/images/valid.png' : '/static/images/unvalid.png';
            }

            // Update card details
            const cardNumber = document.querySelector('.card-number');
            const expiryValue = document.querySelector('.expiry-value');
            const balance = document.querySelector('.balance');
            const lastDigits = document.querySelector('.card-last-digits');

            // Format card number (show only last 4 digits on front)
            const last4Digits = data.card.cardNumber ? data.card.cardNumber.slice(-4) : '';
            console.log('Setting card number:', last4Digits);
            lastDigits.textContent = `*${last4Digits}`;

            // Format expiry date
            if (data.card.validDate) {
                expiryValue.textContent = data.card.validDate;
            }

            // Extract numeric part from "5.00 USD" or "1234.00 USD"
            let rawBalance = data.card.balance || "0.00 USD";
            let numericPart = rawBalance.split(' ')[0]; // "5.00" or "1234.00"
            let number = Number(numericPart);

            // Format with commas, remove decimals if .00
            let formatted = number % 1 === 0
                ? number.toLocaleString('en-US', { maximumFractionDigits: 0 })
                : number.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

            // Add $ after the number
            balance.textContent = `${formatted} $`;
            balance.style.display = 'block';

            // Set CVV for the card - store actual CVV only
            if (data.card.cvv) {
                window.cardCvv = data.card.cvv;
            } else {
                window.cardCvv = '';  // Empty string if no CVV
            }

            // Debug log without showing actual CVV
            console.log('CVV stored for later display');

            // Enable flip button
            document.querySelector('.flip-button').style.display = 'block';
            document.querySelector('.card-last-digits').style.display = 'block';

            // Store card data for later use
            window.currentCard = data.card;

            // Debug log to verify card details
            console.log('Card details updated:', {
                cardNumber: 'XXXX XXXX XXXX ' + last4Digits,
                expiryValue: data.card.validDate,
                balance: balance.textContent,
                lastDigits: lastDigits.textContent,
                cvv: '[HIDDEN]',
                cardData: '[MASKED]'
            });

            // --- Update back of the card ---
            // On card flip (back side)
            if (data.card.cardNumber) {
                const cardNumber = $('.card-info.back .card-number');
                if (cardNumber.length) {
                    // Remove all spaces first, then format
                    const rawNumber = data.card.cardNumber.replace(/\s+/g, '');
                    const formattedNumber = rawNumber.replace(/(\d{4})/g, '$1 ').trim();
                    cardNumber.html(`
                        <span style="margin-right: 10px;">${formattedNumber}</span>
                        <button class="copy-button" style="background: none; border: none; color: white; cursor: pointer; padding: 5px;">
                            <i class="fas fa-copy"></i>
                        </button>
                    `);

                    // Add click handler specifically to the button
                    cardNumber.find('.copy-button').on('click', function (e) {
                        e.preventDefault();
                        e.stopPropagation();

                        // Copy text without spaces
                        navigator.clipboard.writeText(rawNumber).then(() => {
                            $(this).find('i')
                                .removeClass('fa-copy')
                                .addClass('fa-check');
                            setTimeout(() => {
                                $(this).find('i')
                                    .removeClass('fa-check')
                                    .addClass('fa-copy');
                            }, 1000);
                        }).catch(err => {
                            console.error('Copy failed:', err);
                        });
                    });
                }
            }

            // Set expiry date (back)
            if (expiryValue) {
                expiryValue.textContent = data.card.validDate || 'MM/YY';
            }

            // Set CVV (back)
            const cvvDisplayBack = document.querySelector('.cvv-display');
            if (cvvDisplayBack) {
                // Initialize with eye icon
                cvvDisplayBack.innerHTML = eyeIconHTML;

                // Remove all existing event listeners
                const newCvvDisplay = cvvDisplayBack.cloneNode(true);
                cvvDisplayBack.parentNode.replaceChild(newCvvDisplay, cvvDisplayBack);

                // Add new click handler
                newCvvDisplay.addEventListener('click', function (e) {
                    e.stopPropagation(); // Prevent card flip

                    // Toggle between eye icon and CVV
                    if (this.innerHTML.includes('fa-eye')) {
                        this.textContent = data.card.cvv || '';
                    } else {
                        this.innerHTML = eyeIconHTML;
                    }
                });
            }
        } else {
            console.log('No active card found');
            document.getElementById('user_card_none').classList.remove('d-none');
        }

        // Handle transactions for active card only
        if (data.card && data.card.cardStatus.toLowerCase() === 'active' && data.transactions && data.transactions.length > 0) {
            const transactionsList = document.getElementById('transaction_find');
            transactionsList.classList.remove('d-none');
            transactionsList.innerHTML = ''; // Clear existing transactions

            // Store transactions for later use
            window.transactionsCache = data.transactions;

            let filteredTransactions = [];
            if (Array.isArray(data.transactions)) {
                filteredTransactions = data.transactions.filter(
                    tx => tx && !isNaN(Date.parse(tx.transaction_time || tx.timestamp))
                );
                if (filteredTransactions.length !== data.transactions.length) {
                    console.warn('Some transactions were filtered out due to missing or invalid timestamp:', data.transactions);
                }
            }
            const sortedTransactions = filteredTransactions.sort((a, b) =>
                new Date(b.transaction_time || b.timestamp) - new Date(a.transaction_time || a.timestamp)
            );

            // Show only the 5 most recent transactions
            const recentTransactions = sortedTransactions.slice(0, 5);

            // Show transactions in a table format
            transactionsList.innerHTML = `
                <table class="table table-striped table-bordered mb-0">
                    <thead class="table-light">
                        <tr>
                            <th>Type</th>
                            <th>Date</th>
                            <th>ID</th>
                            <th>Detail</th>
                            <th>Note</th>
                            <th>Fee</th>
                            <th>Status</th>
                            <th>Amount</th>
                        </tr>
                    </thead>
                    <tbody id="transactions-table-body"></tbody>
                </table>
            `;
            const tableBody = document.getElementById('transactions-table-body');

            recentTransactions.forEach(tx => {
                console.log('Transaction raw date:', tx.transaction_time || tx.timestamp);
                const date = getTransactionDate(tx);
                const formattedDate = date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
                const isCredit = tx.type === 'TransferIn' || tx.type === 'Deposit';
                const amountSign = isCredit ? '+' : '-';
                const feeSign = isCredit ? '+' : '-';
                const amountBadgeClass = isCredit ? 'bg-primary' : 'bg-danger';

                const row = document.createElement('tr');
                row.className = 'transaction-row';
                row.style.cursor = 'pointer';
                row.onclick = () => showTransactionDetails(tx);
                row.innerHTML = `
                    <td>${tx.type.charAt(0).toUpperCase() + tx.type.slice(1)}</td>
                    <td>${formattedDate}</td>
                    <td>${tx.id}</td>
                    <td>${tx.detail || ''}</td>
                    <td>${tx.note || ''}</td>
                    <td>
                        ${feeSign}${Math.abs(tx.fee).toLocaleString()} ${tx.currency}
                        ${tx.nova_fee_foreign ? `<br>+${tx.nova_fee_foreign.toFixed(2)} ${tx.transaction_currency}` : ''}
                    </td>
                    <td>${tx.status}</td>
                    <td>
                        <span class="badge ${amountBadgeClass}">
                            ${amountSign}$${Math.abs(tx.amount).toLocaleString()} ${tx.currency}
                            ${tx.transaction_amount ? `<br>${tx.transaction_amount.toFixed(2)} ${tx.transaction_currency}` : ''}
                        </span>
                    </td>
                `;
                tableBody.appendChild(row);
            });
        }
    } catch (error) {
        console.error('Error loading user data:', error);
        showError('Error loading user data');
    }
}

// Function to show block card confirmation modal
function showBlockCardModal() {
    if (!userId) {
        console.error('No user ID available');
        return;
    }

    // Create and show Bootstrap modal
    const modalHtml = `
        <div class="modal fade" id="blockCardModal" tabindex="-1" aria-labelledby="blockCardModalLabel" aria-hidden="true">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title" id="blockCardModalLabel">Block Card</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        Are you sure you want to block your card? This will prevent any new transactions.
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="button" class="btn btn-danger" id="confirmBlockCard">Block Card</button>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Remove any existing modal
    $('#blockCardModal').remove();

    // Add new modal to body
    $('body').append(modalHtml);

    // Initialize and show modal
    const modal = new bootstrap.Modal(document.getElementById('blockCardModal'));
    modal.show();

    // Handle confirm button click
    $('#confirmBlockCard').on('click', async function () {
        const btn = this;
        btn.disabled = true;
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Blocking...';
        try {
            const response = await secureFetch(`/api/block_card/${userId}`, {
                method: 'POST'
            });
            const data = await response.json();
            if (data.success) {
                if (cardData) cardData.cardStatus = 'blocked';
                updateCardDisplay();
                showAlert('Card blocked successfully', 'success');
            } else {
                showAlert(data.message || 'Failed to block card', 'danger');
            }
        } catch (error) {
            console.error('Error blocking card:', error);
            showAlert('Failed to block card', 'danger');
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
            modal.hide();
        }
    });
}

// Function to show unblock card confirmation modal
function showUnblockCardModal() {
    if (!userId) {
        console.error('No user ID available');
        return;
    }

    // Create and show Bootstrap modal
    const modalHtml = `
        <div class="modal fade" id="unblockCardModal" tabindex="-1" aria-labelledby="unblockCardModalLabel" aria-hidden="true">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title" id="unblockCardModalLabel">Unblock Card</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        Are you sure you want to unblock your card? This will allow new transactions.
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="button" class="btn btn-success" id="confirmUnblockCard">Unblock Card</button>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Remove any existing modal
    $('#unblockCardModal').remove();

    // Add new modal to body
    $('body').append(modalHtml);

    // Initialize and show modal
    const modal = new bootstrap.Modal(document.getElementById('unblockCardModal'));
    modal.show();

    // Handle confirm button click
    $('#confirmUnblockCard').on('click', async function () {
        const btn = this;
        btn.disabled = true;
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Unblocking...';
        try {
            const response = await secureFetch(`/api/unblock_card/${userId}`, {
                method: 'POST'
            });
            const data = await response.json();
            if (data.success) {
                if (cardData) cardData.cardStatus = 'active';
                updateCardDisplay();
                showAlert('Card unblocked successfully', 'success');
            } else {
                showAlert(data.message || 'Failed to unblock card', 'danger');
            }
        } catch (error) {
            console.error('Error unblocking card:', error);
            showAlert('Failed to unblock card', 'danger');
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
            modal.hide();
        }
    });
}

// --- Deposit Modal/Page Logic ---
async function showDepositModal() {
    if (!userId) {
        alert('User ID not found.');
        return;
    }

    // Get the deposit button and store its original state
    const depositButton = document.getElementById('deposit-button');
    if (!depositButton) return;

    // Store original button state
    const originalHtml = depositButton.innerHTML;
    const originalDisabled = depositButton.disabled;

    // Show loading state
    depositButton.disabled = true;
    depositButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Loading...';

    try {
        const res = await secureFetch(`/api/deposit_page/${userId}`);
        const data = await res.json();
        if (!data.success) {
            alert(data.message || 'Failed to get deposit address.');
            return;
        }
        // Create modal if not exists
        let modal = document.getElementById('deposit-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'deposit-modal';
            modal.style.position = 'fixed';
            modal.style.top = '0';
            modal.style.left = '0';
            modal.style.width = '100vw';
            modal.style.height = '100vh';
            modal.style.background = 'rgba(0,0,0,0.5)';
            modal.style.display = 'flex';
            modal.style.alignItems = 'center';
            modal.style.justifyContent = 'center';
            modal.style.zIndex = '9999';
            modal.innerHTML = `
              <div style="background:#fff;padding:2em;border-radius:10px;min-width:320px;max-width:90vw;text-align:center;position:relative;">
              <h3><b>USDT TRC20</b></h3>  
              <h2>Deposit Address</h2>
                <div id="deposit-limits" style="color:#555;font-size:1em;margin-bottom:0.5em;">
                  Min deposit: $100 &nbsp; | &nbsp; Max deposit: $100,000
                </div>
                <div id="deposit-address-container" style="margin-bottom:1em;">
                  <span id="deposit-address" style="font-size:1.1em;word-break:break-all;"></span>
                  <button id="copy-deposit-address" style="background:none;border:none;color:#007bff;cursor:pointer;margin-left:8px;">
                    <i class="fas fa-copy"></i>
                  </button>
                </div>
                <div id="deposit-qr" style="display:flex;justify-content:center;align-items:center;margin-bottom:1em;"></div>
                <button id="save-qr-btn" class="btn btn-outline-primary mt-2 mb-2">Save QR Code</button>
                <div id="deposit-timer" style="margin:1em 0;font-weight:bold;"></div>
                <button id="close-deposit-modal" class="btn btn-secondary mt-2">Close</button>
              </div>
            `;
            document.body.appendChild(modal);
            document.getElementById('close-deposit-modal').onclick = () => {
                modal.remove();
            };
        }
        // Helper to show/hide elements
        function setDepositModalVisibility(isExpired) {
            const expiredMsg = document.getElementById('deposit-expired-message');
            const addressContainer = document.getElementById('deposit-address-container');
            const qr = document.getElementById('deposit-qr');
            const saveBtn = document.getElementById('save-qr-btn');
            if (!expiredMsg || !addressContainer || !qr || !saveBtn) return;

            expiredMsg.style.display = isExpired ? 'block' : 'none';
            addressContainer.style.display = isExpired ? 'none' : 'block';
            qr.style.display = isExpired ? 'none' : 'flex';
            saveBtn.style.display = isExpired ? 'none' : 'inline-block';
        }
        // If expired, show only the message
        if (data.expired) {
            setDepositModalVisibility(true);
            document.getElementById('deposit-timer').textContent = '';
            modal.style.display = 'flex';
            return;
        } else {
            setDepositModalVisibility(false);
        }
        // Show address
        document.getElementById('deposit-address').textContent = data.address;
        // Copy button logic
        const copyBtn = document.getElementById('copy-deposit-address');
        copyBtn.onclick = function (e) {
            e.preventDefault();
            navigator.clipboard.writeText(data.address).then(() => {
                copyBtn.querySelector('i').classList.remove('fa-copy');
                copyBtn.querySelector('i').classList.add('fa-check');
                setTimeout(() => {
                    copyBtn.querySelector('i').classList.remove('fa-check');
                    copyBtn.querySelector('i').classList.add('fa-copy');
                }, 1200);
            });
        };
        // Generate QR code (use QRCode.js or fallback to Google Charts)
        let qrDiv = document.getElementById('deposit-qr');
        qrDiv.innerHTML = '';
        let qrInstance = null;
        if (window.QRCode) {
            qrInstance = new QRCode(qrDiv, { text: data.address, width: 180, height: 180 });
        } else {
            // Fallback: Google Charts
            qrDiv.innerHTML = `<img id="deposit-qr-img" src="https://chart.googleapis.com/chart?cht=qr&chs=180x180&chl=${encodeURIComponent(data.address)}" alt="QR Code">`;
        }
        // Save QR code button logic
        const saveBtn = document.getElementById('save-qr-btn');
        saveBtn.onclick = async function () {
            try {
                let imgDataUrl = null;
                // If QRCode.js is used, get the canvas or img
                const qrImg = qrDiv.querySelector('img');
                const qrCanvas = qrDiv.querySelector('canvas');

                if (qrImg && qrImg.src) {
                    imgDataUrl = qrImg.src;
                } else if (qrCanvas) {
                    imgDataUrl = qrCanvas.toDataURL('image/png');
                }

                if (!imgDataUrl) {
                    throw new Error('No QR code image found');
                }

                // Check if we're in Telegram WebApp
                if (window.Telegram && window.Telegram.WebApp) {
                    // Convert base64 to blob
                    const response = await fetch(imgDataUrl);
                    const blob = await response.blob();

                    // Create a temporary link element
                    const link = document.createElement('a');
                    link.href = URL.createObjectURL(blob);
                    link.download = 'deposit_qr.png';

                    // Trigger download
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);

                    // Clean up the object URL
                    URL.revokeObjectURL(link.href);

                    showAlert('QR code saved successfully', 'success');
                } else {
                    // Fallback to standard browser download
                    const a = document.createElement('a');
                    a.href = imgDataUrl;
                    a.download = 'deposit_qr.png';
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    showAlert('QR code downloaded successfully', 'success');
                }
            } catch (error) {
                console.error('Error saving QR code:', error);
                showAlert('Unable to save QR code. Please try again.', 'danger');
            }
        };
        // Timer
        let seconds = (data.timer_minutes * 60) + (data.timer_seconds || 0);
        const timerDiv = document.getElementById('deposit-timer');
        function updateTimer() {
            if (seconds <= 0) {
                setDepositModalVisibility(true);
                timerDiv.textContent = 'Expired. Please press deposit again.';
                return;
            }
            const m = Math.floor(seconds / 60);
            const s = seconds % 60;
            timerDiv.textContent = `Valid for: ${m}:${s.toString().padStart(2, '0')}`;
            seconds--;
            setTimeout(updateTimer, 1000);
        }
        updateTimer();
        modal.style.display = 'flex';
    } catch (error) {
        console.error('Error showing deposit modal:', error);
        alert('Failed to load deposit information. Please try again.');
    } finally {
        // Restore button state
        depositButton.disabled = originalDisabled;
        depositButton.innerHTML = originalHtml;
    }
}
// Attach to deposit button
const depositButton = document.getElementById('deposit-button');
if (depositButton) {
    depositButton.onclick = showDepositModal;
}

// Add showError function at the top of the file
function showError(message) {
    console.error('Error:', message);
    const errorDiv = document.getElementById('error-message');
    if (errorDiv) {
        errorDiv.textContent = message;
        errorDiv.style.display = 'block';
        setTimeout(() => {
            errorDiv.style.display = 'none';
        }, 5000);
    } else {
        alert(message);
    }
}